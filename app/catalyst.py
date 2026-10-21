"""
===========================================================
  재료 요약 — 오늘 기사 제목들에서 '왜 올랐나' 를 뽑는다
===========================================================

[ 왜 따로 만들었나 ]
  news.extract_keywords 는 섹터 사전에 있는 말만 받는다. 그래서 그날의 진짜 재료가
  사전에 없으면 통째로 버려진다. 2026-10-21 삼성전자 +5.7% 의 재료는
    슈퍼마이크로 호실적 · 마이크론 파업 예고(반사이익) · 반도체 반등 · 외국인 순매수
  였는데, 키워드로 남은 건 'HBM' 정도였다.
  "OO에 강세" 앞부분을 정규식으로 집어 봤지만 '슈퍼마이크로 호실적 훈풍에',
  '美 AI 기업 호실적에' 처럼 표현이 조금만 달라도 놓쳤다.

[ 방법 ]
  1. Claude(haiku) 가 있으면 — 시장 시황 기사 + 종목별 오늘 기사 제목을 한 번에 넣고
     시장 재료 몇 개와 종목별 재료·재료키워드를 JSON 으로 받는다. 제목만 넣는다(본문 X).
  2. 키가 없거나 실패하면 — 제목 규칙(_rule)으로 '○○에 강세' 의 원인구를 집는다.
  어느 쪽이든 없는 말을 지어내지 않는다. 기사 제목에 있는 사실만 쓴다.

  키: ANTHROPIC_API_KEY (~/.stock-desk/secrets.env, GitHub Actions Secrets)
===========================================================
"""

import json
import os
import re
from collections import Counter

import news
import reasons

MODEL = "claude-haiku-5-5"
MAX_TITLES = 10           # 종목당 넣을 기사 제목 수
MAX_MARKET = 30           # 시장 시황 제목 수

SYSTEM = """너는 한국 주식시장 장중 재료 분석가다. 오늘 기사 제목만 보고 '왜 올랐나'를 정리한다.

규칙
- 제목에 실제로 나온 사실만 쓴다. 제목에 없는 원인을 추측해 만들지 않는다.
- 재료는 원인을 짧은 명사구로 쓴다. 예: "슈퍼마이크로 호실적", "마이크론 파업 예고 반사이익", "중동 휴전 기대", "외국인 순매수".
- 시세 표현(급등·강세·5%↑·신고가)은 재료가 아니다. 재료 없이 시세만 말하는 제목은 무시한다.
- 재료키워드는 같은 이슈로 묶일 수 있는 짧은 말(2~10자)이다. 예: "AI서버", "마이크론 파업", "HBM", "중동".
  여러 종목에 같은 이슈가 걸리면 같은 표현을 쓴다.
- 종목 재료가 시장 재료와 같으면 같은 표현을 쓴다.
- 재료를 못 찾으면 빈 배열로 둔다."""

SCHEMA = {
    "type": "object",
    "properties": {
        "시장재료": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "재료": {"type": "string"},
                    "설명": {"type": "string"},
                    "영향": {"type": "string"},
                },
                "required": ["재료", "설명", "영향"],
                "additionalProperties": False,
            },
        },
        "종목": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "재료": {"type": "array", "items": {"type": "string"}},
                    "재료키워드": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "재료", "재료키워드"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["시장재료", "종목"],
    "additionalProperties": False,
}


def available() -> bool:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def _titles(items: list[dict], n: int) -> list[str]:
    return [f"{it.get('시각', '')} {news._strip_source(it)}".strip() for it in items[:n]]


def _prompt(market: list[dict], stocks: list[dict]) -> str:
    lines = ["# 시장 시황 기사 제목 (오늘)"]
    lines += [f"- {t}" for t in _titles(market, MAX_MARKET)] or ["- (없음)"]
    lines.append("\n# 종목별 기사 제목 (오늘 특징주 기사 → 오늘 일반 기사 → 이전 기사)")
    for i, r in enumerate(stocks):
        chg = r.get("등락률(%)", r.get("등락률"))
        lines.append(f"\n## id={i} {r.get('종목명')} ({chg:+.2f}%)" if isinstance(chg, (int, float))
                     else f"\n## id={i} {r.get('종목명')}")
        lines += [f"- {t}" for t in _titles(r.get("뉴스") or [], MAX_TITLES)] or ["- (기사 없음)"]
    lines.append("\n시장재료는 오늘 시장 전체를 움직인 재료 3~6개, 영향에는 수혜 업종·종목을 짧게."
                 "\n종목은 위 id 마다 하나씩, 재료 최대 3개·재료키워드 최대 3개.")
    return "\n".join(lines)


