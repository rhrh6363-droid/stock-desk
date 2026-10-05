"""
===========================================================
  정적 사이트 빌드  →  docs/
===========================================================

GitHub Pages 에는 파이썬 서버가 없다. 그래서 server.py 가 만들어주던
/api/latest · /api/heatmap 응답을 **파일로 미리 구워둔다.**

  app/static/index.html   →  docs/index.html
  app/data/latest.json    →  docs/data/latest.json
  build_heatmap()         →  docs/data/heatmap.json

index.html 은 /api/* 를 먼저 찍어보고 404 면 data/*.json 으로 넘어가므로
로컬(server.py)과 Pages 양쪽에서 같은 파일이 그대로 돈다.

  python app/build_static.py
===========================================================
"""

import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (HERE, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

STATIC = os.path.join(HERE, "static")
DATA = os.path.join(HERE, "data")
DOCS = os.path.join(ROOT, "docs")
DOCS_DATA = os.path.join(DOCS, "data")


def build() -> dict:
    from server import build_heatmap          # argparse 는 __main__ 에서만 돈다

    os.makedirs(DOCS_DATA, exist_ok=True)

    # 1. 화면 파일
    copied = 0
    for name in os.listdir(STATIC):
        src = os.path.join(STATIC, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(DOCS, name))
            copied += 1

    # 2. 최신 자료
    latest = os.path.join(DATA, "latest.json")
    if os.path.exists(latest):
        shutil.copy2(latest, os.path.join(DOCS_DATA, "latest.json"))
    else:
        with open(os.path.join(DOCS_DATA, "latest.json"), "w", encoding="utf-8") as fh:
            json.dump({"상태": "없음", "안내": "아직 수집된 자료가 없습니다."},
                      fh, ensure_ascii=False)

    # 3. 히트맵 — 날짜별 JSON 을 모아 미리 구워둔다
    heat = build_heatmap()
    with open(os.path.join(DOCS_DATA, "heatmap.json"), "w", encoding="utf-8") as fh:
        json.dump(heat, fh, ensure_ascii=False)

    # 4. Jekyll 처리 끄기 (언더바로 시작하는 파일이 사라지는 것을 막는다)
    open(os.path.join(DOCS, ".nojekyll"), "w").close()

    stat = {"화면파일": copied, "히트맵날짜": len(heat.get("날짜", []))}
    print(f"[빌드] docs/  {stat}")
    return stat


if __name__ == "__main__":
    build()
