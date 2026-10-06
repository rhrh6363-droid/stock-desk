"""
===========================================================
  매크로 지표 — 나스닥 · 반도체 · 유가 · 환율
===========================================================

투자원칙 a: "시장분위기 = 매크로 무조건 확인(나스닥 + 유가 + 환율)"

[ 왜 야후인가 ]
  토스 Open API 는 해외 IP 를 차단한다 (GitHub 런너에서 HTTP 403).
  수집은 미국 런너에서 돌므로 토스로는 매크로를 못 받는다.
  야후는 키가 필요 없고, 대용 ETF 가 아니라 **지수 원본**을 준다.
    ^IXIC  나스닥 종합
    ^SOX   필라델피아 반도체
    CL=F   WTI 원유 선물
    KRW=X  원/달러

실패해도 전체를 멈추지 않는다. 빈 리스트를 돌려준다.
===========================================================
"""

import json
import urllib.error
import urllib.parse
import urllib.request

CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=10d&interval=1d"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

SYMBOLS = [
    ("^IXIC", "나스닥", ""),
    ("^SOX", "필라델피아 반도체", "국내 반도체 선행"),
    ("CL=F", "WTI 유가", "원가·화학·정유"),
    ("KRW=X", "원/달러", "외국인 수급"),
]


def _fetch(symbol: str) -> dict | None:
    url = CHART.format(sym=urllib.parse.quote(symbol))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            body = json.loads(r.read())
    except Exception:
        return None

    try:
        res = body["chart"]["result"][0]
        closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
        if len(closes) < 2:
            return None
        return {"종가": float(closes[-1]), "전일": float(closes[-2]),
                "통화": res.get("meta", {}).get("currency", "")}
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def snapshot() -> list[dict]:
    """매크로 한 줄씩. 못 받은 항목은 빠진다."""
    out = []
    for sym, name, note in SYMBOLS:
        d = _fetch(sym)
        if not d:
            continue
        prev = d["전일"]
        chg = (d["종가"] / prev - 1) * 100 if prev else None
        out.append({
            "이름": name,
            "심볼": sym,
            "종가": round(d["종가"], 2),
            "전일": round(prev, 2),
            "등락률": round(chg, 2) if chg is not None else None,
            "통화": d["통화"],
            "비고": note,
        })
    return out
