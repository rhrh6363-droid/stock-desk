"""
===========================================================
  일일보고서 생성
===========================================================

사용자 시트 '일일보고서' 장표의 항목을 수집 데이터로 채운다.

[ 원칙 ]
  숫자는 수집한 데이터에서만 쓴다. 없는 건 비워둔다.
  '영향'·'전망' 같은 해석은 쓰지 않는다 — 사용자가 한다.
  종목선정은 <제안> 으로만 쓰고 근거를 같이 보여준다.

[ 핫뉴스 선별 — 측정 가능한 신호만 쓴다 ]
  보도 집중도 : 같은 재료를 쓴 서로 다른 매체 수
  시장 반응   : 그 재료를 가진 종목들이 실제로 끌어온 거래대금
  점수        : 매체수 × 거래대금.  "내가 중요해 보여서" 고르지 않는다.
===========================================================
"""

import json
import os
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

# 매크로 사건어 — 이 말이 들어간 기사만 따로 본다
MACRO_TERMS = [
    "FOMC", "금리", "연준", "CPI", "물가", "고용지표",
    "전쟁", "휴전", "공습", "지정학",
    "관세", "수출규제", "제재",
    "어닝", "실적", "가이던스",
    "유가", "환율", "국채",
    "엔비디아", "TSMC", "마이크론",
]


