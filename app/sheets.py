"""
===========================================================
  구글시트 양방향 연결
===========================================================

  읽기 : 섹터별거래대금대장주_TOP5  →  섹터 사전
  쓰기 : 📋 RAW 데이터              ←  당일 특징주

설정은 E:\\Claude\\trading\\config.json 하나로 한다.
비어 있으면 모든 함수가 조용히 비활성 상태가 된다 — 앱은 로컬 사전으로 계속 돈다.
===========================================================
"""

import json
import os

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(ROOT, "config.json")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

_cfg_cache: dict | None = None


def config() -> dict:
    global _cfg_cache
    if _cfg_cache is not None:
        return _cfg_cache
    if not os.path.exists(CONFIG_FILE):
        _cfg_cache = {}
        return _cfg_cache
    with open(CONFIG_FILE, encoding="utf-8") as fh:
        _cfg_cache = json.load(fh)
    return _cfg_cache


def configured() -> bool:
    c = config()
    key = c.get("service_account_json", "")
    return bool(c.get("spreadsheet_id") and key and os.path.exists(key))


def _book():
    import gspread
    from google.oauth2.service_account import Credentials

    c = config()
    creds = Credentials.from_service_account_file(c["service_account_json"], scopes=SCOPES)
    return gspread.authorize(creds).open_by_key(c["spreadsheet_id"])


# ────────────────────────────────────────────────
# 읽기 — 섹터 사전
# ────────────────────────────────────────────────
def read_sector_dict() -> pd.DataFrame | None:
    """TOP5 시트를 섹터 사전 형태로 읽는다.

    시트 열 구성 (사용자 시트 그대로):
      A 대섹터(빈칸이면 위 값 유지) · B 세부섹터 · C~G 대장주 · H 비고 · I 종목 · J 키워드
    """
    if not configured():
        return None

    name = config().get("top5_sheet_name", "섹터별거래대금대장주_TOP5")
    ws = _book().worksheet(name)
    values = ws.get_all_values()
    if len(values) < 2:
        return None

    cols = ["대섹터", "세부섹터", "대장주1", "대장주2", "대장주3", "대장주4", "대장주5",
            "비고", "종목", "키워드"]
    rows = []
    for raw in values[1:]:                       # 1행은 머리글
        padded = (raw + [""] * 10)[:10]
        if not any(x.strip() for x in padded):
            continue
        rows.append(dict(zip(cols, [x.strip() for x in padded])))

    df = pd.DataFrame(rows)
    df["대섹터"] = df["대섹터"].replace("", pd.NA).ffill().fillna("기타")
    return df[df["세부섹터"] != ""]


# ────────────────────────────────────────────────
# 쓰기 — RAW 데이터
# ────────────────────────────────────────────────
def push_raw(rows: list[dict], payload: dict) -> None:
    """당일 특징주를 '📋 RAW 데이터' 시트에 넣는다.

    B1 거래일 · B4:D 종목명/상승률/거래대금 · E 상승원인 · F 키워드(대섹터)
    E·F 는 뉴스에서 확보한 값만 채우고, 비어 있으면 건드리지 않는다.
    """
    if not configured():
        return

    c = config()
    ws = _book().worksheet(c.get("raw_sheet_name", "📋 RAW 데이터"))
    first = int(c.get("first_data_row", 4))

    last = max(ws.row_count, first)
    ws.batch_clear([f"B{first}:F{last}"])

    raw_date = str(payload.get("거래일", ""))
    date_text = (f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
                 if len(raw_date) == 8 else raw_date)
    ws.update_acell(c.get("date_cell", "B1"), date_text)

    body = [[
        str(r.get("종목명", "")),
        float(r.get("등락률(%)") or 0),
        int(r.get("거래대금(억)") or 0),
        str(r.get("상승원인", "") or ""),
        str(r.get("대섹터", "") or ""),
    ] for r in rows]

    if body:
        ws.update(values=body,
                  range_name=f"B{first}:F{first + len(body) - 1}",
                  value_input_option="USER_ENTERED")
