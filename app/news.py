"""
===========================================================
  상승 원인 근거  —  네이버 검색 API
===========================================================

종목별 당일 뉴스를 받아 '왜 올랐는가'의 근거로 붙인다.
크롤링하지 않는다. 공식 API 만 쓴다.

[ 키 발급 — 1회, 무료 ]
  1) developers.naver.com 로그인 → 애플리케이션 등록
  2) 사용 API 에서 '검색' 선택
  3) 발급된 Client ID / Client Secret 를 환경변수로

     setx NAVER_ID     "클라이언트ID"
     setx NAVER_SECRET "클라이언트시크릿"

키가 없으면 근거 칸이 비고, 나머지는 정상 동작한다.
===========================================================
"""

import os
import re
import time
import urllib.parse
import urllib.request
import json

ENDPOINT = "https://openapi.naver.com/v1/search/news.json"
TAG = re.compile(r"<[^>]+>")
CACHE_TTL = 60 * 30          # 30분. 1시간 배치에서 같은 종목을 반복 조회하지 않는다

_cache: dict[str, tuple[float, list[dict]]] = {}


def available() -> bool:
    return bool(os.environ.get("NAVER_ID") and os.environ.get("NAVER_SECRET"))


def _clean(text: str) -> str:
    text = TAG.sub("", text or "")
    for a, b in (("&quot;", '"'), ("&amp;", "&"), ("&lt;", "<"),
                 ("&gt;", ">"), ("&apos;", "'"), ("&nbsp;", " ")):
        text = text.replace(a, b)
    return text.strip()


def search(query: str, count: int = 3) -> list[dict]:
    """종목 관련 최신 뉴스. 실패하면 빈 리스트 — 전체를 멈추지 않는다."""
    if not available():
        return []

    now = time.time()
    hit = _cache.get(query)
    if hit and now - hit[0] < CACHE_TTL:
        return hit[1]

    url = f"{ENDPOINT}?query={urllib.parse.quote(query)}&display={count}&sort=date"
    req = urllib.request.Request(url, headers={
        "X-Naver-Client-Id": os.environ["NAVER_ID"],
        "X-Naver-Client-Secret": os.environ["NAVER_SECRET"],
    })

    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception:
        _cache[query] = (now, [])
        return []

    items = [{
        "제목": _clean(it.get("title")),
        "요약": _clean(it.get("description")),
        "링크": it.get("originallink") or it.get("link"),
        "일시": it.get("pubDate", ""),
    } for it in body.get("items", [])]

    _cache[query] = (now, items)
    return items


def attach(rows: list[dict], limit: int = 40) -> dict:
    """특징주 목록에 뉴스를 붙인다. 거래대금 상위 limit 종목만 조회한다.

    전 종목을 매 배치마다 조회하면 API 한도(일 25,000회)를 빠르게 쓴다.
    대장주 판별에 필요한 건 상위권이다.
    """
    if not available():
        return {"조회": 0, "사유": "NAVER_ID / NAVER_SECRET 환경변수 없음"}

    ordered = sorted(rows, key=lambda r: r.get("거래대금(억)") or 0, reverse=True)
    hit = 0
    for row in ordered[:limit]:
        name = str(row.get("종목명", "")).strip()
        if not name:
            continue
        items = search(f"{name} 주가")
        row["뉴스"] = items
        if items:
            row["상승원인"] = items[0]["제목"]
            hit += 1
        time.sleep(0.05)          # 호출 간격을 조금 둔다

    return {"조회": len(ordered[:limit]), "확보": hit}
