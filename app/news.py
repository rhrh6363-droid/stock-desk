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

# 업종 힌트 — "비철금속 업종", "2차전지 장비주", "기계업종", "사이버보안주"
# 모르는 종목이 무슨 회사인지 알려주는 말들이다. 섹터 배정의 근거로 쓴다.
HINT = re.compile(
    r"([가-힣A-Za-z0-9·]{2,12})\s*(?:업종|섹터)"
    r"|([가-힣A-Za-z0-9·]{2,12})\s*(?:장비주|소재주|관련주|테마주|그룹주|부품주)"
    r"|([가-힣A-Za-z0-9·]{2,12})\s*테마"
    # "게임주 하락", "사이버보안주 강세" — 'OO주' 꼴. HINT_STOP 으로 걸러 낸다
    r"|([가-힣A-Za-z0-9·]{2,10})주(?![가-힣A-Za-z])"
    # "전원장치 사업 회복 여부" — 무슨 사업을 하는 회사인지 그대로 말해 준다
    r"|([가-힣A-Za-z0-9·]{2,12})\s*사업"
)
# 힌트로 쓸 수 없는 말 — 업종을 가리키지 않는다.
# 'OO주' 패턴을 넓히면서 '대장주'·'우선주'·'수혜주' 같은 말이 들어온다
HINT_STOP = {
    "코스피", "코스닥", "증시", "국내", "해외", "전체", "일부", "주요", "기타",
    "오늘", "장중", "급등", "상승", "강세", "하락", "약세", "최고", "신규",
    "대장", "우선", "개별", "성장", "가치", "수혜", "저평가", "소형", "중소형",
    "대형", "유망", "추천", "관심", "인기", "거래", "보통", "신고", "급락",
    "테마", "업종", "섹터", "종목", "현재", "이번", "다음", "지난",
    # 'OO주' 패턴이 '최대주주'·'특징주'·'자사주' 의 앞토막을 집어 온다
    "최대주", "특징", "자사", "유통", "발행", "신주", "구주", "액면", "무상",
    "보유", "지분", "상한", "하한", "애프터마켓", "주가",
}

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


def _strip_source(it: dict) -> str:
    """제목 끝의 '- 언론사' 를 뗀다.

    안 떼면 '조선일보' 에서 '조선', '전자신문' 에서 '전자' 가 키워드로 잡혀
    주성엔지니어링이 조선주가 된다. 실제로 그랬다.
    """
    title = it.get("제목") or ""
    src = (it.get("출처") or "").strip()
    if src and title.endswith(src):
        title = title[: -len(src)].rstrip(" -–·|")
    return re.sub(r"\s+[-–]\s+\S+$", "", title)


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
        title = _strip_source(it)

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


def mentions(title: str, name: str) -> bool:
    """제목이 이 종목을 가리키는가.

    단순 `name in title` 은 부분문자열에 속는다. 실제로 겪은 것:
      '브이엠'  이 '에이치브이엠 주식담보대출' 에 걸렸다  → 다른 회사다
      'AI'     가 'VAI 종결' 에 걸려 HLB 가 AI인프라로 갔다

    종목명 **앞** 글자가 한글이나 영숫자면 더 긴 이름의 한 토막이다. 거른다.
    뒤 글자는 보지 않는다 — 'CS도', '모비릭스는' 처럼 조사가 바로 붙는다.
    """
    if not name or not title:
        return False
    at = 0
    while True:
        i = title.find(name, at)
        if i < 0:
            return False
        before = title[i - 1] if i > 0 else ""
        if not (before and (before.isalnum() or "\uac00" <= before <= "\ud7a3")):
            return True
        at = i + 1


def industry_hints(items: list[dict], name: str = "") -> list[str]:
    """기사 제목에서 '무슨 업종인가' 를 가리키는 말을 뽑는다.

    키워드 추출(extract_keywords) 은 섹터 사전이 아는 말만 받는다. 그래서
    사전에 없는 업종은 하나도 안 걸리고 미분류가 된다. 이 함수는 사전과
    무관하게 제목이 말해 주는 업종을 그대로 꺼내 **사람이 읽고 판단**하게 한다.

      "비철금속 업종, 구리·알루미늄 가격 반등"  → 비철금속
      "2차전지 장비주, 수주 잔고와 실적"        → 2차전지
      "디케이락·씨케이솔루션·브릴스 급등… 기계업종"  → 기계
    """
    out: list[str] = []
    for it in items:
        # 종목명이 안 나온 기사에서 뽑으면 엉뚱한 업종이 붙는다.
        # '예선테크' 의 힌트에 'HLB' 가 섞인 적이 있다.
        if name and not it.get("직접언급"):
            continue
        title = _strip_source(it)
        for groups in HINT.findall(title):
            for g in groups:
                w = (g or "").strip(" ·")
                if not w or w == name or w in HINT_STOP or w in STOP:
                    continue
                if len(w) < 2 or w.isdigit():
                    continue
                if w not in out:
                    out.append(w)
    return out[:6]


