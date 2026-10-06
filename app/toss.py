"""
===========================================================
  토스증권 Open API — 시세 · 캔들 (조회 전용)
===========================================================

**주문 엔드포인트는 호출하지 않는다.** 이 모듈에는 주문 코드가 없다.
키에 주문 권한이 딸려 있더라도 시세·캔들만 쓴다.

[ 문서가 없어 실측으로 확인한 규격 ]
  토큰    POST /oauth2/token   grant_type=client_credentials   → 24시간
  종목    GET  /api/v1/stocks?symbols=006400     ← symbols (복수형)
  현재가   GET  /api/v1/prices?symbols=006400     ← symbols (복수형)
  캔들    GET  /api/v1/candles?symbol=006400&interval=1d&count=N   ← symbol (단수형)

  캔들 주기는 1d / 1m 두 개뿐이다. 5분·15분봉은 1분봉을 묶어서 만든다.
  지수 심볼(^IXIC, ^SOX)은 받지 않는다. ETF 로 대신한다 (QQQ, SOXX).

환경변수 TOSS_CLIENT_ID / TOSS_CLIENT_SECRET 가 없으면 조용히 비활성화된다.

[ 해외 IP 차단 — 실측 ]
  GitHub Actions(미국) 에서 /oauth2/token 과 도메인 루트가 모두 HTTP 403.
  그래서 수집(런너)에서는 토스를 쓰지 못한다.
    매크로 → macro.py (야후, 키 불필요)
    일봉   → charts.py (pykrx)
  토스는 **분봉 전용**으로 남긴다. 한국에서 돌릴 때만(시작.bat) 붙는다.
===========================================================
"""

import gzip
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

BASE = "https://openapi.tossinvest.com"
TOKEN_URL = f"{BASE}/oauth2/token"

# 투자원칙 a: "매크로 무조건 확인(나스닥+유가+환율)"
# 지수 심볼을 안 받으므로 같은 움직임을 따라가는 ETF 로 본다
MACRO = [
    ("QQQ", "나스닥100", "지수 심볼 미지원 → ETF 대용"),
    ("SOXX", "필라델피아 반도체", "지수 심볼 미지원 → ETF 대용"),
    ("USO", "WTI 원유", "원유 ETF"),
]

_token: tuple[str, float] | None = None     # (access_token, 만료시각)
_blocked = False                            # 해외 IP 차단(403) 을 만나면 더 두드리지 않는다


def available() -> bool:
    cid = os.environ.get("TOSS_CLIENT_ID")
    sec = os.environ.get("TOSS_CLIENT_SECRET")
    if not cid or not sec or cid == "CHANGEME" or sec == "CHANGEME":
        return False
    return True


def _decode(raw: bytes) -> str:
    if raw[:2] == b"\x1f\x8b":
        try:
            raw = gzip.decompress(raw)
        except Exception:
            pass
    return raw.decode("utf-8", "replace")


