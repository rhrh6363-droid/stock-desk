"""
===========================================================
  raw_최근.csv  →  구글시트 '📋 RAW 데이터'  자동 전송
===========================================================

특징주_자동집계.py 가 남긴 raw_최근.csv 를 구글시트에 그대로 넣는다.
손으로 복사·붙여넣기 하던 단계를 없애는 부분이다.

[ 준비 — 1회만 ]
  1) pip install gspread google-auth
  2) 구글 클라우드 콘솔에서 서비스 계정 키(JSON) 발급
     (Apps Script 용으로 이미 만든 서비스 계정이 있으면 그걸 써도 된다)
  3) 그 JSON 안의 client_email 주소를 구글시트에 '편집자'로 공유
     ← 이걸 안 하면 권한 오류가 난다. 가장 흔한 실수다.
  4) config.json 의 spreadsheet_id / service_account_json 채우기

[ 쓰는 범위 ]
  B1              거래일 날짜
  B4:D(n)         종목명 / 상승률(%) / 거래대금(억)
  E,F 열          손대지 않는다 — 상승원인·키워드는 사람이 채우는 칸이다
                  단, 전일 잔여 행은 지운다 (날짜가 바뀌었으므로)

[ 실행 ]
  python sheets_push.py
===========================================================
"""

import json
import os
import sys

CONFIG_FILE = "config.json"
LATEST_CSV = "raw_최근.csv"
LATEST_META = "raw_최근.json"

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def load_config() -> dict | None:
    if not os.path.exists(CONFIG_FILE):
        print(f"  [건너뜀] {CONFIG_FILE} 이 없습니다. 구글시트 전송을 하지 않습니다.")
        return None

    with open(CONFIG_FILE, encoding="utf-8") as fh:
        cfg = json.load(fh)

    missing = [k for k in ("spreadsheet_id", "service_account_json") if not cfg.get(k)]
    if missing:
        print(
            f"  [건너뜀] config.json 의 {', '.join(missing)} 가 비어 있습니다.\n"
            "           채우면 다음 실행부터 구글시트로 자동 전송됩니다."
        )
        return None

    if not os.path.exists(cfg["service_account_json"]):
        print(f"  [중단] 서비스 계정 키를 찾을 수 없습니다: {cfg['service_account_json']}")
        sys.exit(1)

    return cfg


def read_rows() -> tuple[list[list], dict]:
    import pandas as pd

    if not os.path.exists(LATEST_CSV):
        print(f"  [중단] {LATEST_CSV} 이 없습니다. 특징주_자동집계.py 를 먼저 실행하세요.")
        sys.exit(1)

    df = pd.read_csv(LATEST_CSV, encoding="utf-8-sig")
    meta = {}
    if os.path.exists(LATEST_META):
        with open(LATEST_META, encoding="utf-8") as fh:
            meta = json.load(fh)

    rows = [
        [str(r["종목명"]), float(r["등락률(%)"]), int(r["거래대금(억)"])]
        for _, r in df.iterrows()
    ] if not df.empty else []

    return rows, meta


def push(cfg: dict, rows: list[list], meta: dict) -> None:
    import gspread
    from google.oauth2.service_account import Credentials

    creds = Credentials.from_service_account_file(cfg["service_account_json"], scopes=SCOPES)
    client = gspread.authorize(creds)

    try:
        book = client.open_by_key(cfg["spreadsheet_id"])
    except Exception as exc:
        print(
            f"  [중단] 시트를 열 수 없습니다: {exc}\n"
            "         서비스 계정 이메일(client_email)을 해당 시트에 '편집자'로 공유했는지 확인하세요."
        )
        sys.exit(1)

    sheet_name = cfg.get("raw_sheet_name", "📋 RAW 데이터")
    try:
        ws = book.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        names = [w.title for w in book.worksheets()]
        print(f"  [중단] '{sheet_name}' 시트가 없습니다. 현재 시트: {names}")
        sys.exit(1)

    first_row = int(cfg.get("first_data_row", 4))

    # 1) 전일 데이터 비우기 — E·F(상승원인·키워드)도 전일 것이므로 함께 지운다
    last_row = max(ws.row_count, first_row)
    ws.batch_clear([f"B{first_row}:F{last_row}"])

    # 2) 날짜
    date_raw = str(meta.get("날짜", ""))
    date_text = (
        f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:8]}" if len(date_raw) == 8 else date_raw
    )
    ws.update_acell(cfg.get("date_cell", "B1"), date_text)

    # 3) 본문
    if rows:
        end = first_row + len(rows) - 1
        # gspread 6.x 는 인자 순서가 (values, range_name) 로 바뀌었다 → 키워드로 넘긴다
        ws.update(
            values=rows,
            range_name=f"B{first_row}:D{end}",
            value_input_option="USER_ENTERED",
        )

    adr = meta.get("ADR")
    adr_text = f"   ADR {adr} [{meta.get('구간')}]" if adr else ""
    print(f"  구글시트 전송 완료: {date_text}  {len(rows)}종목{adr_text}")
    print(f"  → E·F 열(상승원인·키워드)은 비어 있습니다. 채우고 Apps Script 를 돌리세요.")


def main():
    cfg = load_config()
    if cfg is None:
        return
    rows, meta = read_rows()
    push(cfg, rows, meta)


if __name__ == "__main__":
    main()
