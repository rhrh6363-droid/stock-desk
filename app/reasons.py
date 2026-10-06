"""
===========================================================
  키워드 · 상승이유 — 두 필드를 나눠서 채운다
===========================================================

사용자 지시
  "키워드는 그 종목이 올라간 근거인 뉴스들에서 공통되고 반복되는 키워드를
   찾아서 추출하는 게 핵심이고, 상승이유는 이런 키워드를 기반으로 실제로
   상승한 이유를 정리하는 걸 채워야 함. 상승이유/키워드가 필드값으로 무조건."
  "상승이유를 적을 때는 무슨 관련주고 왜 올랐는지를 반드시 적어."
  "키워드는 최대한 공통된 걸 기준으로. HBM·AI서버·AI메모리·반도체·D램이
   종목별로 뽑힌다면 가장 중복이 많은 키워드를 뽑아줘."

목표 모양 (사용자 예시)
    대한광통신 25.31%
    상승이유 : AI데이터센터 관련주 — 글로벌 시장 수요 확대, 데이터센터 확산
    키워드   : AI데이터센터, 광트랜시버
    근거     : https://...

[ 두 필드는 다른 종류다 ]
  키워드    어느 테마인가        — 명사. 섹터 매핑의 입력이다
  상승이유   무슨 관련주고 왜 올랐나 — 문장. 사람이 읽는다

[ 상승이유를 짓는 방법 — 뺄셈이다 ]
  제목에서 지우면 남는 게 이유다. 패턴으로 '이유구' 를 집으려 해 봤는데
  '금융권 연쇄 해킹에' 처럼 조사가 붙거나 '안랩·지니언스 최고가 기록' 처럼
  엉뚱한 구를 집었다. 그래서 반대로 간다.

    "금융권 연쇄 해킹에 보안주 급등…안랩·지니언스 최고가 기록"
      - 종목명(지니언스·안랩) - 시세어(급등·최고가) - 숫자
      = "금융권 연쇄 해킹에 보안주"

  없는 말을 지어내지 않는다. 제목에 실제로 있는 말만 남긴다.
  기사가 없으면 '근거 기사 없음' 이라고 쓴다 — 비워 두지도, 지어내지도 않는다.

[ 대표키워드 — 가장 중복이 많은 것 ]
  그날 전 종목의 키워드 빈도를 세고, 종목별 키워드를 그 빈도순으로 세운다.
  3종목이 'HBM', 1종목이 'D램' 이면 HBM 이 대표가 된다.
  이게 "AI데이터센터 -> 광통신" 같은 연결을 눈에 보이게 하는 장치다.
===========================================================
"""

import re
from collections import Counter

# 시세·등락을 말하는 어휘. 이유가 아니므로 지운다.
MOVE_WORDS = [
    "급등", "급락", "상승", "하락", "강세", "약세", "폭등", "폭락", "상한가", "하한가",
    "신고가", "최고가", "신저가", "돌파", "탈환", "반등", "조정", "솟구쳤다", "뛰었다",
    "오름세", "내림세", "상승세", "하락세", "급등세", "급락세", "강세", "약세",
    "상승폭", "하락폭", "오른다", "내린다", "올랐다", "내렸다", "오름", "내림",
    "올라", "내려", "뛰어", "밀려", "치솟", "급증", "껑충", "훨훨", "방긋", "봇물",
    "장중", "마감", "개장", "전일", "종가", "시가", "주가", "시세", "거래량", "거래대금",
    "특징주", "속보", "단독", "주목", "관심", "부각", "눈길", "들썩", "술렁",
    "↑", "↓", "▲", "▼",
]

# 숫자 + 뒤에 붙는 단위·조사까지 한 번에 지운다.
# 안 그러면 "12%대 올라" 가 "대 올라" 로, "2027년 양산" 이 "년 양산" 으로 남는다
NUM = re.compile(
    r"[-+]?\d[\d,.]*\s*"
    r"(?:%|％|원|배|포인트|p|선|위|주|억|조|만|년|월|일|차|기|분기|대|호|개|곳|명|건)?"
    r"(?:째|만|여)?")
# 시세어 제거 — 앞 글자가 한글이면 더 긴 낱말의 토막이므로 건드리지 않는다.
# '주주가치' 에서 '주가' 를 지워 '주주 치' 로 만든 적이 있다.
MOVE_RE = re.compile(
    r"(?<![가-힣])(?:" +
    "|".join(re.escape(w) for w in sorted(MOVE_WORDS, key=len, reverse=True)) +
    r")")

CODE = re.compile(r"\(\d{6}\)")
# 머리말뿐 아니라 본문 중간의 것도 뗀다 — "[오늘, 종목]" 이 남은 적이 있다
BRACKET = re.compile(r"[\[【]\s*[^\]】]{0,20}\s*[\]】]")
QUOTE = re.compile(r"[\"'“”‘’‘’`]")
MULTI = re.compile(r"\s{2,}")
EDGE = re.compile(r"^[\s,.·…\-–—:|]+|[\s,.·…\-–—:|]+$")