def _llm(market: list[dict], stocks: list[dict]) -> dict:
    import anthropic

    client = anthropic.Anthropic(max_retries=2, timeout=90.0)
    resp = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM,
        output_config={"effort": "low",
                       "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": _prompt(market, stocks)}],
    )
    if resp.stop_reason in ("refusal", "max_tokens"):
        raise RuntimeError(f"stop_reason={resp.stop_reason}")
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)


# ── 규칙 폴백 ─────────────────────────────────────────────
# "美 AI기업 호실적·마이크론 파업 예고에 강세" → 원인구
CAUSE = re.compile(
    r"([가-힣A-Za-z0-9·美中日\s]{2,40}?)\s*(?:기대감?|훈풍|수혜|여파|소식|호재)?\s*(?:에|로|으로)\s*"
    r"(?:[가-힣]{0,6}\s*)?(?:동반\s*)?(?:[\d.,]+\s*%?\s*대?\s*)?"
    r"(?:강세|급등|상승|반등|오름|올라|↑|들썩|껑충)")
JUNK = re.compile(r"하루\s*만|보고|지분율|수량|기록|:|^[가-힣]{1,2}$|(?:하며|하고|해|한)$")
NUMUNIT = re.compile(r"[\d.,]+\s*(?:%|％|조|억|만|원|포인트|선|대)*")


def _rule(name: str, items: list[dict], others: set[str]) -> list[str]:
    c = Counter()
    if name:                                  # 다른 종목 기사의 재료가 붙지 않게
        items = [it for it in items if news.mentions(news._strip_source(it), name)]
    for it in items[:MAX_TITLES]:
        t = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", news._strip_source(it))
        t = re.sub(r"^[^,…]{0,30}(?:마감시황|시황)\]?\s*", " ", t)
        for nm in sorted({name} | others, key=len, reverse=True):
            if len(nm) >= 2:
                t = t.replace(nm, " ")
        for m in CAUSE.findall(t):
            for part in re.split(r"\s*(?:·|,|…|및)\s*", m):
                p = re.sub(r"\s{2,}", " ", part).strip(" '\"‘’“”-")
                p = re.sub(r"\s{2,}", " ", NUMUNIT.sub(" ", p)).strip()
                p = re.sub(r"^(?:코스피|코스닥|증시|국내증시)\s*,?\s*", "", p).strip()
                p = re.sub(r"\s{2,}", " ", reasons.MOVE_RE.sub(" ", p)).strip()
                # 시세만 말하는 토막('급락 하루 만')·공시 문구는 재료가 아니다
                if len(p) < 4 or p in news.STOP or JUNK.search(p):
                    continue
                c[p] += 1
    return reasons._dedupe([k for k, _ in c.most_common(5)])[:3]


def attach(rows: list[dict], market: list[dict]) -> dict:
    """종목마다 '재료'·'재료키워드' 를 붙이고 시장재료 목록을 돌려준다.

    rows 의 '뉴스' 가 먼저 붙어 있어야 한다 (news.attach / stock_news).
    """
    names = {str(r.get("종목명") or "") for r in rows}
    if available() and rows:
        try:
            out = _llm(market, rows)
            for s in out.get("종목", []):
                try:
                    r = rows[int(s["id"])]
                except (ValueError, IndexError, KeyError):
                    continue
                r["재료"] = [x for x in s.get("재료", []) if x][:3]
                r["재료키워드"] = [x for x in s.get("재료키워드", []) if x][:3]
            for r in rows:
                r.setdefault("재료", []), r.setdefault("재료키워드", [])
            return {"방식": f"AI({MODEL})", "시장재료": out.get("시장재료", [])[:6],
                    "재료붙음": sum(1 for r in rows if r["재료"])}
        except Exception as exc:
            print(f"  [재료 AI 실패 → 규칙] {type(exc).__name__}: {str(exc)[:120]}")

    for r in rows:
        nm = str(r.get("종목명") or "")
        r["재료"] = _rule(nm, r.get("뉴스") or [], names - {nm})
        r["재료키워드"] = []
    # 시장재료 — 시황 제목들에서 같은 원인구를 센다
    c = Counter()
    for it in market:
        for p in _rule("", [it], names):
            c[p] += 1
    return {"방식": "규칙", "시장재료": [{"재료": k, "설명": f"시황 기사 {n}건", "영향": ""}
                                     for k, n in c.most_common(6)],
            "재료붙음": sum(1 for r in rows if r["재료"])}
