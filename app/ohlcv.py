"""
===========================================================
  시세 소스 한 군데로 모으기  —  일봉 OHLCV
===========================================================

심층분석·지수매크로가 같은 모양의 캔들을 쓰도록 여기서만 받는다.

[ 소스를 두 개 쓰는 이유 — 실측 ]
  pykrx  단일종목 일봉은 **KRX 로그인 없이도 된다** (전종목 대량조회만 로그인 필요).
         대신 `get_index_ohlcv` 는 로그인이 있어야 하고, 단일종목 응답에
         **거래대금 열이 없다** (시가 고가 저가 종가 거래량 등락률).
  야후   키가 필요 없고 지수 원본을 준다. ^KS11 ^KQ11 ^IXIC ^GSPC ^SOX ^VIX
         CL=F KRW=X 005930.KS 000660.KS 10/10 실측 통과.
         브라우저에서는 못 쓴다 — 응답에 CORS 헤더가 없다. 서버에서만 받는다.

  → 국내 종목: pykrx 우선, 실패하면 야후(.KS/.KQ)
     지수·해외: 야후만

거래대금은 단일종목 응답에 없으므로 **거래량 × 종가로 추정**한다.
키 이름을 "추정거래대금" 으로 둔 건 그게 추정값이라는 걸 화면에서도 밝히기 위함이다.
===========================================================
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
YAHOO = ("https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
         "?range={rng}&interval=1d")

_cache: dict[tuple, list[dict]] = {}


# ────────────────────────────────────────────────
# 야후
# ────────────────────────────────────────────────
def from_yahoo(symbol: str, days: int = 400) -> list[dict]:
    """야후 일봉. 지수·해외·국내 전부 같은 모양으로 돌려준다."""
    rng = "2y" if days > 400 else "1y" if days > 200 else "6mo" if days > 100 else "3mo"
    url = YAHOO.format(sym=urllib.parse.quote(symbol), rng=rng)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            body = json.loads(r.read())
        res = body["chart"]["result"][0]
        ts = res["timestamp"]
        q = res["indicators"]["quote"][0]
    except Exception:
        return []

    out = []
    for i, t in enumerate(ts):
        try:
            c = q["close"][i]
            if c is None:
                continue
            out.append({
                "날짜": datetime.fromtimestamp(t).strftime("%Y-%m-%d"),
                "시가": float(q["open"][i] if q["open"][i] is not None else c),
                "고가": float(q["high"][i] if q["high"][i] is not None else c),
                "저가": float(q["low"][i] if q["low"][i] is not None else c),
                "종가": float(c),
                "거래량": float(q["volume"][i] or 0),
            })
        except (KeyError, IndexError, TypeError, ValueError):
            continue
    for r in out:
        r["추정거래대금"] = r["거래량"] * r["종가"]
    return out[-days:]


def yahoo_meta(symbol: str) -> dict:
    """이름·통화만 필요할 때. 실패하면 빈 dict."""
    url = YAHOO.format(sym=urllib.parse.quote(symbol), rng="5d")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as r:
            meta = json.loads(r.read())["chart"]["result"][0].get("meta", {})
    except Exception:
        return {}
    return {"이름": meta.get("shortName") or "", "통화": meta.get("currency") or ""}


# ────────────────────────────────────────────────
# KRX
# ────────────────────────────────────────────────
def from_krx(ticker: str, end: str, days: int = 400) -> list[dict]:
    """pykrx 일봉. 국내 종목용. 로그인 없이도 단일종목은 나온다."""
    try:
        from pykrx import stock
    except Exception:
        return []

    base = datetime.strptime(end, "%Y%m%d")
    start = base - timedelta(days=int(days * 1.6) + 30)      # 달력일 → 영업일 여유
    try:
        df = stock.get_market_ohlcv_by_date(
            start.strftime("%Y%m%d"), end, str(ticker).zfill(6))
    except Exception:
        return []
    if df is None or df.empty:
        return []
    df = df[df["종가"] > 0]

    out = []
    for idx, row in df.iterrows():
        try:
            close = float(row["종가"])
            vol = float(row.get("거래량") or 0)
            out.append({
                "날짜": idx.strftime("%Y-%m-%d"),
                "시가": float(row["시가"]), "고가": float(row["고가"]),
                "저가": float(row["저가"]), "종가": close,
                "거래량": vol,
                # 단일종목 응답에는 거래대금이 없다. 거래량×종가로 추정한다
                "추정거래대금": vol * close,
            })
        except (KeyError, TypeError, ValueError):
            continue
    return out[-days:]


# ────────────────────────────────────────────────
# 입구
# ────────────────────────────────────────────────
def daily(code: str, end: str | None = None, days: int = 400,
          market: str = "KS") -> list[dict]:
    """국내 종목 일봉. pykrx → 야후 순으로 시도한다.

    code    6자리 종목코드
    end     YYYYMMDD. 없으면 오늘
    market  야후 폴백용 접미사. 코스닥이면 "KQ"
    """
    end = end or datetime.today().strftime("%Y%m%d")
    key = ("krx", code, end, days)
    if key in _cache:
        return _cache[key]

    rows = from_krx(code, end, days)
    if len(rows) < 30:
        rows = from_yahoo(f"{str(code).zfill(6)}.{market}", days)
        if len(rows) < 30 and market == "KS":
            rows = from_yahoo(f"{str(code).zfill(6)}.KQ", days)
    _cache[key] = rows
    return rows


def index_daily(symbol: str, days: int = 400) -> list[dict]:
    """지수·해외·선물·환율. 야후만 쓴다 (pykrx 지수는 KRX 로그인이 필요)."""
    key = ("yh", symbol, days)
    if key not in _cache:
        _cache[key] = from_yahoo(symbol, days)
    return _cache[key]
