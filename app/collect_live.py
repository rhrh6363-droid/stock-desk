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
import subprocess
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import day_replay as dr                      # noqa: E402
import textbook_flow as tf                   # noqa: E402

KST = timezone(timedelta(hours=9))
DAY = None          # --day 2026-10-15 로 과거 장을 다시 그릴 때만 쓴다 (평소엔 None = 오늘)


def _now():
    return datetime.now(KST) if DAY is None else datetime.combine(DAY, datetime.min.time().replace(hour=15, minute=40), KST)


def _today():
    return DAY or datetime.now(KST).date()
OUT = [os.path.join(ROOT, "docs", "data", "live.json"), os.path.join(HERE, "data", "live.json")]

# 6-3 장중 종목 선정 거름망 — "돈이 들어온 곳"(거래대금)이 첫째, 너무 작은 종목은 뺀다
스캔_최소_거래대금억 = 300
스캔_최소_시총억 = 1000
스캔_최대후보 = 10


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


def scan():
    """6-3 — 등락률 상위에서 거래대금·시총으로 거른 뒤, 후보마다 분봉 자리를 붙인다.
    '아침 장대양봉에 따라붙지 않는다'(6-3 #16) 를 위해 당일 고가 대비 위치를 같이 준다."""
    today = _today()
    cand = []
    for mkt in ("KOSPI", "KOSDAQ"):
        for r in rank(mkt):
            val = _f(r.get("accumulatedTradingValueRaw"))
            cap = _f(r.get("marketValueRaw"))
            chg = _f(r.get("fluctuationsRatio"))
            if val is None or cap is None or chg is None:
                continue
            if val / 1e8 < 스캔_최소_거래대금억 or cap / 1e8 < 스캔_최소_시총억:
                continue
            if (r.get("tradeStopType") or {}).get("name") != "TRADING":
                continue
            if r.get("stockEndType") != "stock":      # ETF·ETN 은 교재 단타 대상이 아니다
                continue
            cand.append({"코드": r["itemCode"], "이름": r["stockName"], "시장": "코스피" if mkt == "KOSPI" else "코스닥",
                         "등락률": chg, "현재가": _f(r.get("closePriceRaw")),
                         "거래대금(억)": round(val / 1e8), "시총(억)": round(cap / 1e8)})
    cand.sort(key=lambda x: -x["거래대금(억)"])
    out = []
    for c in cand[:스캔_최대후보]:
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
    return out


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
        sc = scan()
    except Exception as exc:
        sc = []
        print(f"  [스캔 실패] {type(exc).__name__}: {exc}")

    live = {"기준일": today.strftime("%Y%m%d"),      # latest.json 의 '거래일'과 같은 꼴이라야 화면이 맞춰 본다
            "기준시각": now.strftime("%Y-%m-%d %H:%M"),
            "수집": "로컬 PC 5분 간격 (collect_live.py)", "장중": DAY is None and "0900" <= now.strftime("%H%M") <= "1540",
            "지수 3분봉": mk, "종목": out_st, "3분봉 프레임": frames,
            "스캔": {"기준": f"등락률 상위 중 거래대금 {스캔_최소_거래대금억}억 이상 · 시총 {스캔_최소_시총억}억 이상, 거래대금 순 {스캔_최대후보}개",
                   "후보": sc}}
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
