"""
===========================================================
  장중 수집 (로컬 PC 전용)  →  docs/data/live.json
===========================================================

GitHub Actions 는 1시간 간격이고 예약 실행이 수십 분 밀린다. 6장 단타는 지수 3분봉 20선처럼
분 단위로 바뀌는 조건이 핵심이라 그 간격으로는 쓸 수 없다.

그래서 집 PC 의 작업 스케줄러가 평일 장중 5분마다 이 파일을 돌린다. 하는 일은 세 가지다.

  1) 지수(코스피·코스닥) 3분봉 20선 — 네이버 1분봉. 야후보다 빠르고 점심에 빠지지 않는다
  2) 관심 종목의 '지금까지' 장중 복기 — day_replay 를 그 시각까지의 분봉으로 돌린다
  3) 장중 종목 선정 후보 (6-3) — 네이버 등락률 상위에서 거래대금·시총으로 거른 뒤
     종목마다 3분봉 20선·전일 고가·추격 여부를 붙인다

결과는 docs/data/live.json 하나뿐이고, 그 파일만 커밋·푸시한다. latest.json 은 건드리지 않으므로
GitHub 1시간 수집과 부딪히지 않는다. 화면(chapters.html)은 live.json 이 더 최근이면 그 값으로 덮어쓴다.

  python app/collect_live.py              평일 08:55~15:40 에만 동작, 그 밖에는 조용히 끝난다
  python app/collect_live.py --force      시간과 무관하게 한 번 돌린다 (시험용)
  python app/collect_live.py --no-push    파일만 만들고 깃에 올리지 않는다
===========================================================
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import stock_env                              # noqa: E402,F401  ~/.stock-desk/secrets.env
import pandas as pd                           # noqa: E402
import day_replay as dr                      # noqa: E402
import news                                  # noqa: E402
import reasons                               # noqa: E402
import sector_map                            # noqa: E402
import textbook_flow as tf                   # noqa: E402

KST = timezone(timedelta(hours=9))
DAY = None          # --day 2026-10-15 로 과거 장을 다시 그릴 때만 쓴다 (평소엔 None = 오늘)


def _now():
    return datetime.now(KST) if DAY is None else datetime.combine(DAY, datetime.min.time().replace(hour=15, minute=40), KST)


def _today():
    return DAY or datetime.now(KST).date()
OUT = [os.path.join(ROOT, "docs", "data", "live.json"), os.path.join(HERE, "data", "live.json")]
NEWS_CACHE = os.path.join(HERE, "data", "live_news.json")
THEME_API = "https://m.stock.naver.com/api/stocks/theme"      # 네이버 테마 264개 — 오늘 등락률·구성종목

# 증시 기사 판별 — 시세어(reasons) + 재료어. 하나라도 없으면 그 기사는 재료가 아니다
장기사_RE = re.compile("|".join(re.escape(w) for w in (
    *reasons.MOVE_WORDS, "증시", "코스피", "코스닥", "관련주", "테마", "수혜", "실적", "영업이익", "매출",
    "수주", "계약", "공시", "유상증자", "무상증자", "목표주가", "증권", "투자", "상장", "인수", "합병",
    "리포트", "컨센서스", "호재", "악재", "급등주", "상승률", "시총", "주식")))

# 6-3 장중 종목 선정 거름망 — "돈이 들어온 곳"(거래대금)이 첫째, 너무 작은 종목은 뺀다
스캔_최소_거래대금억 = 300      # 단타 후보로 올릴 최소 조건
스캔_최소_시총억 = 1000
스캔_최대후보 = 10
테마_최소_거래대금억 = 50       # 섹터를 묶을 때는 더 넓게 본다 — 작은 종목이 테마를 알려준다
테마_최소_시총억 = 300
테마_모집단 = 40         # 재료(뉴스)를 붙일 종목 수
테마_최대 = 5            # 6-3 #11 "후보 섹터는 4~5개로 압축" — 화면에 띄우는 수
테마_태깅 = 12           # 종목에 테마를 붙일 때는 좀 더 넓게 본다
테마_최소종목 = 5        # 2~3 종목짜리 테마는 섹터가 아니라 개별이슈다
테마_최소상승비 = 0.6     # 테마 종목의 60% 이상이 올라야 '같이 가는' 섹터다
뉴스_캐시분 = 45         # 재료는 분 단위로 바뀌지 않는다


def _days(code, today, n=40):
    """오늘까지의 네이버 일봉. (--day 로 과거를 재생할 때 미래 봉이 섞이지 않게 자른다)"""
    return [x for x in tf.naver_chart(code, "day", n) if x["t"].date() <= today]


def _f(s):
    try:
        return float(str(s).replace(",", ""))
    except Exception:
        return None


def idx_m3(name):
    """지수 3분봉 20선. 전일 분봉까지 이어 붙여 09:00 부터 바로 20선이 나오게 한다."""
    today = _today()
    cur = dr.naver_min(name, "index", today)
    if not cur:
        return {"판정": "오늘 분봉 없음"}
    prev = []
    for back in range(1, 6):                  # 어제가 휴일이면 더 거슬러 올라간다
        prev = dr.naver_min(name, "index", today - timedelta(days=back))
        if prev:
            break
    bars = [b for b in dr.to3(prev + cur) if b["k"][0] == today]
    last = bars[-1]
    out = {"기준 시각": last["t"].strftime("%m-%d %H:%M"), "3분봉 수": len(bars), "당일": True}
    if last["ma"] is None:
        out["판정"] = "3분봉 20개 미만(장 초반)"
        return out
    out.update({"현재": round(last["c"], 2), "3분봉 20선": round(last["ma"], 2),
                "20선 위": last["c"] >= last["ma"], "이격(%)": round((last["c"] / last["ma"] - 1) * 100, 2),
                "20선 위 비율(%)": round(sum(1 for b in bars if b["ma"] and b["c"] >= b["ma"])
                                       / max(1, sum(1 for b in bars if b["ma"])) * 100)})
    return out


def rank(mkt):
    try:
        j = dr._get(f"https://m.stock.naver.com/api/stocks/up/{mkt}?page=1&pageSize=40")
    except Exception:
        return []
    return j.get("stocks") or []


def _장기사(title):
    """증시 기사만 남긴다. 종목명이 지명·일반명사와 겹치면 엉뚱한 기사가 붙는다
    (예: '서산' → 지역 축제 기사). 제목에 시세·증시 낱말이 없으면 재료로 쓰지 않는다."""
    return bool(장기사_RE.search(title))


def _news(rows):
    """6-3 앞쪽 — 종목마다 기사·키워드를 붙인다(구글 뉴스 RSS, 키 없이 된다).
    재료는 분 단위로 바뀌지 않으므로 45분 캐시를 둔다. 5분마다 같은 검색을 반복할 이유가 없다."""
    try:
        with open(NEWS_CACHE, encoding="utf-8") as fh:
            cache = json.load(fh)
    except Exception:
        cache = {}
    if cache.get("날짜") != _today().strftime("%Y%m%d"):
        cache = {"날짜": _today().strftime("%Y%m%d"), "종목": {}}
    box, now, 새로 = cache["종목"], time.time(), 0
    for r in rows:
        hit = box.get(r["코드"])
        if hit and now - hit["t"] < 뉴스_캐시분 * 60:
            r["뉴스"] = hit["뉴스"]
            continue
        nm = r["종목명"]
        items = [i for i in news.search(nm, limit=8) if _장기사(i["제목"])]
        for it in items:                       # 구글은 느슨하게 맞춘다 — 제목에 종목명이 있는 것부터 쓴다
            it["직접언급"] = news.mentions(news._strip_source(it), nm)
        r["뉴스"] = ([i for i in items if i["직접언급"]] + [i for i in items if not i["직접언급"]])[:4]
        box[r["코드"]] = {"t": now, "뉴스": r["뉴스"]}
        새로 += 1
        time.sleep(news.DELAY)
    try:
        with open(NEWS_CACHE, "w", encoding="utf-8") as fh:
            json.dump(cache, fh, ensure_ascii=False)
    except Exception:
        pass
    return 새로


def themes():
    """6-3 '오늘의 주도 섹터' — 네이버 테마 264개 중 오늘 실제로 같이 오르는 것만 추린다.
    교재는 후보 섹터를 4~5개로 압축하라고 한다(6-3 #11). 테마 안의 종목을 다 받아 오므로
    '같은 테마인데 아직 안 간 종목'(6-3 #6 가지치기)이 그대로 나온다."""
    try:
        gs = dr._get(f"{THEME_API}?page=1&pageSize=60").get("groups") or []
    except Exception:
        return []
    고른것 = [g for g in gs
            if (g.get("totalCount") or 0) >= 테마_최소종목 and _f(g.get("changeRate")) is not None
            and (g["riseCount"] / g["totalCount"]) >= 테마_최소상승비]
    out = []
    for g in 고른것[:테마_태깅]:
        try:
            st = dr._get(f"{THEME_API}/{g['no']}?page=1&pageSize=40").get("stocks") or []
        except Exception:
            continue
        rows = [{"종목명": s["stockName"], "코드": s["itemCode"], "등락률": _f(s.get("fluctuationsRatio")),
                 "거래대금(억)": round((_f(s.get("accumulatedTradingValueRaw")) or 0) / 1e8)}
                for s in st if s.get("stockEndType") == "stock"]
        rows.sort(key=lambda r: -r["거래대금(억)"])
        오른것 = [r for r in rows if (r["등락률"] or 0) > 0]
        out.append({"테마": g["name"], "주도": len(out) < 테마_최대,
                    "등락률": _f(g.get("changeRate")), "종목수": g["totalCount"],
                    "오른 종목 수": g["riseCount"], "내린 종목 수": g["fallCount"],
                    "대장주": rows[0]["종목명"] if rows else "",
                    "오른 종목": 오른것[:8],
                    "아직 안 오른 종목": [r for r in rows if (r["등락률"] or 0) <= 0][:6]})
    return out


def _theme(rows):
    """종목마다 뉴스 키워드로 섹터사전을 태우고(재료·대표키워드·근거링크), 이슈 키워드를 묶는다."""
    dic = sector_map.load_dictionary()
    df, _unmapped = sector_map.apply(pd.DataFrame(rows), dic)
    for r, major, minor in zip(rows, df["대섹터"], df["세부섹터"]):
        r["대섹터"], r["세부섹터"] = major, minor
    reasons.consolidate(rows)                   # 키워드 공통도 정렬 + 상승이유 + 근거링크
    issues = [{"키워드": k["키워드"], "종목수": k["종목수"], "거래대금(억)": k["거래대금"], "주섹터": k["주섹터"],
               "종목": [x["종목명"] for x in k["종목"]]}
              for k in reasons.keyword_rollup(rows) if k["종목수"] >= 2][:6]
    return issues


def scan():
    """6-3 — 등락률 상위에서 거래대금·시총으로 거른 뒤, 뉴스·키워드로 섹터를 묶고(앞쪽 절반),
    후보마다 분봉 자리를 붙인다(뒤쪽 절반). '아침 장대양봉에 따라붙지 않는다'(6-3 #16) 를 위해
    당일 고가 대비 위치를 같이 준다."""
    today = _today()
    cand = []
    for mkt in ("KOSPI", "KOSDAQ"):
        for r in rank(mkt):
            val = _f(r.get("accumulatedTradingValueRaw"))
            cap = _f(r.get("marketValueRaw"))
            chg = _f(r.get("fluctuationsRatio"))
            if val is None or cap is None or chg is None:
                continue
            if val / 1e8 < 테마_최소_거래대금억 or cap / 1e8 < 테마_최소_시총억:
                continue
            if (r.get("tradeStopType") or {}).get("name") != "TRADING":
                continue
            if r.get("stockEndType") != "stock":      # ETF·ETN 은 교재 단타 대상이 아니다
                continue
            cand.append({"코드": r["itemCode"], "이름": r["stockName"], "시장": "코스피" if mkt == "KOSPI" else "코스닥",
                         "등락률": chg, "현재가": _f(r.get("closePriceRaw")),
                         "거래대금(억)": round(val / 1e8), "시총(억)": round(cap / 1e8),
                         "단타후보": val / 1e8 >= 스캔_최소_거래대금억 and cap / 1e8 >= 스캔_최소_시총억})
    cand.sort(key=lambda x: -x["거래대금(억)"])
    pool = cand[:테마_모집단]
    for c in pool:                              # 섹터 모듈이 쓰는 이름으로 맞춰 둔다
        c["종목명"], c["등락률(%)"] = c["이름"], c["등락률"]
    groups, issues = [], []
    try:
        groups = themes()
    except Exception as exc:
        print(f"  [테마 실패] {type(exc).__name__}: {exc}")
    속한테마 = {}
    for g in groups:
        for r in g["오른 종목"] + g["아직 안 오른 종목"]:
            속한테마.setdefault(r["코드"], []).append(g["테마"])
    try:
        _news(pool)
        issues = _theme(pool)
    except Exception as exc:
        print(f"  [재료 실패] {type(exc).__name__}: {exc}")
    for c in pool:                              # 뉴스 원문은 화면에 안 쓴다 — 파일만 커진다
        c.pop("뉴스", None), c.pop("업종힌트", None), c.pop("키워드공통도", None)
        c.pop("종목명", None), c.pop("등락률(%)", None), c.pop("상승원인", None)
        c["테마"] = 속한테마.get(c["코드"], [])
        c["주도섹터"] = bool(c["테마"])
    # 6-3 #1 — 주도 섹터에 속한 종목을 먼저 본다. 그다음 거래대금 순
    print(f"  테마 {len(groups)}개 · 모집단 {len(pool)} · 재료 {sum(1 for c in pool if c.get('근거링크'))} · "
          f"주도테마 종목 {sum(1 for c in pool if c['주도섹터'])}")
    pool.sort(key=lambda x: (not x["주도섹터"], -x["거래대금(억)"]))
    out = []
    for c in [x for x in pool if x["단타후보"]][:스캔_최대후보]:
        try:
            m1 = dr.naver_min(c["코드"], "item", today)
            d = [x for x in _days(c["코드"], today, 5) if x["t"].date() < today]
            if len(m1) < 10 or not d:
                continue
            prev = d[-1]                       # 전일 봉 — 오늘 봉은 장중이라 아직 자라는 중이다
            b3 = dr.to3(m1)
            last = b3[-1]
            hi = max(b["h"] for b in b3)
            # 현재가·등락률은 순위표 대신 분봉으로 다시 잰다 (순위표는 지연되고, --day 재생 때는 다른 날 값이 온다)
            c.update({"현재가": last["c"], "등락률": round((last["c"] / prev["c"] - 1) * 100, 2),
                      "3분봉 20선": round(last["ma"], 2) if last["ma"] else None,
                      "20선 위": None if last["ma"] is None else last["c"] >= last["ma"],
                      "당일 고가": hi, "고가 대비(%)": round((last["c"] / hi - 1) * 100, 2),
                      "전일 고가": prev["h"], "전일 고가 돌파": last["c"] > prev["h"]})
            day = dr.Day(m1, [], [], [], prev["h"], prev["c"])
            day.idx = {}                       # 지수 조건은 위쪽 3분봉 카드가 따로 보여준다
            sig = []
            for nm, src, fn, *_ in dr.METHODS:
                n, px, stop, t1, why, _b = fn(day)
                if n is None:
                    continue
                ago = int((last["t"] - b3[n]["t"]).total_seconds() // 60)
                sig.append({"매매법": nm, "교재": src, "시각": b3[n]["t"].strftime("%H:%M"), "경과(분)": ago,
                            "신선": ago <= 15, "가격": px, "손절": round(stop), "1차 목표": round(t1), "근거": why})
            c["신호"] = sorted(sig, key=lambda x: x["경과(분)"])
            out.append(c)
        except Exception as exc:
            c["오류"] = f"{type(exc).__name__}"
            out.append(c)
    return out, groups, issues


def build():
    now = _now()
    today = _today()
    pl_path = os.path.join(HERE, "data", "latest.json")
    with open(pl_path, encoding="utf-8") as fh:
        pl = json.load(fh)
    stocks = [(s["코드"], s["이름"], s.get("심볼", ""))
              for s in (pl.get("교재흐름") or {}).get("종목", []) if s.get("코드")]

    mk = {}
    for nm, key in (("KOSPI", "코스피"), ("KOSDAQ", "코스닥")):
        try:
            mk[key] = idx_m3(nm)
        except Exception as exc:
            mk[key] = {"판정": f"실패: {type(exc).__name__}"}

    if all("20선 위" not in v and v.get("판정") == "오늘 분봉 없음" for v in mk.values()):
        print("  오늘 분봉이 없다(휴장일) — 아무것도 쓰지 않는다")
        return None

    out_st, frames = [], {}
    for code, name, sym in stocks:
        try:
            d = _days(code, today)
            if d and d[-1]["t"].date() != today:
                d = d + [{"t": datetime.combine(today, datetime.min.time()).replace(tzinfo=KST),
                          "o": d[-1]["c"], "h": d[-1]["c"], "l": d[-1]["c"], "c": d[-1]["c"], "v": 0}]
            r = dr.replay(code, "KOSDAQ" if sym.endswith(".KQ") else "KOSPI", d)
            fr = r.pop("_frame", None)
            if fr:
                frames[code] = fr
            out_st.append({"코드": code, "이름": name, "단타 복기": r})
        except Exception as exc:
            out_st.append({"코드": code, "이름": name, "단타 복기": {"판정": f"복기 실패: {type(exc).__name__}: {exc}"}})

    try:
        sc, groups, issues = scan()
    except Exception as exc:
        sc, groups, issues = [], [], []
        print(f"  [스캔 실패] {type(exc).__name__}: {exc}")

    live = {"기준일": today.strftime("%Y%m%d"),      # latest.json 의 '거래일'과 같은 꼴이라야 화면이 맞춰 본다
            "기준시각": now.strftime("%Y-%m-%d %H:%M"),
            "수집": "로컬 PC 5분 간격 (collect_live.py)", "장중": DAY is None and "0900" <= now.strftime("%H%M") <= "1540",
            "지수 3분봉": mk, "종목": out_st, "3분봉 프레임": frames,
            "스캔": {"기준": f"등락률 상위 중 거래대금 {스캔_최소_거래대금억}억 이상 · 시총 {스캔_최소_시총억}억 이상 "
                           f"{테마_모집단}개를 뉴스·섹터로 묶고, 주도 섹터 먼저 {스캔_최대후보}개",
                   "후보": sc, "테마": [g for g in groups if g["주도"]], "이슈 키워드": issues}}
    body = json.dumps(live, ensure_ascii=False, separators=(",", ":"), default=str)
    for p in OUT:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(body)
    print(f"[장중] {live['기준시각']} · 지수 {mk.get('코스피', {}).get('기준 시각', '-')} · "
          f"종목 {len(out_st)} · 후보 {len(sc)} · {len(body) // 1024}KB")
    return live


def push():
    """live.json 하나만 올린다. 봇 커밋과 겹치면 rebase 로 비켜간다."""
    def git(*a, check=True):
        return subprocess.run(["git", "-C", ROOT, *a], capture_output=True, text=True, check=check)

    rel = os.path.relpath(OUT[0], ROOT).replace("\\", "/")      # docs/data/live.json 하나만 올린다
    git("add", "--", rel)
    if not git("diff", "--cached", "--quiet", check=False).returncode:
        print("  바뀐 것 없음")
        return
    git("commit", "-q", "-m", f"장중 {datetime.now(KST).strftime('%m-%d %H:%M')}", "--", rel)
    for _ in range(3):
        if git("push", "-q", check=False).returncode == 0:
            print("  푸시 완료")
            return
        r = git("pull", "--rebase", "-q", check=False)
        if r.returncode:
            git("rebase", "--abort", check=False)
            print(f"  푸시 보류(다음 회차에 다시 시도): {r.stderr.strip()[:120]}")
            return
    print("  푸시 실패 — 다음 회차에 다시 시도")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--day" in args:
        DAY = datetime.strptime(args[args.index("--day") + 1], "%Y-%m-%d").date()
    now = _now()
    if DAY is None and "--force" not in args and (now.weekday() >= 5 or not ("0855" <= now.strftime("%H%M") <= "1540")):
        sys.exit(0)                            # 장 시간이 아니면 아무것도 하지 않는다
    sys.stdout.reconfigure(encoding="utf-8")
    if build() and "--no-push" not in args:
        push()
