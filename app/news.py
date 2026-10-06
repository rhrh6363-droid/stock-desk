"""
===========================================================
  뉴스 근거 + 키워드 추출
===========================================================

[ 왜 네이버가 아닌가 ]
  2026-07-31  네이버 개발자센터 검색 API 신규 신청 중단 (API HUB 로 이관)
  2026-07-07  검색 결과를 AI 에 입력·학습·평가에 쓰는 것을 약관상 금지
  → 신규 발급이 막혔고, 설령 받아도 이 용도는 약관 위반이다. 쓰지 않는다.

[ 대체 ] 구글 뉴스 RSS
  키·가입·할당량이 없다. 한국어 결과가 나오고 언론사와 발행시각이 같이 온다.
    https://news.google.com/rss/search?q=<검색어>&hl=ko&gl=KR&ceid=KR:ko

[ 이 모듈이 하는 일 — 두 가지다 ]
  1. 상승 원인 근거    기사 제목 + 링크. 시트의 '상승이유'·'URL' 열에 해당
  2. 키워드 추출       시트의 '키워드' 열에 해당. **섹터 매핑의 입력이다**

  키워드가 매핑을 좌우하므로 news 는 반드시 섹터 매핑 **앞에** 돌아야 한다.
===========================================================
"""

import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

RSS = "https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

LOOKBACK_DAYS = 3          # 당일 재료를 보려면 짧아야 한다
PER_STOCK = 4              # 종목당 기사 수
DELAY = 0.25               # 연속 호출 간격 (초)
CACHE_MIN = 30

# 세 글자 이상 어휘는 제목에 들어 있기만 하면 받는다.
# 두 글자 어휘는 'OO주' / 'OO 테마' 꼴일 때만 받는다 (_short_hit 참고).
VOCAB_MIN = 3

TAG = re.compile(r"<[^>]+>")
# "특징주, 종목명-반도체 기판(FC-BGA) 테마 상승세에" → 테마 앞 구문을 집는다
THEME = re.compile(r"[-–,]\s*([가-힣A-Za-z0-9·\s]{2,30}?)\s*(?:\([^)]*\))?\s*테마")
NOISE = re.compile(r"\[[^\]]*\]|\([^)]*\)|[\"'“”‘’]")

_cache: dict[str, tuple[float, list[dict]]] = {}

# 제목에서 키워드로 뽑지 않을 말. 섹터를 가르지 못한다.
STOP = {
    "특징주", "주가", "장중", "오늘", "상한가", "급등", "강세", "상승", "하락", "약세",
    "코스피", "코스닥", "증시", "시황", "마감", "개장", "종목", "투자", "매수", "매도",
    "전일", "기준", "기업", "상장", "분기", "실적", "공시", "대비", "확대", "기대",
    "전망", "발표", "체결", "계약", "수주", "출시", "진행", "예정", "관련", "주목",
    "시가총액", "시총", "거래대금", "거래량", "외국인", "기관", "개인", "순매수",
}


def available() -> bool:
    """키가 필요 없다. 항상 쓸 수 있다."""
    return True


def _clean(text: str) -> str:
    return TAG.sub("", text or "").replace("&quot;", '"').replace("&amp;", "&").strip()


