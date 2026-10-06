"""
===========================================================
  진단 — KRX 업종 분류를 받을 수 있는가
===========================================================

왜 진단이 필요한가
  미분류 종목에 "이 회사가 공식적으로 무슨 업종인가" 를 붙이면 섹터 배정이
  훨씬 쉬워진다. 뉴스 힌트는 기사가 있어야 나오지만 업종은 언제나 있다.

  그런데 로컬에는 KRX 로그인이 없어 검증을 못 했다. pykrx 는 import 할 때
  KRX_ID / KRX_PW 로 직접 로그인한다 — 즉 **런너에서만** 확인할 수 있다.

  검증 없이 파이프라인에 넣지 않는다. 먼저 여기서 모양을 확인한다.

쓰는 법 (워크플로에서)
  python app/probe_industry.py
===========================================================
"""

import sys
from datetime import datetime, timedelta

# 미분류로 남은 종목 — 실제로 업종이 나오는지 볼 대상
TARGETS = {
    "브이엠": None, "서울전자통신": None, "케이아이이": None,
    "아이스크림에듀": None, "아티스트컴퍼니": None, "하이딥": None,
    "이미지스": None, "CS": None, "소프트센우": None,
}


def recent_business_day() -> str:
    """최근 영업일 추정 — 주말이면 금요일로 당긴다."""
    d = datetime.today()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.strftime("%Y%m%d")


def head(title: str) -> None:
    print("\n" + "=" * 62)
    print(f"  {title}")
    print("=" * 62)


def probe_sector_classifications(date: str) -> None:
    """후보 1 — get_market_sector_classifications(date, market)"""
    head("후보 1  get_market_sector_classifications")
    from pykrx import stock

    for market in ("KOSPI", "KOSDAQ"):
        try:
            df = stock.get_market_sector_classifications(date, market)
        except Exception as exc:
            print(f"  {market}  실패  {type(exc).__name__}: {exc}")
            continue
        if df is None or df.empty:
            print(f"  {market}  빈 결과")
            continue
        print(f"  {market}  {df.shape}  열={list(df.columns)}")
        print(f"  인덱스 이름={df.index.name}")
        print(df.head(3).to_string())
        # 대상 종목이 들어 있나
        if "종목명" in df.columns:
            hit = df[df["종목명"].isin(TARGETS)]
            if not hit.empty:
                print(f"\n  >>> 대상 {len(hit)}종목 발견:")
                print(hit.to_string())


def probe_index_portfolio(date: str) -> None:
    """후보 2 — 업종 지수의 구성종목으로 역산한다.

    KRX 는 '코스피 전기전자', '코스닥 제약' 같은 업종 지수를 낸다.
    각 지수의 구성종목을 받아 뒤집으면 티커 → 업종이 된다.
    """
    head("후보 2  업종 지수 구성종목 역산")
    from pykrx import stock

    for market in ("KOSPI", "KOSDAQ"):
        try:
            codes = stock.get_index_ticker_list(date, market)
        except Exception as exc:
            print(f"  {market}  지수 목록 실패  {type(exc).__name__}: {exc}")
            continue
        print(f"  {market}  지수 {len(codes)}개")
        shown = 0
        for code in codes:
            try:
                name = stock.get_index_ticker_name(code)
            except Exception:
                name = "?"
            print(f"     {code}  {name}")
            shown += 1
            if shown >= 12:
                print(f"     ... (총 {len(codes)}개)")
                break
        # 첫 업종 지수의 구성종목 모양만 본다
        if codes:
            try:
                pf = stock.get_index_portfolio_deposit_file(codes[min(1, len(codes) - 1)], date)
                print(f"     구성종목 예: {len(pf)}개  앞 5 = {list(pf)[:5]}")
            except Exception as exc:
                print(f"     구성종목 실패  {type(exc).__name__}: {exc}")


def probe_ticker_lookup(date: str) -> None:
    """후보 3 — 티커별 조회 함수가 업종을 주는지"""
    head("후보 3  티커 단위 조회")
    from pykrx import stock

    # 대상 종목의 티커를 찾는다
    tickers = {}
    for market in ("KOSPI", "KOSDAQ"):
        try:
            for t in stock.get_market_ticker_list(date, market):
                nm = stock.get_market_ticker_name(t)
                if nm in TARGETS:
                    tickers[nm] = (t, market)
        except Exception as exc:
            print(f"  {market}  티커 목록 실패  {type(exc).__name__}: {exc}")
    print(f"  대상 티커 {len(tickers)}개: {tickers}")

    if not tickers:
        return
    name, (ticker, market) = next(iter(tickers.items()))
    for fn in ("get_market_fundamental_by_ticker", "get_market_cap_by_ticker"):
        try:
            df = getattr(stock, fn)(date, market)
            print(f"  {fn}  열={list(df.columns)}")
        except Exception as exc:
            print(f"  {fn}  실패  {type(exc).__name__}: {exc}")


def main() -> int:
    date = sys.argv[1] if len(sys.argv) > 1 else recent_business_day()
    print(f"기준일 {date}")

    import os
    print(f"KRX_ID 설정됨: {bool(os.environ.get('KRX_ID'))}")

    for fn in (probe_sector_classifications, probe_index_portfolio, probe_ticker_lookup):
        try:
            fn(date)
        except Exception as exc:
            print(f"\n  [{fn.__name__}] 예외  {type(exc).__name__}: {exc}")

    print("\n진단 끝 — 쓸 수 있는 후보를 골라 파이프라인에 붙인다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
