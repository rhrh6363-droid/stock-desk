"""
교재 순서 분석 — 수동 실행용 래퍼.
본체는 app/textbook_flow.py (수집 파이프라인이 매 배치마다 돌린다).
app/data/latest.json 의 대상으로 다시 돌려 이 폴더에 날짜별 JSON 을 남긴다.

  python rulebook/교재순서분석기.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(os.path.dirname(HERE), "app")
sys.path.insert(0, APP)

import textbook_flow  # noqa: E402

with open(os.path.join(APP, "data", "latest.json"), encoding="utf-8") as fh:
    payload = json.load(fh)
res = textbook_flow.build(payload, payload.get("거래일", ""))
path = os.path.join(HERE, f"교재순서분석_{res['기준일']}.json")
with open(path, "w", encoding="utf-8") as fh:
    json.dump(res, fh, ensure_ascii=False, indent=1, default=str)
print(path)