def token() -> str | None:
    """24시간짜리 액세스 토큰. 만료 5분 전에 갱신한다."""
    global _token
    if not available():
        return None
    if _token and time.time() < _token[1] - 300:
        return _token[0]

    global _blocked
    if _blocked:
        return None

    body = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": os.environ["TOSS_CLIENT_ID"],
        "client_secret": os.environ["TOSS_CLIENT_SECRET"],
    }).encode()
    req = urllib.request.Request(
        TOKEN_URL, data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            res = json.loads(_decode(r.read()))
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            _blocked = True
            print("  토스 403 — 해외 IP 차단. 분봉은 한국에서 돌릴 때만 붙습니다.")
        else:
            print(f"  토스 토큰 발급 실패: HTTP {exc.code}")
        return None
    except Exception as exc:
        print(f"  토스 토큰 발급 실패: {type(exc).__name__}: {exc}")
        return None

    tok = res.get("access_token")
    if not tok:
        return None
    _token = (tok, time.time() + float(res.get("expires_in", 3600)))
    return tok


def _get(path: str) -> dict | None:
    tok = token()
    if not tok:
        return None
    url = BASE + urllib.parse.quote(path, safe="/?=&,:")
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {tok}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(_decode(r.read()))
    except urllib.error.HTTPError as e:
        detail = _decode(e.read())[:160]
        print(f"  토스 {e.code} {path.split('?')[0]} — {detail}")
    except Exception as exc:
        print(f"  토스 호출 실패 {type(exc).__name__}: {exc}")
    return None


# ────────────────────────────────────────────────
# 조회
# ────────────────────────────────────────────────
def prices(symbols: list[str]) -> dict[str, float]:
    """심볼 → 현재가. 한 번에 여러 개."""
    if not symbols:
        return {}
    res = _get("/api/v1/prices?symbols=" + ",".join(symbols))
    out = {}
    for row in (res or {}).get("result", []) or []:
        try:
            out[row["symbol"]] = float(row["lastPrice"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


def candles(symbol: str, interval: str = "1d", count: int = 30) -> list[dict]:
    """일봉(1d) 또는 분봉(1m). 최신이 앞에 온다 → 오래된 순으로 뒤집어 돌려준다."""
    res = _get(f"/api/v1/candles?symbol={symbol}&interval={interval}&count={count}")
    rows = (res or {}).get("result", {}).get("candles", []) or []
    out = []
    for c in rows:
        try:
            out.append({
                "시각": c["timestamp"],
                "시가": float(c["openPrice"]),
                "고가": float(c["highPrice"]),
                "저가": float(c["lowPrice"]),
                "종가": float(c["closePrice"]),
                "거래량": float(c.get("volume") or 0),
            })
        except (KeyError, TypeError, ValueError):
            continue
    return list(reversed(out))


def resample(minute_candles: list[dict], minutes: int) -> list[dict]:
    """1분봉을 묶어 5분·15분봉을 만든다. 토스가 5m/15m 을 안 주기 때문이다."""
    if not minute_candles or minutes <= 1:
        return minute_candles
    out: list[dict] = []
    for i in range(0, len(minute_candles), minutes):
        chunk = minute_candles[i:i + minutes]
        if not chunk:
            continue
        out.append({
            "시각": chunk[0]["시각"],
            "시가": chunk[0]["시가"],
            "고가": max(c["고가"] for c in chunk),
            "저가": min(c["저가"] for c in chunk),
            "종가": chunk[-1]["종가"],
            "거래량": sum(c["거래량"] for c in chunk),
        })
    return out


# ────────────────────────────────────────────────
# 분석 — 투자원칙에 쓰이는 판정들
# ────────────────────────────────────────────────
def chart_read(symbol: str, lookback: int = 60) -> dict:
    """일봉으로 전고점 돌파·끼·이평선을 본다.

    투자원칙 6 전고점돌파 패턴 / 1.2 "끼 — 윗꼬리 없고 과거 상을 잘 가는 종목"
    """
    rows = candles(symbol, "1d", lookback)
    if len(rows) < 6:
        return {}

    closes = [r["종가"] for r in rows]
    last = rows[-1]
    prior = rows[:-1]

    def ma(n):
        return round(sum(closes[-n:]) / n, 1) if len(closes) >= n else None

    prior_high = max(r["고가"] for r in prior)
    rng = last["고가"] - last["저가"]
    upper_tail = (last["고가"] - last["종가"]) / rng * 100 if rng else 0
    body = abs(last["종가"] - last["시가"]) / rng * 100 if rng else 0

    # 과거에 상한가 근처까지 간 날이 몇 번이나 되나 = '끼'
    spikes = 0
    for i in range(1, len(rows)):
        prev = rows[i - 1]["종가"]
        if prev > 0 and (rows[i]["종가"] / prev - 1) * 100 >= 20:
            spikes += 1

    return {
        "MA5": ma(5), "MA20": ma(20), "MA60": ma(60),
        "전고점": round(prior_high, 1),
        "전고점돌파": bool(last["종가"] > prior_high),
        "윗꼬리(%)": round(upper_tail, 1),
        "몸통(%)": round(body, 1),
        "장대양봉": bool(body >= 60 and upper_tail <= 15 and last["종가"] > last["시가"]),
        "끼(20%급등일수)": spikes,
        "기간": len(rows),
    }


def intraday_leader(symbols: list[str], minutes: int = 5) -> list[dict]:
    """장중 대장주 추적 — 투자원칙 1.3 "장중 대장주가 바뀌기도 하니 거래대금 위주 모니터링".

    1분봉을 묶어 최근 구간의 거래량 흐름을 본다.
    """
    out = []
    for sym in symbols[:10]:                 # 호출 수를 제한한다
        mins = candles(sym, "1m", 120)
        if not mins:
            continue
        bars = resample(mins, minutes)
        if len(bars) < 2:
            continue
        recent, before = bars[-1], bars[-2]
        out.append({
            "심볼": sym,
            "최근거래량": recent["거래량"],
            "직전거래량": before["거래량"],
            "거래량증감(%)": round((recent["거래량"] / before["거래량"] - 1) * 100, 1)
            if before["거래량"] else None,
            "종가": recent["종가"],
        })
    out.sort(key=lambda x: -(x["최근거래량"] or 0))
    return out


def macro() -> list[dict]:
    """나스닥·반도체·유가. 투자원칙 a 의 매크로 확인."""
    if not available():
        return []
    out = []
    for sym, name, note in MACRO:
        rows = candles(sym, "1d", 3)
        if len(rows) < 2:
            continue
        last, prev = rows[-1], rows[-2]
        chg = (last["종가"] / prev["종가"] - 1) * 100 if prev["종가"] else None
        out.append({
            "이름": name, "심볼": sym,
            "종가": round(last["종가"], 2),
            "전일": round(prev["종가"], 2),
            "등락률": round(chg, 2) if chg is not None else None,
            "비고": note,
        })
    return out
