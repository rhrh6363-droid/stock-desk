"""
===========================================================
  일일 특징주 자동 집계 + ADR 산출  (v4)
===========================================================

[ 변경점 — v3 대비 ]
  1. KRX 계정을 코드에서 분리했다. 환경변수로만 읽는다.
  2. ADR(등락비율)을 함께 계산해 'ADR 추이' 시트에 누적한다.
     전종목 등락률이 이미 손에 있으므로 추가 조회 없이 나온다.
  3. 로그인 실패 원인을 구분해서 알려준다. (KRX 는 주기적으로 비밀번호 변경을 강제한다)

[ 필터 조건 ]
  A조건: 당일 등락률 15% 이상
  B조건: 거래대금 500억 이상 + 일중변동폭 6% 이상
  -> 합집합(union). A+B 중복은 별도 색상.

[ 준비 ]
  pip install pykrx pandas openpyxl --upgrade

  계정을 환경변수로 설정한다. 코드에 적지 않는다.
    Windows (영구)  :  setx KRX_ID "아이디"
                       setx KRX_PW "비밀번호"
    Windows (현재창):  $env:KRX_ID="아이디"; $env:KRX_PW="비밀번호"
    Mac/Linux       :  export KRX_ID=아이디
                       export KRX_PW=비밀번호

[ 실행 ]
  python 특징주_자동집계.py                      # 오늘
  python 특징주_자동집계.py 20261002             # 특정일
  python 특징주_자동집계.py 20260901 20261002    # 기간
===========================================================
"""

import json
import os
import sys
import warnings
from datetime import datetime, timedelta

import pandas as pd
import requests
from pykrx import stock

warnings.filterwarnings("ignore")

# pykrx 는 요청에 타임아웃을 걸지 않는다. 한 종목이 응답하지 않으면 전체가 영구히 멈춘다.
# (실제로 겪었다 — CPU 4초에 10분 이상 네트워크 대기.) 모든 요청에 상한을 둔다.
_ORIG_REQUEST = requests.Session.request


def _request_with_timeout(self, *args, **kwargs):
    kwargs.setdefault("timeout", 15)
    return _ORIG_REQUEST(self, *args, **kwargs)


requests.Session.request = _request_with_timeout

# 같은 폴더의 risk_metrics.py 를 어떤 실행 방식에서도 찾게 한다
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# ────────────────────────────────────────────────
# 조건 설정
# ────────────────────────────────────────────────
COND_A_MIN_CHANGE = 15.0              # A: 등락률 %
COND_A_MIN_INTRADAY = 6.0             # A: 일중변동폭 % — 사용자 지시로 A에도 적용
MIN_MARKETCAP = 500_000_000_000       # 투자원칙 "시총 5천억 이상만 본다" — 표기용, 거르지 않는다
OVERHEAT_2D = 40.0                    # 투자원칙 7: 이틀 누적 40%+ 과열
OVERHEAT_EXEMPT_VALUE = 10_000        # 거래대금(억) 1조 이상이면 과열이어도 예외
COND_B_MIN_VALUE = 50_000_000_000     # B: 거래대금 (원)
COND_B_MIN_INTRADAY = 6.0             # B: 일중변동폭 %
COND_B_MIN_CHANGE = 5.0               # B: 등락률 % — 시트 기준에 맞춤
MIN_CLOSE = 500                       # 동전주 제거

OUTPUT_FILE = "특징주집계_누적.xlsx"
ADR_SHEET = "ADR 추이"

# 구글시트 전송용 중간 산출물 — sheets_push.py 가 이걸 읽는다
LATEST_CSV = "raw_최근.csv"
LATEST_META = "raw_최근.json"


