"""
===========================================================
  차트 판정 — 전고점 돌파 · 끼 · 이평선
===========================================================

투자원칙
  1.2  "끼 (윗꼬리 없고, 과거 상을 잘 가는 종목) / 차트 / 수급"
  6    "전고점돌파 패턴 파악"

[ 왜 pykrx 인가 ]
  토스 Open API 는 해외 IP 를 막는다. 수집은 미국 런너에서 돈다.
  **일봉은 KRX 로 충분하다** — 전고점·이평선·캔들 모양은 전부 일봉으로 나온다.
  분봉(장중 대장주 교체 추적)만 토스가 필요하고, 그건 한국에서 돌릴 때만 붙는다.

KRX 로그인 세션이 필요하다 (수집기가 이미 만들어 둔다).
===========================================================
"""

from datetime import datetime, timedelta

LOOKBACK_DAYS = 120          # 달력일. 영업일로는 약 80일
SPIKE_PCT = 20.0             # 하루 20% 이상 = '상 잘 가는' 날
BODY_MIN = 60.0              # 장대양봉 몸통 비율
TAIL_MAX = 15.0              # 윗꼬리 허용치


def _history(ticker: str, target_date: str):
    from pykrx import stock

    end = datetime.strptime(target_date, "%Y%m%d")
    start = end - timedelta(days=LOOKBACK_DAYS)
    try:
        df = stock.get_market_ohlcv_by_date(
            start.strftime("%Y%m%d"), target_date, ticker)
    except Exception:
        return None
    if df is None or df.empty:
        return None
    return df[df["종가"] > 0]


def read(ticker: str, target_date: str) -> dict:
    """일봉으로 전고점·이평선·캔들 모양·끼를 본다."""
    df = _history(ticker, target_date)
    if df is None or len(df) < 6:
        return {}

    close = df["종가"].astype(float)
    high = df["고가"].astype(float)
    low = df["저가"].astype(float)
    open_ = df["시가"].astype(float)

    last_close = float(close.iloc[-1])
    last_high, last_low = float(high.iloc[-1]), float(low.iloc[-1])
    last_open = float(open_.iloc[-1])

    def ma(n):
        return round(float(close.tail(n).mean()), 1) if len(close) >= n else None

    prior_high = float(high.iloc[:-1].max())
    rng = last_high - last_low
    윗꼬리 = (last_high - last_close) / rng * 100 if rng else 0.0
    몸통 = abs(last_close - last_open) / rng * 100 if rng else 0.0

    # '끼' — 과거에 하루 20% 넘게 간 날이 몇 번인가
    daily = close.pct_change() * 100
    끼 = int((daily >= SPIKE_PCT).sum())

    ma20 = ma(20)
    return {
        "MA5": ma(5), "MA20": ma20, "MA60": ma(60),
        "전고점": round(prior_high, 1),
        "전고점돌파": bool(last_close > prior_high),
        "전고점대비(%)": round((last_close / prior_high - 1) * 100, 2) if prior_high else None,
        "윗꼬리(%)": round(윗꼬리, 1),
        "몸통(%)": round(몸통, 1),
        "장대양봉": bool(몸통 >= BODY_MIN and 윗꼬리 <= TAIL_MAX and last_close > last_open),
        "끼(20%급등일수)": 끼,
        "20일선위": bool(ma20 and last_close > ma20),
        "영업일수": int(len(df)),
    }


def attach(leaders: list[dict], rows: list[dict], target_date: str) -> int:
    """대장주 후보에만 차트 판정을 붙인다. 붙인 개수를 돌려준다."""
    붙임 = 0
    by_name = {r.get("종목명"): r.get("티커") for r in rows}
    for c in leaders:
        ticker = by_name.get(c.get("종목명"))
        if not ticker:
            continue
        try:
            got = read(str(ticker).zfill(6), target_date)
        except Exception:
            got = {}
        if got:
            c["차트"] = got
            붙임 += 1
    return 붙임
