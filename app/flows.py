"""
===========================================================
  투자자별 매매 현황 — 외국인 · 기관
===========================================================

사용자 지시: "거래대금이 쏠리는 종목의 원인, 투자자 별 매매 현황이
기관이나 외국인인 경우도 체크해줘"

거래대금이 터진 이유가 **누구 돈인지**를 본다.
  외국인·기관 순매수  →  수급이 들어온 것. 재료에 무게가 있다
  개인만 순매수       →  개인 쏠림. 다음 날 되돌림 위험이 크다

KRX 전종목 순매수를 투자자별로 한 번씩 받아 티커로 붙인다.
(종목별 개별 조회가 아니라 시장 전체 1회 호출 × 투자자 2명 = 2회)

로그인 세션이 필요하다. 실패하면 조용히 비우고 전체를 멈추지 않는다.
===========================================================
"""

import pandas as pd

# pykrx 투자자 구분 이름. '기관합계' 가 연기금·투신·보험 등을 모두 포함한다.
INVESTORS = {"외국인": "외국인", "기관": "기관합계"}
MARKET = "ALL"                      # 코스피 + 코스닥

COLUMNS = ["외국인순매수(억)", "기관순매수(억)", "수급주체"]


def _fetch(date: str, investor: str) -> dict[str, float]:
    """티커 → 순매수 거래대금(억). 실패하면 빈 dict."""
    from pykrx import stock

    try:
        df = stock.get_market_net_purchases_of_equities_by_ticker(
            date, date, MARKET, investor)
    except Exception as exc:
        print(f"    {investor} 조회 실패: {type(exc).__name__}: {exc}")
        return {}

    if df is None or df.empty:
        return {}

    col = next((c for c in df.columns if "순매수" in c and "거래대금" in c), None)
    if col is None:
        return {}

    out = {}
    for ticker, val in df[col].items():
        try:
            out[str(ticker).zfill(6)] = round(float(val) / 1e8, 1)
        except (TypeError, ValueError):
            continue
    return out


def _label(foreign: float | None, inst: float | None) -> str:
    """수급 주체 한 줄 요약. 억 단위."""
    f = foreign or 0.0
    i = inst or 0.0
    if f <= 0 and i <= 0:
        return "개인"                      # 외국인·기관 둘 다 순매도 → 개인 쏠림
    if f > 0 and i > 0:
        return "외국인+기관"
    return "외국인" if f > 0 else "기관"


def attach(rows: list[dict], date: str) -> dict:
    """RAW 행에 외국인·기관 순매수와 수급주체를 붙인다. 통계를 돌려준다."""
    if not rows:
        return {"조회": 0, "사유": "대상 종목 없음"}

    tables = {name: _fetch(date, code) for name, code in INVESTORS.items()}
    if not any(tables.values()):
        for r in rows:
            for c in COLUMNS:
                r[c] = None
        return {"조회": 0, "사유": "KRX 투자자별 매매 조회 실패"}

    맞은수 = 0
    주체집계: dict[str, int] = {}

    for r in rows:
        ticker = str(r.get("티커") or "").zfill(6)
        f = tables.get("외국인", {}).get(ticker)
        i = tables.get("기관", {}).get(ticker)
        r["외국인순매수(억)"] = f
        r["기관순매수(억)"] = i
        if f is None and i is None:
            r["수급주체"] = None
            continue
        주체 = _label(f, i)
        r["수급주체"] = 주체
        주체집계[주체] = 주체집계.get(주체, 0) + 1
        맞은수 += 1

    return {"조회": 맞은수, "전체": len(rows), "주체": 주체집계}


def summary(rows: list[dict]) -> list[dict]:
    """수급주체별 종목수·거래대금 — 일일보고서에 쓴다."""
    if not rows:
        return []
    df = pd.DataFrame(rows)
    if "수급주체" not in df.columns:
        return []
    df = df[df["수급주체"].notna()]
    if df.empty:
        return []

    out = []
    for 주체, part in df.groupby("수급주체"):
        out.append({
            "주체": str(주체),
            "종목수": int(len(part)),
            "거래대금": int(part["거래대금(억)"].sum()),
            "평균등락률": round(float(part["등락률(%)"].mean()), 2),
        })
    out.sort(key=lambda x: -x["거래대금"])
    return out