# ────────────────────────────────────────────────
# 계정 확인 — 전종목 조회는 KRX 로그인이 있어야 동작한다
# ────────────────────────────────────────────────
def check_credentials() -> None:
    if os.environ.get("KRX_ID") and os.environ.get("KRX_PW"):
        return
    print(
        "\n[중단] KRX 계정이 설정되지 않았습니다.\n"
        "       전종목 조회는 로그인 없이는 동작하지 않습니다.\n\n"
        "  Windows :  setx KRX_ID \"아이디\"  /  setx KRX_PW \"비밀번호\"  (새 창에서 실행)\n"
        "  Mac/Linux: export KRX_ID=아이디  /  export KRX_PW=비밀번호\n\n"
        "  * 비밀번호를 코드에 적지 마세요.\n"
    )
    sys.exit(1)


def explain_failure(err: str) -> str:
    """조회 실패의 진짜 원인을 짚어준다."""
    if "Expecting value" in err or "KRX 로그인" in err or "자격 증명" in err:
        return (
            "KRX 로그인이 풀렸거나 거부됐습니다.\n"
            "     가장 흔한 원인은 'KRX 비밀번호 변경 요구'입니다.\n"
            "     https://www.krx.co.kr 에 직접 로그인해 변경 요구가 있는지 확인하세요.\n"
            "     변경 후 환경변수 KRX_PW 도 함께 갱신해야 합니다."
        )
    return err


# ────────────────────────────────────────────────
# 날짜 파싱
# ────────────────────────────────────────────────
def get_target_dates() -> list[str]:
    args = sys.argv[1:]
    if not args:
        return [datetime.today().strftime("%Y%m%d")]
    if len(args) == 1:
        return [args[0]]
    if len(args) == 2:
        start = datetime.strptime(args[0], "%Y%m%d")
        end = datetime.strptime(args[1], "%Y%m%d")
        dates, cur = [], start
        while cur <= end:
            if cur.weekday() < 5:
                dates.append(cur.strftime("%Y%m%d"))
            cur += timedelta(days=1)
        return dates
    print("인자 오류.  사용법: python 특징주_자동집계.py [YYYYMMDD] [YYYYMMDD]")
    sys.exit(1)


# ────────────────────────────────────────────────
# ADR — 시장 위험 척도
# ────────────────────────────────────────────────
def calc_adr(df_base: pd.DataFrame) -> dict:
    """등락비율. 전종목 등락률에서 바로 집계된다.

    ADR = 상승 종목수 / 하락 종목수 * 100
    통상 120 이상 과열, 80 이하 침체로 본다.
    """
    up = int((df_base["등락률(%)"] > 0).sum())
    down = int((df_base["등락률(%)"] < 0).sum())
    flat = int((df_base["등락률(%)"] == 0).sum())
    adr = round(up / down * 100, 2) if down else None

    if adr is None:
        zone = "산출불가"
    elif adr >= 120:
        zone = "과열"
    elif adr >= 80:
        zone = "중립"
    else:
        zone = "침체"

    return {"상승": up, "하락": down, "보합": flat, "ADR": adr, "구간": zone}