def search(query: str, limit: int = PER_STOCK) -> list[dict]:
    """구글 뉴스 RSS. 실패하면 빈 리스트 — 전체를 멈추지 않는다."""
    now = time.time()
    hit = _cache.get(query)
    if hit and now - hit[0] < CACHE_MIN * 60:
        return hit[1][:limit]

    q = urllib.parse.quote(f"{query} when:{LOOKBACK_DAYS}d")
    req = urllib.request.Request(RSS.format(q=q), headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            root = ET.fromstring(r.read())
    except Exception:
        _cache[query] = (now, [])
        return []

    out = []
    for item in root.findall(".//item")[:limit * 2]:
        title = _clean(item.findtext("title"))
        if not title:
            continue
        src = item.find("source")
        out.append({
            "제목": title,
            "링크": item.findtext("link", ""),
            "출처": (src.text if src is not None else "") or "",
            "날짜": item.findtext("pubDate", "")[:22],
        })
        if len(out) >= limit:
            break

    _cache[query] = (now, out)
    return out


def _tokens(title: str) -> list[str]:
    """제목에서 키워드 후보를 뽑는다."""
    body = NOISE.sub(" ", title)
    # 언론사 꼬리표 제거 ("... - 연합뉴스")
    body = re.split(r"\s+-\s+\S+$", body)[0]
    parts = re.split(r"[^가-힣A-Za-z0-9]+", body)
    return [p for p in parts if len(p) >= 2 and p not in STOP and not p.isdigit()]


def _short_hit(term: str, title: str) -> bool:
    """두 글자 섹터어가 '테마를 가리키는 꼴'로 쓰였는지."""
    return bool(re.search(
        rf"{re.escape(term)}\s*(?:주|株)\b|{re.escape(term)}\s*(?:주)?\s*테마|"
        rf"{re.escape(term)}\s*관련주|{re.escape(term)}\s*섹터", title))


def extract_keywords(items: list[dict], vocab: set[str], name: str = "") -> list[str]:
    """기사 제목에서 섹터 키워드를 뽑는다.

    vocab = 섹터 사전이 아는 말(세부섹터명·키워드). 여기에 걸리는 말이 제일 정확하다.
    사전에 없으면 '테마' 패턴과 제목 토큰으로 보충한다.
    """
    found: list[str] = []

    def add(word: str):
        w = word.strip()
        if w and w != name and w not in found and len(w) >= 2:
            found.append(w)

    for it in items:
        # 제목 끝의 '- 언론사' 를 떼고 본다.
        # 안 떼면 '조선일보' 에서 '조선', '전자신문' 에서 '전자' 가 키워드로 잡힌다
        title = it["제목"]
        src = (it.get("출처") or "").strip()
        if src and title.endswith(src):
            title = title[: -len(src)].rstrip(" -–·|")
        title = re.sub(r"\s+[-–]\s+\S+$", "", title)

        # 1. "...-OOO 테마 상승세에" → 테마명을 그대로
        for m in THEME.findall(title):
            add(m.strip())

        # 2. 사전이 아는 말이 제목에 통째로 들어 있으면 채택 (가장 신뢰도 높음)
        for v in vocab:
            if v not in title:
                continue
            if len(v) >= VOCAB_MIN or _short_hit(v, title):
                add(v)

    # 제목 토큰 폴백은 쓰지 않는다.
    # '910선' '대구지역' '2위로' 같은 말이 섞여 들어와 엉뚱한 섹터에 꽂힌다.
    # 사전이 아는 말이 하나도 안 걸리면 키워드 없이 두는 편이 낫다 → 미분류.
    return found[:8]


def attach(rows: list[dict], vocab: set[str] | None = None, limit: int = 40) -> dict:
    """거래대금 상위 종목에 기사·키워드·상승원인을 붙인다.

    vocab 을 주면 섹터 사전 어휘를 우선해 키워드를 뽑는다.
    """
    if not rows:
        return {"조회": 0, "사유": "대상 종목 없음"}

    vocab = vocab or set()
    order = sorted(range(len(rows)),
                   key=lambda i: -(rows[i].get("거래대금(억)") or 0))[:limit]
    target = set(order)

    맞은수 = 0
    for i, r in enumerate(rows):
        if i not in target:
            r.setdefault("뉴스", [])
            r.setdefault("키워드", [])
            r.setdefault("상승원인", "")
            continue

        name = str(r.get("종목명") or "").strip()
        items = search(name) if name else []
        time.sleep(DELAY)

        r["뉴스"] = items
        r["키워드"] = extract_keywords(items, vocab, name)
        r["상승원인"] = items[0]["제목"] if items else ""
        if items:
            맞은수 += 1

    키워드붙은수 = sum(1 for r in rows if r.get("키워드"))
    return {"조회": 맞은수, "대상": len(target), "전체": len(rows),
            "키워드추출": 키워드붙은수, "출처": "구글 뉴스 RSS"}


def vocabulary(dic) -> set[str]:
    """섹터 사전에서 키워드 어휘를 모은다 (세부섹터명 + 키워드 열)."""
    words: set[str] = set()
    if dic is None or len(dic) == 0:
        return words
    for col in ("세부섹터", "키워드"):
        if col not in dic.columns:
            continue
        for cell in dic[col].fillna(""):
            for part in re.split(r"[|,\n]", str(cell)):
                p = part.strip()
                if len(p) >= 2 and p not in STOP:
                    words.add(p)
    return words