def _load(date: str) -> dict | None:
    f = os.path.join(DATA, f"{date}.json")
    if not os.path.exists(f):
        return None
    try:
        with open(f, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def previous(date: str) -> dict | None:
    """직전 거래일 보고서. 섹터 변화 방향을 계산하는 데 쓴다."""
    if not os.path.isdir(DATA):
        return None
    days = sorted(f[:8] for f in os.listdir(DATA)
                  if f.endswith(".json") and f[:8].isdigit() and f[:8] < date)
    return _load(days[-1]) if days else None


def _rows(payload: dict) -> list[dict]:
    return [r for g in payload.get("그룹", []) for r in g.get("종목", [])]


# ────────────────────────────────────────────────
# 핫뉴스 — 보도 집중도 × 시장 반응
# ────────────────────────────────────────────────
def hot_news(payload: dict, limit: int = 8) -> list[dict]:
    """오늘 돈이 실제로 따라간 재료를 점수 순으로."""
    rows = _rows(payload)
    매체 = defaultdict(set)        # 키워드 → 보도한 매체 집합
    기사 = {}                      # 키워드 → 대표 기사
    거래대금 = defaultdict(int)
    종목 = defaultdict(list)

    for r in rows:
        kws = r.get("키워드") or []
        if not kws:
            continue
        value = int(r.get("거래대금(억)") or 0)
        for kw in kws:
            거래대금[kw] += value
            종목[kw].append(r.get("종목명"))
            for n in (r.get("뉴스") or []):
                src = (n.get("출처") or "").strip()
                if src:
                    매체[kw].add(src)
                기사.setdefault(kw, n)

    out = []
    for kw, value in 거래대금.items():
        매체수 = len(매체[kw])
        n = len(종목[kw])
        out.append({
            "재료": kw,
            "매체수": 매체수,
            "종목수": n,
            "거래대금": value,
            "점수": 매체수 * value,
            "종목": 종목[kw][:5],
            "대표기사": 기사.get(kw, {}).get("제목", ""),
            "링크": 기사.get(kw, {}).get("링크", ""),
        })
    out.sort(key=lambda x: -x["점수"])
    return out[:limit]


def macro_news(limit: int = 6) -> list[dict]:
    """매크로 사건 후보. 해석은 붙이지 않는다 — 제목과 링크만."""
    import news

    seen, out = set(), []
    for term in MACRO_TERMS:
        items = news.search(f"{term} 증시", limit=2)
        for it in items:
            key = it["제목"][:40]
            if key in seen:
                continue
            seen.add(key)
            out.append({**it, "사건어": term})
    # 같은 사건을 여러 매체가 썼는지로 정렬할 수 없으므로 발행 최신순
    out.sort(key=lambda x: x.get("날짜", ""), reverse=True)
    return out[:limit]


# ────────────────────────────────────────────────
# 섹터 변화 방향
# ────────────────────────────────────────────────
def sector_shift(payload: dict, prev: dict | None) -> dict:
    """어제 대비 섹터 변화. 시트의 '주도 지속 / 신규 부상 / 전환 리스크'."""
    def table(p):
        return {g["대섹터"]: g for g in (p or {}).get("그룹", [])
                if g.get("대섹터") != "미분류"}

    now, before = table(payload), table(prev)
    if not before:
        return {"기준일": None, "지속": [], "신규": [], "소멸": [], "증감": []}

    지속, 신규, 소멸, 증감 = [], [], [], []
    for name, g in now.items():
        b = before.get(name)
        if b is None:
            신규.append({"대섹터": name, "거래대금": g["합산거래대금"],
                        "종목수": g["종목수"], "대장주": g["대장주"]})
            continue
        delta = g["합산거래대금"] - b["합산거래대금"]
        pct = round(delta / b["합산거래대금"] * 100, 1) if b["합산거래대금"] else None
        증감.append({"대섹터": name, "전일": b["합산거래대금"], "당일": g["합산거래대금"],
                    "증감": delta, "증감률": pct})
        if g.get("분류") == "주도업종" and b.get("분류") == "주도업종":
            지속.append({"대섹터": name, "거래대금": g["합산거래대금"],
                        "전일거래대금": b["합산거래대금"], "대장주": g["대장주"]})

    for name, b in before.items():
        if name not in now:
            소멸.append({"대섹터": name, "전일거래대금": b["합산거래대금"],
                        "전일등급": b.get("등급"), "전일대장주": b.get("대장주")})

    증감.sort(key=lambda x: -(x["증감"] or 0))
    신규.sort(key=lambda x: -x["거래대금"])
    소멸.sort(key=lambda x: -x["전일거래대금"])
    return {"기준일": (prev or {}).get("거래일"),
            "지속": 지속, "신규": 신규, "소멸": 소멸, "증감": 증감}


# ────────────────────────────────────────────────
# 리스크 · 체크리스트 · 제안
# ────────────────────────────────────────────────
def risks(payload: dict) -> dict:
    rows = _rows(payload)
    rsi = [r for r in rows if (r.get("RSI(14)") or 0) >= 70]
    heat = [r for r in rows if r.get("과열")]
    small = [r for r in rows if r.get("시총기준") == "미달"]
    indiv = [r for r in rows if r.get("수급주체") == "개인"]
    return {
        "RSI70이상": [{"종목명": r["종목명"], "RSI": r.get("RSI(14)")} for r in rsi][:12],
        "과열": [{"종목명": r["종목명"], "2일누적": r.get("2일누적(%)"),
                 "판정": r.get("과열")} for r in heat][:12],
        "시총미달": [r["종목명"] for r in small][:12],
        "개인쏠림": [r["종목명"] for r in indiv][:12],
        "요약": {"RSI70": len(rsi), "과열": len(heat),
                "시총미달": len(small), "개인쏠림": len(indiv)},
    }


def checklist(r: dict) -> list[dict]:
    """투자원칙을 종목 하나에 적용한 점검표."""
    rsi = r.get("RSI(14)")
    stop, take = r.get("제안손절(%)"), r.get("제안익절(%)")
    return [
        {"항목": "시총 5천억 이상", "통과": r.get("시총기준") == "충족",
         "값": f'{r.get("시총(억)"):,.0f}억' if r.get("시총(억)") else "—"},
        {"항목": "RSI 70 미만", "통과": rsi is not None and rsi < 70,
         "값": f"{rsi:.1f}" if rsi is not None else "—"},
        {"항목": "2일 40% 과열 아님", "통과": not r.get("과열"),
         "값": f'{r.get("2일누적(%)"):.1f}%' if r.get("2일누적(%)") is not None else "—"},
        {"항목": "외국인·기관 수급", "통과": bool(r.get("수급주체")) and r.get("수급주체") != "개인",
         "값": r.get("수급주체") or "—"},
        {"항목": "3:1 손익비 성립", "통과": stop is not None and take is not None,
         "값": f"{stop}% / +{take}%" if stop is not None else "—"},
        {"항목": "상승 근거 확인", "통과": bool(r.get("상승원인")),
         "값": (r.get("상승원인") or "—")[:40]},
    ]


def suggest(payload: dict, shift: dict) -> dict:
    """<제안> 종목선정. 판단은 사용자가 한다 — 근거를 같이 낸다."""
    groups = [g for g in payload.get("그룹", [])
              if g.get("분류") == "주도업종" and g.get("대섹터") != "미분류"]

    if not groups:
        return {
            "선정섹터": None,
            "매매법": None,
            "후보": [],
            "코멘트": "주도업종(같은 섹터 3종목 이상)이 없다. 개별이슈 장이다. "
                     "투자원칙 9에 따라 관찰만 하고 들어가지 않는 쪽을 <제안>한다.",
        }

    지속 = {s["대섹터"] for s in shift.get("지속", [])}
    후보 = []
    for g in groups[:3]:
        top = g["종목"][0]
        second = g["종목"][1] if g["종목수"] > 1 else None
        checks = checklist(top)
        통과 = sum(1 for c in checks if c["통과"])

        # 눌림목 vs 돌파 — 이격도와 볼밴 위치로 가른다
        이격 = top.get("이격도")
        밴드 = top.get("볼밴위치") or ""
        if "상단돌파" in 밴드:
            매매법 = "돌파 (상단 돌파 상태 — 추격은 거래대금 확인 후)"
        elif 이격 is not None and 이격 < 100:
            매매법 = "눌림목 (20일선 아래 — 반등 확인 후)"
        else:
            매매법 = "관찰 (분기 애매 — 장중 거래대금으로 재판정)"

        후보.append({
            "대섹터": g["대섹터"],
            "종목명": top["종목명"],
            "등락률": top.get("등락률(%)"),
            "거래대금": top.get("거래대금(억)"),
            "섹터합산": g["합산거래대금"],
            "섹터종목수": g["종목수"],
            "2등주": second["종목명"] if second else None,
            "2등주등락률": second.get("등락률(%)") if second else None,
            "근거": top.get("상승원인", ""),
            "매매법": 매매법,
            "체크": checks,
            "통과": 통과,
            "총항목": len(checks),
            "전일지속": g["대섹터"] in 지속,
        })

    후보.sort(key=lambda x: (-x["통과"], -x["섹터합산"]))
    best = 후보[0]
    말 = (f'<제안> 1순위는 {best["대섹터"]} / {best["종목명"]}. '
          f'점검 {best["통과"]}/{best["총항목"]} 통과, 매매법은 {best["매매법"]}.')
    if best["통과"] < best["총항목"]:
        막힌 = [c["항목"] for c in best["체크"] if not c["통과"]]
        말 += f' 다만 {", ".join(막힌)} 이(가) 걸린다. 투자원칙 9 — 애매하면 사지 않는다.'
    if best["2등주"]:
        율 = best["2등주등락률"]
        율 = f'{율:+.2f}' if isinstance(율, (int, float)) else '—'
        말 += f' D+1 상따를 본다면 2등주 {best["2등주"]}({율}%)가 무너졌는지 먼저 확인한다.'

    return {"선정섹터": best["대섹터"], "매매법": best["매매법"],
            "후보": 후보, "코멘트": 말}


# ────────────────────────────────────────────────
def build(payload: dict) -> dict:
    """일일보고서 전체를 만든다."""
    prev = previous(payload.get("거래일", ""))
    shift = sector_shift(payload, prev)
    return {
        "핫뉴스": hot_news(payload),
        "매크로뉴스": macro_news(),
        "섹터변화": shift,
        "리스크": risks(payload),
        "제안": suggest(payload, shift),
    }