# ────────────────────────────────────────────────
# 데이터 수집 + 필터링
# ────────────────────────────────────────────────
def fetch_date(target_date: str):
    print(f"\n{'='*62}")
    print(f"  {target_date[:4]}.{target_date[4:6]}.{target_date[6:]} 수집 중...")
    print(f"{'='*62}")

    try:
        df_kospi = stock.get_market_ohlcv_by_ticker(target_date, market="KOSPI")
        df_kosdaq = stock.get_market_ohlcv_by_ticker(target_date, market="KOSDAQ")

        if df_kospi.empty and df_kosdaq.empty:
            print(f"  [{target_date}] 데이터 없음 (휴장일 또는 미반영)")
            return None, None

        df_kospi["시장"] = "코스피"
        df_kosdaq["시장"] = "코스닥"
        df_all = pd.concat([df_kospi, df_kosdaq])
        df_all.index.name = "티커"
        df_all = df_all.reset_index()

    except Exception as exc:
        print(f"  [{target_date}] 수집 실패: {explain_failure(str(exc))}")
        return None, None

    def find_col(df, candidates):
        return next((c for c in candidates if c in df.columns), None)

    change_col = find_col(df_all, ["등락률", "변동률", "전일비율"])
    close_col = find_col(df_all, ["종가", "close"])
    value_col = find_col(df_all, ["거래대금", "거래금액", "value"])
    high_col = find_col(df_all, ["고가", "high"])
    low_col = find_col(df_all, ["저가", "low"])
    open_col = find_col(df_all, ["시가", "open"])

    missing = [
        n for n, c in [("등락률", change_col), ("종가", close_col),
                       ("거래대금", value_col), ("고가", high_col), ("저가", low_col)]
        if c is None
    ]
    if missing:
        print(f"  필수 컬럼 없음: {missing}")
        return None, None

    # 파생 컬럼
    df_all["거래대금(억)"] = (df_all[value_col] / 1e8).round(0).astype(int)
    df_all["등락률(%)"] = df_all[change_col].round(2)
    df_all["일중변동폭(%)"] = ((df_all[high_col] - df_all[low_col]) / df_all[low_col] * 100).round(2)
    df_all["날짜"] = target_date

    df_base = df_all[df_all[close_col] >= MIN_CLOSE].copy()

    # ── ADR: 특징주가 아니라 전체 시장 기준으로 계산한다
    adr = calc_adr(df_base)
    adr["날짜"] = target_date
    adr["대상종목수"] = len(df_base)
    print(f"  [참고] 시장 ADR {adr['ADR']}  [{adr['구간']}]   "
          f"상승 {adr['상승']} / 하락 {adr['하락']} / 보합 {adr['보합']}")

    # ── A / B 조건
    # 갭상승만 하고 장중에 안 움직인 종목은 매매 대상이 아니다 → A도 변동폭으로 거른다
    mask_a = (
        (df_base["등락률(%)"] >= COND_A_MIN_CHANGE)
        & (df_base["일중변동폭(%)"] >= COND_A_MIN_INTRADAY)
    )
    mask_b = (
        (df_base["거래대금(억)"] >= COND_B_MIN_VALUE / 1e8)
        & (df_base["일중변동폭(%)"] >= COND_B_MIN_INTRADAY)
        & (df_base["등락률(%)"] >= COND_B_MIN_CHANGE)
    )
    df_union = df_base[mask_a | mask_b].copy()

    if df_union.empty:
        print("  조건에 맞는 특징주 없음")
        return None, adr

    # 종목명은 걸러낸 종목만 조회한다 (전종목 조회는 너무 느리다)
    print(f"  종목명 조회 ({len(df_union)}종목)...", flush=True)
    names = {}
    for ticker in df_union["티커"]:
        try:
            names[ticker] = stock.get_market_ticker_name(ticker)
        except Exception:
            names[ticker] = ticker
    df_union["종목명"] = df_union["티커"].map(names)

    def tag(row):
        a = (row["등락률(%)"] >= COND_A_MIN_CHANGE
             and row["일중변동폭(%)"] >= COND_A_MIN_INTRADAY)
        b = (row["거래대금(억)"] >= COND_B_MIN_VALUE / 1e8
             and row["일중변동폭(%)"] >= COND_B_MIN_INTRADAY
             and row["등락률(%)"] >= COND_B_MIN_CHANGE)
        return "A+B" if (a and b) else ("A" if a else "B")

    df_union["조건"] = df_union.apply(tag, axis=1)
    df_union["_sort"] = df_union["조건"].map({"A+B": 0, "A": 1, "B": 2})
    df_union = df_union.sort_values(["_sort", "등락률(%)"], ascending=[True, False]).drop(columns="_sort")
    df_union = df_union.reset_index(drop=True)
    df_union.index += 1

    out_cols = ["날짜", "시장", "종목명", "티커", close_col, "등락률(%)",
                "거래대금(억)", "일중변동폭(%)", "조건"]
    rename_map = {close_col: "종가"}
    for col, label in ((open_col, "시가"), (high_col, "고가"), (low_col, "저가")):
        if col:
            out_cols.append(col)
            rename_map[col] = label

    df_out = df_union[out_cols].rename(columns=rename_map)

    # 시가총액 — 투자원칙의 5천억 기준을 화면에서 쓰기 위해 받아둔다 (전종목 1회 호출)
    try:
        cap = stock.get_market_cap_by_ticker(target_date)
        cap_col = next((c for c in cap.columns if "시가총액" in c), None)
        if cap_col:
            억 = (cap[cap_col] / 1e8).round(0)
            df_out["시총(억)"] = df_out["티커"].map(억).astype("Float64")
            df_out["시총기준"] = df_out["시총(억)"].map(
                lambda v: None if pd.isna(v) else ("충족" if v * 1e8 >= MIN_MARKETCAP else "미달"))
    except Exception as exc:
        print(f"  시가총액 조회 생략: {type(exc).__name__}: {exc}")

    # 종목별 위험지표 — ADR 로는 종목 단위 위험을 못 재므로 여기서 붙인다
    try:
        from risk_metrics import add_risk_metrics
        df_out = add_risk_metrics(df_out, target_date)
    except Exception as exc:
        print(f"  위험지표 계산 생략: {type(exc).__name__}: {exc}")

    # 과열 판정 — 투자원칙 7. 조단위 거래대금은 예외로 둔다
    if "2일누적(%)" in df_out.columns:
        def overheat(row):
            cum = row.get("2일누적(%)")
            if pd.isna(cum) or cum < OVERHEAT_2D:
                return None
            if (row.get("거래대금(억)") or 0) >= OVERHEAT_EXEMPT_VALUE:
                return "과열(조단위 예외)"
            return "과열"
        df_out["과열"] = df_out.apply(overheat, axis=1)

    # 콘솔 출력
    counts = df_out["조건"].value_counts()
    print(f"\n  총 {len(df_out)}종목  |  A+B: {counts.get('A+B', 0)}  "
          f"A: {counts.get('A', 0)}  B: {counts.get('B', 0)}\n")

    header = (f"  {'#':>3} {'조건':^5} {'종목명':^12} {'종가':>9} {'등락률':>7} "
              f"{'거래대금':>9} {'RSI':>6} {'볼밴':^8} {'평균폭':>7} {'손절':>7}")
    print(header)
    print("  " + "─" * (len(header) - 2))
    labels = {"A+B": "[A+B]", "A": "[ A ]", "B": "[ B ]"}

    def num(val, fmt=">6.1f"):
        return format(val, fmt) if pd.notna(val) else format("—", ">6")

    for idx, row in df_out.iterrows():
        rsi = row.get("RSI(14)")
        band = row.get("볼밴위치") or "—"
        avg = row.get("평균변동폭(20일)")
        stop = row.get("제안손절(%)")
        flag = "!" if pd.notna(rsi) and rsi >= 70 else " "
        print(f"  {idx:>3} {labels[row['조건']]:^5} {row['종목명']:^12} "
              f"{row['종가']:>9,} {row['등락률(%)']:>6.2f}% "
              f"{row['거래대금(억)']:>9,} {num(rsi)}{flag} {band:^8} "
              f"{num(avg)}% {num(stop)}%")

    print("\n  RSI 뒤의 ! = 70 이상 과매수.  손절은 평균변동폭×1.5 <제안>, 익절은 그 3배.")

    return df_out, adr


