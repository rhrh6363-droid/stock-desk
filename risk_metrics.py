"""
===========================================================
  종목별 위험지표  —  RSI · 볼밴σ2 · 이격도 · 평균변동폭
===========================================================

ADR 은 시장 지표라 종목 하나에는 쓸 수 없다. 종목 단위 위험은 아래 4개가 담당한다.

  RSI(14)          70 이상 과매수 / 30 이하 과매도        <확정>
  볼밴 σ2 위치      상단으로 갈수록 위험률 상승            <확정>
  이격도(20일)      종가 ÷ MA20 × 100                    <확정>
  평균변동폭(20일)   그 종목의 '정상' 일중 변동폭            <제안>

평균변동폭은 **대상일을 제외한 직전 20거래일**로 계산한다.
특징주로 걸린 당일은 그 자체가 이상치여서 평균에 넣으면 기준이 망가진다.

손절·익절 제안은 전부 <제안> 이다. 사용자 확정 규칙이 아니다.
  제안손절 = 평균변동폭 × STOP_MULTIPLE
  제안익절 = 제안손절 × 3          ← 3:1 손익비 (사용자 확정)
===========================================================
"""

from datetime import datetime, timedelta

import pandas as pd
from pykrx import stock

RSI_PERIOD = 14
BB_PERIOD = 20
BB_SIGMA = 2
RANGE_WINDOW = 20

# 하루 노이즈 바깥에 손절을 두기 위한 배수. <제안> — 사용자 확정값이 아니다.
STOP_MULTIPLE = 1.5

HISTORY_DAYS = 160          # MA20·RSI14 를 안정적으로 채우기 위한 조회 기간(달력일)

# 투자원칙 7 — 이틀 누적 40% 이상이면 과열. 거래대금 조단위면 예외 (판정은 집계기에서)
OVERHEAT_2D = 40.0

COLUMNS = ["RSI(14)", "볼밴위치", "볼밴%B", "이격도", "평균변동폭(20일)",
           "제안손절(%)", "제안익절(%)", "2일누적(%)"]


def _col(df: pd.DataFrame, names: list[str]) -> str | None:
    return next((n for n in names if n in df.columns), None)


def _rsi(close: pd.Series, period: int = RSI_PERIOD) -> float | None:
    """Wilder RSI. 0~100 범위를 벗어날 수 없다."""
    if len(close) < period + 1:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean().iloc[-1]
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean().iloc[-1]
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 1)


def _band_label(pct_b: float) -> str:
    if pct_b >= 100:
        return "상단돌파"
    if pct_b >= 80:
        return "상단"
    if pct_b >= 60:
        return "중상단"
    if pct_b >= 40:
        return "중심"
    if pct_b >= 20:
        return "중하단"
    return "하단"


def _metrics_for(ticker: str, target_date: str) -> dict:
    """종목 1개의 지표. 조회 실패나 데이터 부족이면 None 으로 채운다.

    `get_market_ohlcv_by_date` 는 종목당 0.1초 미만이라 수십 종목은 몇 초면 끝난다.
    """
    blank = {c: None for c in COLUMNS}

    end = datetime.strptime(target_date, "%Y%m%d")
    start = end - timedelta(days=HISTORY_DAYS)

    try:
        hist = stock.get_market_ohlcv_by_date(
            start.strftime("%Y%m%d"), target_date, str(ticker)
        )
    except Exception:
        return blank
    if hist is None or hist.empty:
        return blank

    close_c = _col(hist, ["종가", "close"])
    high_c = _col(hist, ["고가", "high"])
    low_c = _col(hist, ["저가", "low"])
    if not close_c:
        return blank

    hist = hist[hist[close_c] > 0]
    close = hist[close_c].astype(float)
    out = dict(blank)

    # ── RSI
    out["RSI(14)"] = _rsi(close)

    # ── 볼린저밴드 σ2 · 이격도
    if len(close) >= BB_PERIOD:
        ma = close.rolling(BB_PERIOD).mean().iloc[-1]
        sd = close.rolling(BB_PERIOD).std(ddof=0).iloc[-1]
        last = close.iloc[-1]
        if sd and sd > 0:
            upper, lower = ma + BB_SIGMA * sd, ma - BB_SIGMA * sd
            pct_b = (last - lower) / (upper - lower) * 100
            out["볼밴%B"] = round(pct_b, 1)
            out["볼밴위치"] = _band_label(pct_b)
        if ma:
            out["이격도"] = round(last / ma * 100, 1)

    # ── 평균 일중변동폭: 대상일을 뺀 직전 20거래일
    # 2일 누적 상승률 — 전전일 종가 대비 당일 종가
    if len(close) >= 3:
        base = float(close.iloc[-3])
        if base > 0:
            out["2일누적(%)"] = round((float(close.iloc[-1]) / base - 1) * 100, 2)

    if high_c and low_c and len(hist) >= RANGE_WINDOW + 1:
        prior = hist.iloc[:-1].tail(RANGE_WINDOW)
        lows = prior[low_c].astype(float)
        rng = ((prior[high_c].astype(float) - lows) / lows * 100)
        avg_range = rng.mean()
        if pd.notna(avg_range) and avg_range > 0:
            stop = avg_range * STOP_MULTIPLE
            out["평균변동폭(20일)"] = round(avg_range, 2)
            out["제안손절(%)"] = -round(stop, 2)
            out["제안익절(%)"] = round(stop * 3, 2)

    return out


def add_risk_metrics(df: pd.DataFrame, target_date: str) -> pd.DataFrame:
    """특징주 표에 종목별 위험지표 컬럼을 붙인다. 티커 컬럼이 있어야 한다."""
    if df is None or df.empty or "티커" not in df.columns:
        return df

    total = len(df)
    print(f"\n  종목별 위험지표 계산 ({total}종목)", flush=True)

    rows = []
    for n, ticker in enumerate(df["티커"], 1):
        rows.append(_metrics_for(ticker, target_date))
        if n % 10 == 0 or n == total:
            print(f"    {n}/{total}", flush=True)

    metrics = pd.DataFrame(rows, index=df.index)[COLUMNS]
    merged = pd.concat([df, metrics], axis=1)

    done = int(metrics["RSI(14)"].notna().sum())
    if done < total:
        print(f"  * {total - done}종목은 이력이 부족해 지표를 비워뒀습니다.")

    overheat = metrics["RSI(14)"].dropna()
    if len(overheat):
        hot = int((overheat >= 70).sum())
        print(f"  RSI 70 이상(과매수): {hot}종목 / {len(overheat)}종목")

    return merged
