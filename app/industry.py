"""
===========================================================
  KRX 공식 업종 — 미분류 종목 판단의 1차 근거
===========================================================

왜 필요한가
  미분류 종목에 섹터를 수기로 찍으려면 "이 회사가 뭐 하는 곳인가" 를 알아야
  한다. 뉴스 힌트는 기사가 있어야 나오고, 소형주는 기사가 없는 날이 많다.
  **업종은 언제나 있다.** 그래서 1차 근거로 쓴다.

[ 실측 — 런너에서 확인했다 (로컬은 KRX 로그인이 없어 검증 불가였다) ]
  get_market_sector_classifications(date, market)
    → 인덱스 종목코드 / 열 [종목명, 업종명, 종가, 대비, 등락률, 시가총액]
    → KOSPI 942행 · KOSDAQ 1,824행
    → 당시 미분류 9종목 **전부** 업종이 나왔다

  이 함수는 KRX 로그인이 필요하다. 로그인 없이는 'Expecting value' 로 죽는다.
  pykrx 가 import 시점에 KRX_ID / KRX_PW 로 직접 로그인한다.

[ 쓰는 범위 — 표시용이다 ]
  KRX 업종은 거칠다. '전기·전자' 하나에 반도체·전력기기·부품이 다 들어간다.
  우리 대섹터(AI인프라 · ESS배터리 …)로 **자동 변환하지 않는다.**
  사람이 읽고 판단하는 근거로만 쓴다 — 섹터를 지어내지 않는다.
===========================================================
"""

MARKETS = ("KOSPI", "KOSDAQ")

_cache: dict[str, dict[str, dict]] = {}


def read(date: str) -> dict[str, dict]:
    """티커 → {업종, 시장}. 실패한 시장은 건너뛴다.

    시장마다 한 번씩, 두 번만 호출한다. 종목 수가 많아도 추가 비용이 없다.
    """
    if date in _cache:
        return _cache[date]

    from pykrx import stock

    out: dict[str, dict] = {}
    for market in MARKETS:
        try:
            df = stock.get_market_sector_classifications(date, market)
        except Exception as exc:
            print(f"  업종 조회 실패 {market}: {type(exc).__name__}")
            continue
        if df is None or df.empty or "업종명" not in df.columns:
            continue
        for ticker, row in df.iterrows():
            업종 = str(row.get("업종명") or "").strip()
            if 업종:
                out[str(ticker).zfill(6)] = {"업종": 업종, "시장": market}

    _cache[date] = out
    return out


def attach(rows: list[dict], date: str) -> dict:
    """종목마다 '업종' 을 붙인다. 붙인 수를 돌려준다."""
    table = read(date)
    if not table:
        return {"업종": 0, "전체": len(rows), "사유": "업종 조회 실패"}

    붙임 = 0
    for r in rows:
        t = r.get("티커")
        if not t:
            continue
        got = table.get(str(t).zfill(6))
        if got:
            r["업종"] = got["업종"]
            붙임 += 1

    return {"업종": 붙임, "전체": len(rows), "업종수": len({r.get("업종") for r in rows if r.get("업종")})}


def summary(rows: list[dict]) -> list[dict]:
    """업종별 거래대금 — 어느 업종에 돈이 몰렸나.

    우리 섹터 분류와는 별개다. KRX 기준으로 교차 확인하는 용도다.
    """
    agg: dict[str, dict] = {}
    for r in rows:
        업종 = r.get("업종")
        if not 업종:
            continue
        e = agg.setdefault(업종, {"업종": 업종, "종목수": 0, "거래대금": 0, "종목": []})
        e["종목수"] += 1
        e["거래대금"] += int(r.get("거래대금(억)") or 0)
        if len(e["종목"]) < 5:
            e["종목"].append(r.get("종목명"))
    return sorted(agg.values(), key=lambda x: -x["거래대금"])