def cohorts(items: list[dict], name: str = "") -> list[str]:
    """같은 기사에 함께 이름이 오른 종목들.

    "디케이락·씨케이솔루션·브릴스 급등" 처럼 묶여 나오면 같은 재료다.
    아는 종목이 하나라도 섞여 있으면 모르는 종목의 정체를 짚을 수 있다.
    """
    out: list[str] = []
    for it in items:
        if name and not it.get("직접언급"):
            continue
        title = _strip_source(it)
        # 가운뎃점·슬래시로 나열된 종목명 묶음을 집는다
        for chunk in re.findall(r"[가-힣A-Za-z0-9]{2,12}(?:\s*[·/]\s*[가-힣A-Za-z0-9]{2,12})+", title):
            for part in re.split(r"\s*[·/]\s*", chunk):
                p = part.strip()
                if p and p != name and p not in STOP and p not in HINT_STOP and len(p) >= 2:
                    if p not in out:
                        out.append(p)
    return out[:8]


def evidence(rows: list[dict], name: str) -> dict:
    """미분류 종목 하나에 붙일 판단 인자 묶음.

    화면(종목배정 탭)에서 사용자가 이걸 읽고 대섹터를 고른다.
    추측해서 섹터를 지어내지 않는다 — 근거만 보여주고 판단은 사람이 한다.
    """
    r = next((x for x in rows if x.get("종목명") == name), None)
    if r is None:
        return {}
    items = r.get("뉴스") or []
    return {
        "업종힌트": industry_hints(items, name),
        "동반언급": [c for c in cohorts(items, name)
                   if c not in (r.get("키워드") or [])],
        "직접언급수": sum(1 for it in items if it.get("직접언급")),
        "기사수": len(items),
        "검색": "https://news.google.com/search?q="
                + urllib.parse.quote(name) + "&hl=ko&gl=KR&ceid=KR:ko",
    }


def attach(rows: list[dict], vocab: set[str] | None = None,
           limit: int | None = None) -> dict:
    """모든 종목에 기사·키워드·상승원인을 붙인다.

    vocab 을 주면 섹터 사전 어휘를 우선해 키워드를 뽑는다.

    limit=None 이면 전 종목을 본다. 예전에 40으로 잘라 두었는데, 잘려 나가는
    하위 종목이 바로 사용자가 "무슨 회사인지도 모르는" 소형주였다.
    판단 인자가 가장 필요한 종목을 빼고 있었으니 거꾸로였다.
    """
    if not rows:
        return {"조회": 0, "사유": "대상 종목 없음"}

    vocab = vocab or set()
    if limit is None:
        target = set(range(len(rows)))
    else:
        target = set(sorted(range(len(rows)),
                            key=lambda i: -(rows[i].get("거래대금(억)") or 0))[:limit])

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

        # 구글 뉴스는 느슨하게 매칭한다. '예선테크' 로 찾으면 HLB 기사가,
        # '이미지스' 로 찾으면 넥슨 기사가 1위로 온다. 제목에 종목명이 없는
        # 기사다. 그래서 신뢰도를 표시해 두고, 상승원인은 직접 언급된 것부터 쓴다.
        for it in items:
            it["직접언급"] = mentions(_strip_source(it), name)
        direct = [it for it in items if it["직접언급"]]

        r["뉴스"] = direct + [it for it in items if not it["직접언급"]]
        r["키워드"] = extract_keywords(r["뉴스"], vocab, name)
        r["상승원인"] = direct[0]["제목"] if direct else ""
        r["업종힌트"] = industry_hints(r["뉴스"], name)
        if direct:
            맞은수 += 1

    키워드붙은수 = sum(1 for r in rows if r.get("키워드"))
    힌트붙은수 = sum(1 for r in rows if r.get("업종힌트"))
    return {"조회": 맞은수, "대상": len(target), "전체": len(rows),
            "키워드추출": 키워드붙은수, "업종힌트": 힌트붙은수,
            "출처": "구글 뉴스 RSS"}


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