# ────────────────────────────────────────────────
# 엑셀 저장
# ────────────────────────────────────────────────
def save_to_excel(df: pd.DataFrame, target_date: str, adr: dict | None):
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    sheet_name = f"{target_date[:4]}.{target_date[4:6]}.{target_date[6:]}"

    if os.path.exists(OUTPUT_FILE):
        wb = load_workbook(OUTPUT_FILE)
        if sheet_name in wb.sheetnames:
            del wb[sheet_name]
    else:
        wb = Workbook()
        if "Sheet" in wb.sheetnames:
            del wb["Sheet"]

    ws = wb.create_sheet(title=sheet_name)
    ws.sheet_properties.tabColor = (
        "C00000" if len(df) >= 10 else "FF6600" if len(df) >= 5 else "FFC000"
    )
    col_count = len(df.columns) + 1

    # 제목
    ws.merge_cells(f"A1:{get_column_letter(col_count)}1")
    title = ws["A1"]
    title.value = (
        f"특징주 집계 | {sheet_name}  |  "
        f"[A] 등락률 {COND_A_MIN_CHANGE}%+ & 일중변동폭 {COND_A_MIN_INTRADAY}%+   "
        f"[B] 거래대금 {int(COND_B_MIN_VALUE/1e8)}억+ & 일중변동폭 {COND_B_MIN_INTRADAY}%+ "
        f"& 등락률 {COND_B_MIN_CHANGE}%+   [A+B] 중복"
    )
    title.font = Font(name="맑은 고딕", size=12, bold=True, color="1F3864")
    title.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 32

    # 부제 — ADR 포함
    ws.merge_cells(f"A2:{get_column_letter(col_count)}2")
    sub = ws["A2"]
    adr_text = (f"[참고] 시장 ADR {adr['ADR']} [{adr['구간']}]  "
                f"상승 {adr['상승']}/하락 {adr['하락']}  |  ") if adr else ""
    sub.value = f"{adr_text}수집 {datetime.now():%Y-%m-%d %H:%M}  |  출처: KRX"
    sub.font = Font(name="맑은 고딕", size=9, italic=True, color="595959")
    sub.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[2].height = 16

    # 헤더
    headers = ["#"] + list(df.columns)
    widths = {"#": 5, "날짜": 12, "시장": 8, "종목명": 14, "티커": 10, "종가": 12,
              "등락률(%)": 10, "거래대금(억)": 14, "일중변동폭(%)": 13, "조건": 7,
              "시가": 11, "고가": 11, "저가": 11,
              "RSI(14)": 9, "볼밴위치": 11, "볼밴%B": 10, "이격도": 9,
              "평균변동폭(20일)": 16, "제안손절(%)": 12, "제안익절(%)": 12}
    thin = Side(style="thin", color="AAAAAA")
    for ci, head in enumerate(headers, 1):
        cell = ws.cell(row=3, column=ci, value=head)
        cell.font = Font(name="맑은 고딕", size=10, bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", start_color="1F3864", end_color="1F3864")
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = Border(left=thin, right=thin, top=thin, bottom=thin)
        ws.column_dimensions[get_column_letter(ci)].width = widths.get(head, 11)
    ws.row_dimensions[3].height = 22

    PALETTE = {
        "A+B": ("FFD0D0", "FFEEEE", "CC0000", "FFFFFF", "CC0000"),
        "A":   ("FFE5CC", "FFF5EE", "E65C00", "FFFFFF", "CC4400"),
        "B":   ("C8F0DC", "EAFAF1", "006D3B", "FFFFFF", "005A30"),
    }
    soft = Side(style="thin", color="DDDDDD")
    border = Border(left=soft, right=soft, top=soft, bottom=soft)

    change_ci = headers.index("등락률(%)") + 1
    intra_ci = headers.index("일중변동폭(%)") + 1
    cond_ci = headers.index("조건") + 1
    rsi_ci = headers.index("RSI(14)") + 1 if "RSI(14)" in headers else None

    for i, (idx, row) in enumerate(df.iterrows(), 4):
        bg_even, bg_odd, rate_bg, rate_fg, cond_fg = PALETTE[row["조건"]]
        bg = bg_even if i % 2 == 0 else bg_odd

        for ci, val in enumerate([idx] + list(row), 1):
            if val is not None and not isinstance(val, str) and pd.isna(val):
                val = None                      # NaN 은 엑셀에 쓸 수 없다
            cell = ws.cell(row=i, column=ci, value=val)
            cell.border = border
            cell.alignment = Alignment(horizontal="center", vertical="center")
            if ci == rsi_ci and isinstance(val, (int, float)) and val >= 70:
                # RSI 과매수 — 위험 가산 구간이라 눈에 띄게 둔다
                cell.font = Font(name="맑은 고딕", size=10, bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", start_color="C00000", end_color="C00000")
            elif ci == change_ci:
                cell.font = Font(name="맑은 고딕", size=10, bold=True, color=rate_fg)
                cell.fill = PatternFill("solid", start_color=rate_bg, end_color=rate_bg)
            elif ci == cond_ci:
                cell.font = Font(name="맑은 고딕", size=10, bold=True, color=cond_fg)
                cell.fill = PatternFill("solid", start_color=bg, end_color=bg)
            else:
                is_bold = ci == intra_ci and isinstance(val, (int, float)) and val >= COND_B_MIN_INTRADAY
                cell.font = Font(name="맑은 고딕", size=10, bold=is_bold)
                cell.fill = PatternFill("solid", start_color=bg, end_color=bg)
        ws.row_dimensions[i].height = 20

    # 요약
    counts = df["조건"].value_counts()
    stat_row = len(df) + 5
    ws.merge_cells(f"A{stat_row}:{get_column_letter(col_count)}{stat_row}")
    stat = ws[f"A{stat_row}"]
    stat.value = (
        f"총 {len(df)}종목  |  A+B: {counts.get('A+B', 0)}  A: {counts.get('A', 0)}  B: {counts.get('B', 0)}  |  "
        f"코스피 {len(df[df['시장']=='코스피'])} / 코스닥 {len(df[df['시장']=='코스닥'])}  |  "
        f"평균등락률 {df['등락률(%)'].mean():.2f}%  평균거래대금 {int(df['거래대금(억)'].mean()):,}억"
    )
    stat.font = Font(name="맑은 고딕", size=10, bold=True, color="1F3864")
    stat.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    ws.row_dimensions[stat_row].height = 24

    _write_adr_sheet(wb, adr)
    _reorder_sheets(wb)
    _save(wb, sheet_name)


def _write_adr_sheet(wb, adr: dict | None):
    """ADR 을 날짜별로 누적한다. 20일 ADR 은 이 시트에서 계산하면 된다."""
    from openpyxl.styles import Alignment, Font, PatternFill

    if not adr:
        return

    if ADR_SHEET in wb.sheetnames:
        ws = wb[ADR_SHEET]
    else:
        ws = wb.create_sheet(title=ADR_SHEET, index=0)
        ws.sheet_properties.tabColor = "1F3864"
        for ci, head in enumerate(["날짜", "ADR", "구간", "상승", "하락", "보합", "대상종목수"], 1):
            cell = ws.cell(row=1, column=ci, value=head)
            cell.font = Font(name="맑은 고딕", size=10, bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", start_color="1F3864", end_color="1F3864")
            cell.alignment = Alignment(horizontal="center")
            ws.column_dimensions[chr(64 + ci)].width = 13

    # 같은 날짜가 있으면 갱신, 없으면 추가
    target = None
    for r in range(2, ws.max_row + 1):
        if str(ws.cell(row=r, column=1).value) == adr["날짜"]:
            target = r
            break
    if target is None:
        target = ws.max_row + 1

    zone_color = {"과열": "E8232A", "중립": "2D9E4A", "침체": "2560C0"}.get(adr["구간"], "888888")
    values = [adr["날짜"], adr["ADR"], adr["구간"], adr["상승"], adr["하락"], adr["보합"], adr["대상종목수"]]
    for ci, val in enumerate(values, 1):
        cell = ws.cell(row=target, column=ci, value=val)
        cell.alignment = Alignment(horizontal="center")
        if ci in (2, 3):
            cell.font = Font(name="맑은 고딕", size=10, bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", start_color=zone_color, end_color=zone_color)
        else:
            cell.font = Font(name="맑은 고딕", size=10)


def save_adr_only(adr: dict):
    """특징주가 0개인 날에도 ADR 은 남긴다. 추이가 끊기면 20일 ADR 을 못 쓴다."""
    from openpyxl import Workbook, load_workbook

    if os.path.exists(OUTPUT_FILE):
        wb = load_workbook(OUTPUT_FILE)
    else:
        wb = Workbook()
        if "Sheet" in wb.sheetnames:
            del wb["Sheet"]
    _write_adr_sheet(wb, adr)
    _reorder_sheets(wb)
    _save(wb, ADR_SHEET)


def save_latest(df: pd.DataFrame | None, target_date: str, adr: dict | None):
    """구글시트로 보낼 '가장 최근 1거래일' 산출물.

    엑셀은 서식이 들어가 다시 읽기 번거롭다. 전송용으로는 평범한 CSV 를 따로 남긴다.
    """
    cols = ["날짜", "시장", "종목명", "티커", "종가", "등락률(%)",
            "거래대금(억)", "일중변동폭(%)", "조건",
            "RSI(14)", "볼밴위치", "볼밴%B", "이격도",
            "평균변동폭(20일)", "제안손절(%)", "제안익절(%)"]
    frame = df if df is not None else pd.DataFrame(columns=cols)
    frame.to_csv(LATEST_CSV, index=False, encoding="utf-8-sig")

    meta = {
        "날짜": target_date,
        "종목수": int(len(frame)),
        "수집시각": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if adr:
        meta.update({k: v for k, v in adr.items() if k != "날짜"})
    with open(LATEST_META, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)


def _reorder_sheets(wb):
    """ADR 추이를 맨 앞에, 날짜 시트는 최신순."""
    date_sheets = sorted([s for s in wb.sheetnames if s != ADR_SHEET], reverse=True)
    order = ([ADR_SHEET] if ADR_SHEET in wb.sheetnames else []) + date_sheets
    for position, name in enumerate(order):
        wb.move_sheet(name, offset=-wb.sheetnames.index(name) + position)


def _save(wb, sheet_name: str):
    path, attempt = OUTPUT_FILE, 0
    while True:
        try:
            wb.save(path)
            print(f"\n  저장 완료: {os.path.abspath(path)}  (시트: {sheet_name})")
            return
        except PermissionError:
            attempt += 1
            base, ext = os.path.splitext(OUTPUT_FILE)
            path = f"{base}_{attempt}{ext}"
            print(f"  파일이 열려 있음 → {path} 으로 재시도...")


# ────────────────────────────────────────────────
def main():
    check_credentials()
    dates = get_target_dates()

    print(f"\n{'='*62}")
    print(f"  처리 대상: {len(dates)}일  ({dates[0]} ~ {dates[-1]})")
    print(f"  [A] 등락률 {COND_A_MIN_CHANGE}%+ & 일중변동폭 {COND_A_MIN_INTRADAY}%+")
    print(f"  [B] 거래대금 {int(COND_B_MIN_VALUE/1e8)}억+ & 일중변동폭 {COND_B_MIN_INTRADAY}%+ "
          f"& 등락률 {COND_B_MIN_CHANGE}%+")
    print(f"{'='*62}")

    success, latest = 0, None
    for date in dates:
        df, adr = fetch_date(date)
        if adr is None:                      # 휴장일 또는 수집 실패
            continue
        if df is not None:
            save_to_excel(df, date, adr)
        else:
            save_adr_only(adr)               # 특징주 0개여도 ADR 은 기록
        latest = (df, date, adr)
        success += 1

    if latest:
        save_latest(*latest)

    print(f"\n{'='*62}")
    print(f"  완료: {success}/{len(dates)}일")
    print(f"  파일: {os.path.abspath(OUTPUT_FILE)}")
    if latest:
        print(f"  전송용: {os.path.abspath(LATEST_CSV)}")
    print(f"{'='*62}\n")

    if success == 0:
        sys.exit(2)                          # 스케줄러 로그에서 구분되도록


if __name__ == "__main__":
    main()