# 이유구로 남기기엔 너무 짧거나 뜻이 없는 꼬리
TAIL_JUNK = re.compile(r"(?:등극|기록|전환|유지|지속|확인|돌입|진입)$")

MIN_REASON = 6          # 이 아래는 이유로 못 쓴다
MAX_REASON = 60         # 한 줄로 읽히는 길이
NO_NEWS = "근거 기사 없음"
UNCLEAR = "재료 문구 불명확 — 근거 기사 확인"

# 뺄셈 뒤에 남는 한 글자 조각. '탈환한' 에서 '한', '3분기' 에서 '기'
ORPHAN = re.compile(r"(?:^|\s)[가-힣]\s")


def _squeeze(text: str) -> str:
    """한 글자 조각과 겹치는 공백을 턴다."""
    for _ in range(3):
        cut = ORPHAN.sub(" ", text)
        if cut == text:
            break
        text = cut
    return MULTI.sub(" ", text).strip()


def _dedupe(phrases: list[str]) -> list[str]:
    """한쪽이 다른 쪽에 포함되면 긴 쪽만 남긴다.

    HLB 가 '리보세라닙 …' 을 두 번 적은 적이 있다.
    """
    out: list[str] = []
    for p in sorted(phrases, key=len, reverse=True):
        if not any(p in q or _overlap(p, q) for q in out):
            out.append(p)
    return out


def _overlap(a: str, b: str) -> bool:
    """어절 절반 이상이 겹치면 같은 말로 본다."""
    wa, wb = set(a.split()), set(b.split())
    if not wa or not wb:
        return False
    return len(wa & wb) / min(len(wa), len(wb)) >= 0.5


def _strip_names(text: str, names: set[str]) -> str:
    """제목에서 종목명들을 지운다. 긴 이름부터 지워야 토막이 안 남는다."""
    for nm in sorted(names, key=len, reverse=True):
        if len(nm) >= 2:
            text = text.replace(nm, " ")
    return text


def reason_phrase(title: str, name: str, others: set[str]) -> str:
    """기사 제목 하나에서 '왜 올랐나' 만 남긴다 — 뺄셈 방식.

    지우는 것: 대괄호 머리말, 언론사 꼬리, 종목명, 시세어, 숫자, 따옴표
    남는 것  : 재료
    """
    import news

    t = news._strip_source({"제목": title, "출처": ""})
    # 꼬리가 둘일 때가 있다 ("… - 조선비즈 - Chosunbiz"). 안 떼면 본문에 남는다
    for _ in range(3):
        cut = re.sub(r"\s+[-–]\s+[^-–]{2,22}\s*$", "", t)
        if cut == t:
            break
        t = cut
    t = BRACKET.sub("", t)
    t = CODE.sub(" ", t)
    t = QUOTE.sub(" ", t)
    t = _strip_names(t, {name} | others)
    # 긴 것부터, 그리고 앞 경계를 보고 지운다 (MOVE_RE 주석 참고)
    t = MOVE_RE.sub(" ", t)
    t = NUM.sub(" ", t)
    # 조사만 남은 토막 정리
    t = re.sub(r"\s+(?:에|이|가|은|는|을|를|와|과|의|도|만|에서|으로|로)\s+", " ", t)
    t = re.sub(r"[…·]+", " ", t)
    t = MULTI.sub(" ", t)
    t = EDGE.sub("", t)
    t = TAIL_JUNK.sub("", t).strip()
    t = EDGE.sub("", t)

    t = _squeeze(t)
    t = EDGE.sub("", t)
    if len(t) < MIN_REASON:
        return ""
    return t[:MAX_REASON].strip()


def _global_counts(rows: list[dict]) -> Counter:
    """그날 전 종목의 키워드 빈도. '가장 중복이 많은' 키워드를 고르는 기준이다."""
    c = Counter()
    for r in rows:
        for k in (r.get("키워드") or []):
            c[k] += 1
    return c


