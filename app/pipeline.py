"""
===========================================================
  일별 / 장중 파이프라인
===========================================================

  수집(특징주_자동집계) → 섹터 매핑 → 주도업종 판정 → 뉴스 근거 → JSON

산출물: app/data/YYYYMMDD.json  +  app/data/latest.json
서버(server.py)가 이 JSON 을 읽어 화면에 뿌린다.

단독 실행도 된다:
  python app/pipeline.py              # 오늘
  python app/pipeline.py 20261002     # 특정일
===========================================================
"""

import importlib
import json
import os
import sys
from datetime import datetime, timedelta

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (HERE, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

import flows                     # noqa: E402
import news                      # noqa: E402
import sector_map                # noqa: E402

DATA_DIR = os.path.join(HERE, "data")
ASSIGN_FILE = os.path.join(HERE, "키워드배정.csv")      # 키워드 → 섹터 (보조)
STOCK_ASSIGN_FILE = os.path.join(HERE, "종목배정.csv")   # 종목명 → 대섹터 (시트 🔧 종목 배정)

지수코드 = {"코스피": "1001", "코스닥": "2001"}

# 장 시작 전(00시 배치)이나 휴장일에는 그 날짜에 자료가 없다.
# 빈 결과로 latest.json 을 덮으면 화면이 비어버린다. 자료가 있는 날까지 거슬러 찾는다.
MAX_LOOKBACK = 7


def _clean(obj):
    """NaN 을 None 으로. JSON 에 NaN 이 들어가면 브라우저가 파싱하지 못한다."""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    if isinstance(obj, float) and pd.isna(obj):
        return None
    if hasattr(obj, "item"):
        return obj.item()
    return obj


def _breadth(adr: dict | None) -> int:
    """그 날짜에 자료가 실제로 있었는지. 상승+하락+보합이 0이면 자료가 없는 것이다."""
    if not adr:
        return 0
    return sum(int(adr.get(k) or 0) for k in ("상승", "하락", "보합"))


def fetch_indices(date: str) -> list[dict]:
    """코스피·코스닥 현황. 실패해도 전체를 멈추지 않는다."""
    from pykrx import stock

    out = []
    for name, code in 지수코드.items():
        try:
            df = stock.get_index_ohlcv(date, date, code)
            if df is None or df.empty:
                continue
            row = df.iloc[-1]
            close = float(row["종가"])
            open_ = float(row["시가"])
            out.append({
                "이름": name,
                "종가": round(close, 2),
                "등락pt": round(close - open_, 2),
                "등락률": round((close - open_) / open_ * 100, 2) if open_ else None,
                "거래대금": int(row["거래대금"]) if "거래대금" in row else None,
            })
        except Exception:
            continue
    return out


def load_assignments() -> pd.DataFrame:
    """종목배정 장표 — 키워드를 어느 섹터에 넣을지 수기로 잡아둔 표.

    구글시트가 연결되면 그쪽 '종목배정' 탭이 이 파일을 대신한다.
    """
    cols = ["키워드", "대섹터", "세부섹터", "비고"]
    if not os.path.exists(ASSIGN_FILE):
        return pd.DataFrame(columns=cols)
    try:
        df = pd.read_csv(ASSIGN_FILE, encoding="utf-8-sig", dtype=str).fillna("")
    except Exception as exc:
        print(f"  키워드배정 읽기 실패: {type(exc).__name__}")
        return pd.DataFrame(columns=cols)
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    return df[df["키워드"].str.strip() != ""][cols]


def load_stock_assignments() -> pd.DataFrame:
    """종목배정 장표 — 미분류로 남은 종목에 대섹터를 수기로 찍어둔 표.

    시트의 '🔧 종목 배정' 탭과 같다. 여기 등록된 종목은 1단계(종목명 완전일치)로
    잡히므로 뉴스·키워드와 무관하게 무조건 그 섹터로 간다.
    """
    cols = ["종목명", "대섹터", "세부섹터", "비고"]
    if not os.path.exists(STOCK_ASSIGN_FILE):
        return pd.DataFrame(columns=cols)
    try:
        df = pd.read_csv(STOCK_ASSIGN_FILE, encoding="utf-8-sig", dtype=str).fillna("")
    except Exception as exc:
        print(f"  종목배정 읽기 실패: {type(exc).__name__}")
        return pd.DataFrame(columns=cols)
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    df = df[(df["종목명"].str.strip() != "") & (df["대섹터"].str.strip() != "")]
    return df[cols]


def load_dictionary() -> tuple[pd.DataFrame, str]:
    """섹터 사전. 구글시트가 연결돼 있으면 거기서, 아니면 로컬 CSV."""
    try:
        import sheets
        if sheets.configured():
            dic = sheets.read_sector_dict()
            if dic is not None and not dic.empty:
                return dic, "구글시트"
    except Exception as exc:
        print(f"  구글시트 사전 읽기 실패 → 로컬 사용 ({type(exc).__name__})")
    return sector_map.load_dictionary(), "로컬 CSV"


def merge_assignments(dic: pd.DataFrame, assign: pd.DataFrame,
                      stocks: pd.DataFrame | None = None) -> pd.DataFrame:
    """수기 배정을 사전 행으로 바꿔 붙인다.

    종목배정 → '종목' 열  → 1단계(종목명 완전일치). 무조건 이긴다.
    키워드배정 → '키워드' 열 → 4단계(키워드 대조).
    """
    extra = []
    if stocks is not None and not stocks.empty:
        extra += [{"대섹터": r["대섹터"], "세부섹터": r["세부섹터"],
                   "종목": r["종목명"], "비고": r["비고"]} for _, r in stocks.iterrows()]
    if not assign.empty:
        extra += [{"대섹터": r["대섹터"] or "기타", "세부섹터": r["세부섹터"],
                   "키워드": r["키워드"], "비고": r["비고"]} for _, r in assign.iterrows()]
    if not extra:
        return dic
    return pd.concat([dic, pd.DataFrame(extra)], ignore_index=True)


def run(target_date: str | None = None, push_sheet: bool = True) -> dict:
    date = target_date or datetime.today().strftime("%Y%m%d")

    collector = importlib.import_module("특징주_자동집계")
    collector.check_credentials()

    # 요청한 날짜에 자료가 없으면 최근 거래일까지 거슬러 찾는다.
    # 날짜를 명시해 부른 경우에는 그 날짜만 본다.
    explicit = target_date is not None
    base = datetime.strptime(date, "%Y%m%d")
    tried: list[str] = []
    df = adr = None

    for back in range(1 if explicit else MAX_LOOKBACK + 1):
        d = (base - timedelta(days=back)).strftime("%Y%m%d")
        print(f"\n[1/5] 수집  {d}")
        df, adr = collector.fetch_date(d)
        if _breadth(adr) > 0:
            date = d
            break
        tried.append(d)
        print("  자료 없음 — 장 시작 전이거나 휴장일입니다.")
    else:
        print(f"\n[중단] {len(tried)}일을 거슬러도 자료가 없습니다: {', '.join(tried)}")
        print("  latest.json 을 덮지 않습니다 — 화면에는 지난 거래일 자료가 그대로 남습니다.")
        return {"상태": "데이터없음", "거래일": date, "시도": tried}
    if df is None:
        df = pd.DataFrame(columns=["종목명", "거래대금(억)", "등락률(%)", "조건"])

    # 사전을 먼저 읽는다 — 뉴스에서 키워드를 뽑을 때 사전 어휘를 기준으로 쓴다
    dic, source = load_dictionary()
    assign = load_assignments()
    stock_assign = load_stock_assignments()
    merged = merge_assignments(dic, assign, stock_assign)

    # 키워드가 섹터 매핑의 입력이다. 그래서 뉴스가 매핑보다 **먼저** 돌아야 한다
    print("\n[2/5] 뉴스 근거 + 키워드 추출")
    rows = _clean(df.to_dict("records"))
    news_stat = news.attach(rows, vocab=news.vocabulary(merged))
    print(f"  {news_stat}")

    print("\n[3/5] 섹터 매핑")
    mapped, unmapped = sector_map.apply(pd.DataFrame(rows), merged)
    rows = _clean(mapped.to_dict("records"))
    print(f"  사전: {source} ({len(dic)}행) + 종목배정 {len(stock_assign)}행"
          f" + 키워드배정 {len(assign)}행   미매핑 {len(unmapped)}종목")

    print("\n[4/5] 투자자별 수급 (외국인·기관)")
    flow_stat = flows.attach(rows, date)
    print(f"  {flow_stat}")

    # 매핑까지 끝난 rows 로 집계해야 근거·키워드·수급이 그룹 안으로 따라 들어간다
    enriched = pd.DataFrame(rows) if rows else mapped
    groups = sector_map.aggregate(enriched) if not enriched.empty else []
    leaders = sector_map.leaders(groups)

    print("\n[5/5] 저장")
    payload = {
        "거래일": date,
        "수집시각": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "사전출처": source,
        "adr": _clean(adr),
        "지수": fetch_indices(date),
        "그룹": _clean(groups),
        "대장주후보": _clean(leaders),
        "미매핑": unmapped,
        "뉴스": news_stat,
        "수급": flow_stat,
        "수급요약": flows.summary(rows),
        "사전": _clean(dic.fillna("").to_dict("records")),
        "배정": _clean(assign.to_dict("records")),
        "종목배정": _clean(stock_assign.to_dict("records")),
        "대섹터목록": sorted({str(x) for x in dic["대섹터"].dropna().unique() if str(x).strip()}),
        "미매핑상세": _clean([
            {"종목명": r.get("종목명"), "거래대금(억)": r.get("거래대금(억)"),
             "등락률(%)": r.get("등락률(%)"), "키워드": r.get("키워드"),
             "상승원인": r.get("상승원인")}
            for r in rows if r.get("대섹터") == "미분류"]),
        "종목수": len(rows),
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    for name in (f"{date}.json", "latest.json"):
        with open(os.path.join(DATA_DIR, name), "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
    print(f"  {os.path.join(DATA_DIR, 'latest.json')}")

    for g in groups[:5]:
        print(f"    {g['순위']}. {g['대섹터']:12} {g['등급']:4} "
              f"{g['종목수']}종목 {g['합산거래대금']:>8,}억  대장 {g['대장주']}")

    if push_sheet:
        try:
            import sheets
            if sheets.configured():
                sheets.push_raw(rows, payload)
                print("  구글시트 RAW 전송 완료")
        except Exception as exc:
            print(f"  구글시트 전송 생략: {type(exc).__name__}: {exc}")

    return payload


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else None)