def consolidate(rows: list[dict]) -> dict:
    """키워드를 공통도 순으로 세우고, 상승이유를 짓는다.

    두 필드를 **반드시** 채운다
      키워드    공통 빈도 높은 순. 대표키워드는 그 첫째
      상승이유   "<대표키워드> 관련주 — <재료>" / 기사가 없으면 '근거 기사 없음'
    """
    counts = _global_counts(rows)
    names = {str(r.get("종목명") or "") for r in rows if r.get("종목명")}

    기사없음 = 0
    문구불명 = 0
    for r in rows:
        name = str(r.get("종목명") or "")
        kws = list(r.get("키워드") or [])

        # 1) 공통도 높은 키워드를 앞으로. 같으면 짧은 쪽(포괄적인 쪽)을 앞으로
        kws.sort(key=lambda k: (-counts[k], len(k)))
        출처 = "뉴스" if kws else ""

        # 뉴스에서 못 뽑았으면 사전의 세부섹터를 쓴다 — 필드를 비우지 않는다.
        # 대장주·종목배정으로 매핑된 종목은 기사 키워드가 없는 게 정상이다
        if not kws:
            for col in ("세부섹터", "대섹터"):
                v = str(r.get(col) or "").strip()
                if v and v != "미분류":
                    kws = [v]
                    출처 = "사전"
                    break

        r["키워드"] = kws
        r["대표키워드"] = kws[0] if kws else ""
        r["키워드출처"] = 출처
        r["키워드공통도"] = {k: counts[k] for k in kws}

        # 2) 재료 — 종목명이 실제로 나온 기사에서만 뽑는다
        items = [n for n in (r.get("뉴스") or []) if n.get("직접언급")]
        모은것: list[str] = []
        for it in items[:3]:
            p = reason_phrase(it.get("제목", ""), name, names - {name})
            if p:
                모은것.append(p)
        재료 = _dedupe(모은것)[:2]

        # 3) 상승이유 — 무슨 관련주고 왜 올랐나
        머리 = f"{r['대표키워드']} 관련주" if r["대표키워드"] else ""
        몸통 = ", ".join(재료)
        if 머리 and 몸통:
            r["상승이유"] = f"{머리} — {몸통}"[:140]
        elif 몸통:
            r["상승이유"] = 몸통
        elif 머리:
            r["상승이유"] = f"{머리} — {UNCLEAR}"
        elif items:
            # 기사는 있다. 문구를 못 뽑았을 뿐이다 — '없음' 이라고 쓰면 거짓이다
            r["상승이유"] = UNCLEAR
            문구불명 += 1
        else:
            r["상승이유"] = NO_NEWS
            기사없음 += 1

        # 4) 근거 — 사용자 예시의 '근거: URL'
        if items:
            r["근거링크"] = items[0].get("링크", "")
            r["근거출처"] = items[0].get("출처", "")
            r["근거제목"] = items[0].get("제목", "")
        else:
            r["근거링크"] = r["근거출처"] = r["근거제목"] = ""

        # 예전 이름을 쓰는 곳이 있어 같이 둔다 (report·sheets·sector_map)
        r["상승원인"] = r["상승이유"]

    top = counts.most_common(8)
    return {
        "전체": len(rows),
        "이유있음": len(rows) - 기사없음 - 문구불명,
        "문구불명": 문구불명,
        "기사없음": 기사없음,
        "대표키워드붙음": sum(1 for r in rows if r.get("대표키워드")),
        "키워드_뉴스": sum(1 for r in rows if r.get("키워드출처") == "뉴스"),
        "키워드_사전": sum(1 for r in rows if r.get("키워드출처") == "사전"),
        "공통키워드": [{"키워드": k, "종목수": n} for k, n in top],
    }


def keyword_rollup(rows: list[dict]) -> list[dict]:
    """키워드별 집계 — "어떤 이슈가 어느 종목을 움직였나".

    사용자 목적: "특정 이슈와 뉴스들이 어떤 섹터와 테마에 엮여서 종목의 시세가
    크게 움직이는지 알아야 해. AI데이터센터 -> 대한광통신 등 광통신 관련 종목에
    영향을 준다는 걸 깨닫는 거지."
    """
    agg: dict[str, dict] = {}
    for r in rows:
        for k in (r.get("키워드") or []):
            e = agg.setdefault(k, {
                "키워드": k, "종목수": 0, "거래대금": 0,
                "종목": [], "대섹터": Counter(), "업종": Counter(),
            })
            e["종목수"] += 1
            e["거래대금"] += int(r.get("거래대금(억)") or 0)
            if len(e["종목"]) < 8:
                e["종목"].append({
                    "종목명": r.get("종목명"),
                    "등락률": r.get("등락률(%)"),
                    "거래대금": r.get("거래대금(억)"),
                })
            if r.get("대섹터"):
                e["대섹터"][r["대섹터"]] += 1
            if r.get("업종"):
                e["업종"][r["업종"]] += 1

    out = []
    for e in agg.values():
        out.append({
            "키워드": e["키워드"],
            "종목수": e["종목수"],
            "거래대금": e["거래대금"],
            "종목": e["종목"],
            "주섹터": e["대섹터"].most_common(1)[0][0] if e["대섹터"] else "",
            "주업종": e["업종"].most_common(1)[0][0] if e["업종"] else "",
        })
    return sorted(out, key=lambda x: (-x["거래대금"], -x["종목수"]))
