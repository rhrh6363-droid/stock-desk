"""
교재 순서 분석 — 일일보고서 '교재 순서' 장표
설계 문서: rulebook/교재적용체계.md

  0장  세팅      : 월·주·일·60분·5분 프레임을 받는다. 화면 원칙 = 주가·이평·거래량
  1~5장 차트·수급 : 프레임별 사실을 계산한다
  6~7장 매매법    : 매매법마다 조건 충족/미충족/판정불가 → 적합도
  8장  틀         : 적합한 매매법의 진입·손절·목표·대응을 가격으로
  9장  시장       : 지수·해외·환율·금리·VIX·계절성 → 장세 → 현금 비중
  10장 결론       : 9장 게이트를 통과한 것만 남긴다
"""
import json, math, sys, io, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
KST = timezone(timedelta(hours=9))


# ───────────────────────── 0장: 데이터 ─────────────────────────
def _get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read())


def yahoo(sym, interval, rng):
    u = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}"
         f"?range={rng}&interval={interval}")
    try:
        j = _get(u)["chart"]["result"][0]
    except Exception:
        return [], {}
    ts = j.get("timestamp") or []
    q = j["indicators"]["quote"][0]
    out = []
    for i, t in enumerate(ts):
        c = q["close"][i]
        if c is None:
            continue
        o = q["open"][i] if q["open"][i] is not None else c
        h = q["high"][i] if q["high"][i] is not None else c
        l = q["low"][i] if q["low"][i] is not None else c
        out.append({"t": datetime.fromtimestamp(t, KST), "o": float(o), "h": float(h),
                    "l": float(l), "c": float(c), "v": float(q["volume"][i] or 0)})
    return out, j.get("meta", {})


def naver_trend(code, n=60):
    try:
        rows = _get(f"https://m.stock.naver.com/api/stock/{code}/trend?pageSize={n}")
    except Exception:
        return []
    num = lambda s: float(str(s).replace(",", "").replace("+", "").replace("%", "") or 0)
    out = []
    for r in rows:
        out.append({"d": r["bizdate"], "외국인": num(r["foreignerPureBuyQuant"]),
                    "기관": num(r["organPureBuyQuant"]), "개인": num(r["individualPureBuyQuant"]),
                    "보유율": num(r["foreignerHoldRatio"]), "종가": num(r["closePrice"])})
    return out[::-1]   # 과거 → 최근


def naver_chart(code, tf, count):
    """네이버 fchart — KRX 종가와 일치한다 (야후 일봉 종가는 어긋나는 날이 있다: 10/15 삼성전자 210,000 vs 207,500)."""
    import re as _re
    try:
        req = urllib.request.Request(f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe={tf}&count={count}&requestType=0", headers=UA)
        with urllib.request.urlopen(req, timeout=25) as r:
            t = r.read().decode("euc-kr", errors="replace")
    except Exception:
        return []
    out = []
    for item in _re.findall(r'data="([^"]+)"', t):
        dt, o, h, l, c, v = item.split("|")
        if "null" in (o, h, l, c):
            continue
        out.append({"t": datetime.strptime(dt[:8], "%Y%m%d").replace(tzinfo=KST), "o": float(o), "h": float(h),
                    "l": float(l), "c": float(c), "v": float(v)})
    return out


def load_stock(code):
    d = naver_chart(code, "day", 3000)
    w = naver_chart(code, "week", 600)
    sym, best = None, -1
    for suf in (".KS", ".KQ"):          # 코스닥 종목도 .KS 로 빈 응답이 오는 경우가 있어 5분봉 개수로 고른다
        x, meta = yahoo(code + suf, "5m", "5d")
        if len(x) > best:
            sym, best = code + suf, len(x)
    if len(d) < 250 or not sym:
        return None
    m, _ = yahoo(sym, "1mo", "max")
    nm = naver_chart(code, "month", 3)
    if m and nm:   # 이번 달 봉은 네이버 값으로 맞춘다
        m[-1].update({k: nm[-1][k] for k in ("o", "h", "l", "c")})
    h60, _ = yahoo(sym, "60m", "730d")
    m5, _ = yahoo(sym, "5m", "5d")
    return {"sym": sym, "d": d, "w": w, "m": m, "h60": h60, "m5": m5, "meta": meta}


# ───────────────────────── 계산 도구 ─────────────────────────
def sma(xs, n):
    out, s = [None] * len(xs), 0.0
    for i, x in enumerate(xs):
        s += x
        if i >= n:
            s -= xs[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema(xs, n):
    k, out, e = 2 / (n + 1), [], None
    for x in xs:
        e = x if e is None else x * k + e * (1 - k)
        out.append(e)
    return out


def rsi(cl, n=14):
    if len(cl) <= n:
        return [None] * len(cl)
    out = [None] * len(cl)
    g = sum(max(cl[i] - cl[i - 1], 0) for i in range(1, n + 1)) / n
    l = sum(max(cl[i - 1] - cl[i], 0) for i in range(1, n + 1)) / n
    out[n] = 100 - 100 / (1 + g / l) if l else 100
    for i in range(n + 1, len(cl)):
        ch = cl[i] - cl[i - 1]
        g = (g * (n - 1) + max(ch, 0)) / n
        l = (l * (n - 1) + max(-ch, 0)) / n
        out[i] = 100 - 100 / (1 + g / l) if l else 100
    return out


def pct(a, b):
    return None if (a is None or b in (None, 0)) else (a / b - 1) * 100


def r1(x, k=1):
    return None if x is None else round(x, k)


def tick(price):
    """KRX 호가단위 (2023 개편 기준) — 라운드피겨 계산용."""
    for lim, t in ((2000, 1), (5000, 5), (20000, 10), (50000, 50), (200000, 100), (500000, 500)):
        if price < lim:
            return t
    return 1000


def round_figures(p):
    """1-4: 1,000 / 5,000 / 10,000 / 50,000 / 100,000 단위. 가격대에 맞는 단위만."""
    units = [u for u in (1000, 5000, 10000, 50000, 100000, 500000) if p / u <= 40 and p / u >= 0.5] or [1000]
    below, above = [], []
    for u in units:
        below.append(math.floor(p / u) * u)
        above.append(math.ceil(p / u) * u)
    b = max(x for x in below if x <= p) if below else None
    a = min(x for x in above if x > p) if any(x > p for x in above) else None
    return b, a


def pivots(rows, k=5):
    hi, lo = [], []
    for i in range(k, len(rows) - k):
        if rows[i]["h"] == max(r["h"] for r in rows[i - k:i + k + 1]):
            hi.append(i)
        if rows[i]["l"] == min(r["l"] for r in rows[i - k:i + k + 1]):
            lo.append(i)
    return hi, lo


def vol_profile(rows, bins=15):
    """1-5 매물대 차트: 매물대 수 15개. 보여지는 기간만큼."""
    lo, hi = min(r["l"] for r in rows), max(r["h"] for r in rows)
    if hi <= lo:
        return []
    step = (hi - lo) / bins
    acc = [0.0] * bins
    for r in rows:
        tp = (r["h"] + r["l"] + r["c"]) / 3
        acc[min(int((tp - lo) / step), bins - 1)] += r["v"] * tp
    tot = sum(acc) or 1
    return [{"하단": lo + i * step, "상단": lo + (i + 1) * step, "비중": acc[i] / tot * 100}
            for i in range(bins)]


def candle(r, prev=None):
    rng = r["h"] - r["l"] or 1e-9
    body = r["c"] - r["o"]
    up = r["h"] - max(r["o"], r["c"])
    dn = min(r["o"], r["c"]) - r["l"]
    chg = pct(r["c"], prev["c"]) if prev else None
    tags = []
    if abs(body) / rng < 0.15:
        tags.append("도지/단봉")
    if up / rng >= 0.45 and up > abs(body):
        tags.append("긴 윗꼬리")
    if dn / rng >= 0.45 and dn > abs(body):
        tags.append("긴 아래꼬리")
    if body > 0 and r["o"] and body / r["o"] >= 0.05:
        tags.append("장대양봉")
    if body < 0 and r["o"] and -body / r["o"] >= 0.05:
        tags.append("장대음봉")
    if prev and body > 0 and prev["c"] < prev["o"] and r["c"] > prev["o"] and r["o"] <= prev["c"]:
        tags.append("상승장악형")
    if prev and body < 0 and prev["c"] > prev["o"] and r["o"] >= prev["c"] and r["c"] < prev["o"]:
        tags.append("하락장악형")
    return {"양음": "양봉" if body > 0 else "음봉" if body < 0 else "보합",
            "등락률": r1(chg, 2), "형태": tags or ["보통"],
            "윗꼬리비": r1(up / rng * 100, 0), "아래꼬리비": r1(dn / rng * 100, 0)}


# ───────────────────────── 1~5장: 프레임별 사실 ─────────────────────────
def monthly(m):
    cl = [r["c"] for r in m]
    c = cl[-1]
    out = {}
    for n in (18, 20, 60, 120):
        ma = sma(cl, n)[-1]
        out[f"{n}월선"] = r1(ma, 0)
        out[f"{n}월선 위"] = None if ma is None else c >= ma
    low24 = min(r["l"] for r in m[-24:])
    hi_all = max(r["h"] for r in m)
    top36 = max(r["h"] for r in m[-36:])
    bot36 = min(r["l"] for r in m[-36:])
    out.update({
        "24개월 저점": r1(low24, 0), "저점 대비(%)": r1(pct(c, low24)),
        "사상 최고가": r1(hi_all, 0), "최고가 대비(%)": r1(pct(c, hi_all)),
        "36개월 박스 위치(%)": r1((c - bot36) / (top36 - bot36) * 100 if top36 > bot36 else None, 0),
        "봉수": len(m),
    })
    p = out["36개월 박스 위치(%)"]
    out["월봉 박스"] = None if p is None else ("상단" if p >= 67 else "중심" if p >= 33 else "하단")
    return out


def weekly(w):
    cl = [r["c"] for r in w]
    c = cl[-1]
    out = {}
    ma = {n: sma(cl, n) for n in (5, 10, 13, 20, 60, 120)}
    for n, s in ma.items():
        out[f"{n}주선"] = r1(s[-1], 0)
    out["10주선 이격(%)"] = r1(pct(c, ma[10][-1]))
    # 10·20주 교차 (9-1 §11)
    st = []
    for i in range(-6, 0):
        a, b = ma[10][i], ma[20][i]
        st.append(None if a is None or b is None else a >= b)
    out["10·20주 상태"] = "골든(10>20)" if st[-1] else "데드(10<20)"
    out["10·20주 최근 교차"] = any(st[i] != st[i - 1] for i in range(1, len(st)) if st[i] is not None and st[i - 1] is not None)
    # 주봉 이평 중 어디까지 내려왔나 (9-1 §11-2)
    below = [n for n in (13, 20, 60, 120) if ma[n][-1] and c < ma[n][-1]]
    out["이탈한 주봉선"] = below
    # 직전 양봉을 깼는가 (1-14 §2)
    last_bull = next((r for r in reversed(w[:-1]) if r["c"] > r["o"]), None)
    if last_bull:
        out["직전 주봉 양봉"] = {"시가": r1(last_bull["o"], 0), "저가": r1(last_bull["l"], 0),
                            "날짜": last_bull["t"].strftime("%Y-%m-%d")}
        out["직전 양봉 깸"] = ("저가까지 깸" if c < last_bull["l"] else
                          "시가 깸" if c < last_bull["o"] else "안 깸")
    out["이번 주 캔들"] = candle(w[-1], w[-2])
    # 주봉 볼린저 20·2 — 발산/응축 (1-9 PART H)
    bw = []
    for i in range(19, len(cl)):
        seg = cl[i - 19:i + 1]
        mu = sum(seg) / 20
        sd = (sum((x - mu) ** 2 for x in seg) / 20) ** 0.5
        bw.append((4 * sd / mu * 100, mu - 2 * sd, mu + 2 * sd))
    if len(bw) > 160:
        hist = sorted(x[0] for x in bw[-156:])
        now = bw[-1][0]
        rank = sum(1 for x in hist if x <= now) / len(hist) * 100
        trend = bw[-1][0] - bw[-5][0]
        out["주봉 볼린저 폭(%)"] = r1(now)
        out["폭 3년 백분위"] = r1(rank, 0)
        out["폭 방향(4주)"] = "벌어지는 중" if trend > 0 else "좁혀지는 중"
        out["주봉 볼린저 하단"] = r1(bw[-1][1], 0)
        out["주봉 볼린저 상단"] = r1(bw[-1][2], 0)
        out["발산·응축"] = ("응축(좁음)" if rank <= 25 else "발산(넓음)" if rank >= 75 else "중간") + " · " + out["폭 방향(4주)"]
    # 주봉 기준봉 (최근 52주 최대 거래량 양봉) 3라인 (9-1 §11-3, 7-5 [2])
    yr = w[-52:]
    bulls = [r for r in yr if r["c"] > r["o"]]
    if bulls:
        k = max(bulls, key=lambda r: r["v"])
        out["주봉 기준봉"] = {"날짜": k["t"].strftime("%Y-%m-%d"), "저점": r1(k["l"], 0),
                          "중심": r1((k["o"] + k["c"]) / 2, 0), "고점": r1(k["h"], 0),
                          "현재가 위치": ("고점 위" if c > k["h"] else "중심 위" if c >= (k["o"] + k["c"]) / 2
                                       else "저점 위" if c >= k["l"] else "저점 아래")}
    # 주봉 장기 매물대 (1-14 §4)
    vp = vol_profile(w[-156:])
    if vp:
        top = sorted(vp, key=lambda x: -x["비중"])[:3]
        out["주봉 3년 매물대 상위3"] = [f"{x['하단']:,.0f}~{x['상단']:,.0f} ({x['비중']:.0f}%)" for x in top]
        sup = [x for x in vp if x["상단"] <= c]
        res = [x for x in vp if x["하단"] > c]
        out["아래 가장 두꺼운 매물대"] = (lambda x: f"{x['하단']:,.0f}~{x['상단']:,.0f}")(max(sup, key=lambda x: x["비중"])) if sup else None
        out["위 가장 두꺼운 매물대"] = (lambda x: f"{x['하단']:,.0f}~{x['상단']:,.0f}")(max(res, key=lambda x: x["비중"])) if res else None
    # 주봉 OBV 방향 (4-3)
    obv, s = [], 0
    for i in range(1, len(w)):
        s += w[i]["v"] if w[i]["c"] > w[i - 1]["c"] else -w[i]["v"] if w[i]["c"] < w[i - 1]["c"] else 0
        obv.append(s)
    if len(obv) > 21:
        po = cl[-1] - cl[-21]
        oo = obv[-1] - obv[-21]
        out["주봉 OBV(20주)"] = ("주가↓ OBV↑ 매집 다이버전스" if po < 0 < oo else
                             "주가↑ OBV↓ 분산 다이버전스" if po > 0 > oo else
                             "같은 방향")
    return out


def daily(d):
    cl = [r["c"] for r in d]
    c, prev = d[-1], d[-2]
    out = {"날짜": c["t"].strftime("%Y-%m-%d"), "종가": c["c"]}
    ma = {n: sma(cl, n) for n in (5, 10, 20, 60, 120, 240)}
    for n, s in ma.items():
        out[f"{n}선"] = r1(s[-1], 0)
    a = [ma[n][-1] for n in (5, 20, 60, 120)]
    out["배열"] = ("정배열(5>20>60>120)" if None not in a and a[0] > a[1] > a[2] > a[3] else
                 "역배열(5<20<60<120)" if None not in a and a[0] < a[1] < a[2] < a[3] else "혼조")
    out["20선 추이(5일)"] = "상승" if ma[20][-1] > ma[20][-6] else "하락"
    out["60선 추이(5일)"] = "상승" if ma[60][-1] > ma[60][-6] else "하락"
    for n in (5, 20, 60):
        out[f"이격도{n}"] = r1(c["c"] / ma[n][-1] * 100)
    out["엔벨로프20±6"] = ("상단 위" if c["c"] > ma[20][-1] * 1.06 else "하단 아래" if c["c"] < ma[20][-1] * 0.94 else "밴드 안")
    out["엔벨로프20±3(20선 근접)"] = abs(c["c"] / ma[20][-1] - 1) <= 0.03
    out["60선 vs 1년선"] = ("데드(60<240)" if ma[240][-1] and ma[60][-1] < ma[240][-1] else "60선 위")
    rs = rsi(cl)
    out["RSI14"] = r1(rs[-1])
    out["최근10일 RSI70 돌파"] = any(x and x >= 70 for x in rs[-10:])
    # RSI 다이버전스(30일): 저점 갱신인데 RSI 저점은 높다
    seg = list(range(len(d) - 30, len(d)))
    i1 = min(seg[:15], key=lambda i: d[i]["l"])
    i2 = min(seg[15:], key=lambda i: d[i]["l"])
    out["RSI 상승다이버전스(30일)"] = bool(d[i2]["l"] < d[i1]["l"] and rs[i2] and rs[i1] and rs[i2] > rs[i1])
    e12, e26 = ema(cl, 12), ema(cl, 26)
    macd = [x - y for x, y in zip(e12, e26)]
    sig = ema(macd, 9)
    out["MACD 오실레이터"] = "0선 위" if macd[-1] - sig[-1] > 0 else "0선 아래"
    # 거래량·거래대금
    v20 = sum(r["v"] for r in d[-21:-1]) / 20
    out["거래량 20일평균 대비(배)"] = r1(c["v"] / v20 if v20 else None)
    amt = [r["v"] * r["c"] / 1e8 for r in d]
    out["추정 거래대금(억)"] = r1(amt[-1], 0)
    yr = d[-250:]
    kmax = max(range(len(yr)), key=lambda i: yr[i]["v"])
    out["1년 최대 거래량일"] = {"날짜": yr[kmax]["t"].strftime("%Y-%m-%d"), "종가": yr[kmax]["c"],
                           "양음": "양봉" if yr[kmax]["c"] > yr[kmax]["o"] else "음봉"}
    out["오늘 캔들"] = candle(c, prev)
    # 신고가의 격 (7-3 [1])
    grade = None
    for n, nm in ((len(d) - 1, "10년(사실상 사상)"), (250, "52주"), (120, "120일"), (60, "60일"), (20, "20일")):
        if len(d) > n + 1 and c["h"] >= max(r["h"] for r in d[-n - 1:-1]):
            grade = nm
            break
    out["신고가 격"] = grade or "없음"
    # 시세 시작점 대비 (7-3 [3]) / 고점 대비
    low120 = min(range(len(d) - 120, len(d)), key=lambda i: d[i]["l"])
    hi60 = max(range(len(d) - 60, len(d)), key=lambda i: d[i]["h"])
    out["120일 저점"] = {"가격": d[low120]["l"], "날짜": d[low120]["t"].strftime("%Y-%m-%d")}
    out["120일 저점 대비(%)"] = r1(pct(c["c"], d[low120]["l"]))
    out["60일 고점"] = {"가격": d[hi60]["h"], "날짜": d[hi60]["t"].strftime("%Y-%m-%d")}
    out["60일 고점 대비(%)"] = r1(pct(c["c"], d[hi60]["h"]))
    # 전고점·전저점 (1-3 PART B)
    ph, pl = pivots(d[-250:], 5)
    base = len(d) - len(d[-250:])
    highs = [d[base + i]["h"] for i in ph]
    lows = [d[base + i]["l"] for i in pl]
    lp = [d[base + i]["l"] for i in pl][-2:]
    out["최근 두 저점"] = [round(x) for x in lp]
    out["최근 두 저점 상승"] = len(lp) == 2 and lp[1] >= lp[0] * 0.99
    out["위 전고점(가까운 순)"] = sorted({round(x) for x in highs if x > c["c"]})[:3]
    out["아래 전저점(가까운 순)"] = sorted({round(x) for x in lows if x < c["c"]}, reverse=True)[:3]
    # 박스 (최근 40일)
    b = d[-40:]
    bh, bl = max(r["h"] for r in b), min(r["l"] for r in b)
    out["40일 박스"] = {"상단": bh, "하단": bl, "중심": (bh + bl) / 2,
                       "위치(%)": r1((c["c"] - bl) / (bh - bl) * 100 if bh > bl else None, 0)}
    rb, ra = round_figures(c["c"])
    out["라운드피겨"] = {"아래": rb, "위": ra}
    # 미메움 갭 (1-13)
    gaps = []
    for i in range(len(d) - 60, len(d)):
        pr, cu = d[i - 1], d[i]
        after = d[i + 1:]
        if cu["l"] > pr["h"]:
            if not after or min(r["l"] for r in after) > pr["h"]:
                gaps.append({"방향": "상승갭", "날짜": cu["t"].strftime("%m-%d"), "하방": pr["h"], "상방": cu["l"]})
        if cu["h"] < pr["l"]:
            if not after or max(r["h"] for r in after) < pr["l"]:
                gaps.append({"방향": "하락갭", "날짜": cu["t"].strftime("%m-%d"), "하방": cu["h"], "상방": pr["l"]})
    out["미메움 갭(60일)"] = gaps[-4:]
    # 매물대 60일·250일 (1-5)
    for n in (60, 250):
        vp = vol_profile(d[-n:])
        if vp:
            sup = [x for x in vp if x["상단"] <= c["c"]]
            res = [x for x in vp if x["하단"] > c["c"]]
            out[f"매물대{n}일 아래"] = (lambda x: f"{x['하단']:,.0f}~{x['상단']:,.0f} ({x['비중']:.0f}%)")(max(sup, key=lambda x: x["비중"])) if sup else "없음(최저 구간)"
            out[f"매물대{n}일 위"] = (lambda x: f"{x['하단']:,.0f}~{x['상단']:,.0f} ({x['비중']:.0f}%)")(max(res, key=lambda x: x["비중"])) if res else "없음(최고 구간)"
    # 일봉 기준봉: 장대양봉(+5%) + 거래량 2배 (2-7, 1-14 §5)
    kb = None
    for i in range(len(d) - 1, len(d) - 61, -1):
        r, p = d[i], d[i - 1]
        va = sum(x["v"] for x in d[i - 20:i]) / 20
        if r["c"] > r["o"] and pct(r["c"], p["c"]) and pct(r["c"], p["c"]) >= 5 and va and r["v"] >= 2 * va:
            kb = r
            break
    if kb:
        mid = (kb["o"] + kb["c"]) / 2
        out["일봉 기준봉"] = {"날짜": kb["t"].strftime("%Y-%m-%d"), "시가": kb["o"], "중심": mid, "저점": kb["l"], "고점": kb["h"],
                          "현재": "고점 위" if c["c"] > kb["h"] else "중심 위" if c["c"] >= mid else "시가 위" if c["c"] >= kb["o"] else "시가 아래"}
    # 음봉 바닥 기준봉 (7-4): 하락 중 음봉 + 거래량 전일비 증가 (40일, 가장 아래)
    cand = [i for i in range(len(d) - 40, len(d))
            if d[i]["c"] < d[i]["o"] and d[i]["v"] > d[i - 1]["v"]]
    if cand:
        k = min(cand, key=lambda i: d[i]["c"])
        out["음봉바닥 기준봉"] = {"날짜": d[k]["t"].strftime("%Y-%m-%d"), "몸통 상방": d[k]["o"],
                             "몸통 하방": d[k]["c"], "몸통(%)": r1(pct(d[k]["o"], d[k]["c"])),
                             "종가 상방 돌파": c["c"] > d[k]["o"] and k < len(d) - 1}
    # 눌림목 거래대금 밴드 (7-2 [2])
    surge = max(range(len(d) - 120, len(d)), key=lambda i: amt[i])
    q0, q1 = max(0, surge - 25), max(0, surge - 5)
    quiet = sum(amt[q0:q1]) / max(1, q1 - q0)
    now5 = sum(amt[-5:]) / 5
    out["눌림목 거래대금"] = {"급등일": d[surge]["t"].strftime("%Y-%m-%d"), "급등일 대금(억)": r1(amt[surge], 0),
                         "조용구간 평균(억)": r1(quiet, 0), "밴드(억)": f"{quiet:,.0f}~{quiet * 2:,.0f}",
                         "최근5일 평균(억)": r1(now5, 0), "밴드 안": quiet <= now5 <= quiet * 2}
    # 7-2 [1] 5봉 전부터 과거 20봉 변동폭
    seg = d[-25:-5]
    out["5봉전 20봉 변동폭(%)"] = r1(pct(max(r["h"] for r in seg), min(r["l"] for r in seg)))
    # 지지 근거 겹침 수 (6-6: 3개 이상)
    return out


def hour60(h):
    if len(h) < 120:
        return {"판정": "데이터 부족"}
    c = h[-1]["c"]
    va = sum(r["v"] for r in h[-140:-1]) / 139
    k = None
    for i in range(len(h) - 1, max(0, len(h) - 70), -1):   # 최근 약 10거래일
        r = h[i]
        if r["c"] > r["o"] and (r["c"] - r["o"]) / r["o"] >= 0.02 and r["v"] >= 2 * va:
            k = i
            break
    if k is None:
        return {"판정": "최근 10거래일 60분봉에 장대양봉+거래량 봉 없음",
                "60분 20선": r1(sma([r["c"] for r in h], 20)[-1], 0),
                "20선 위": c >= sma([r["c"] for r in h], 20)[-1]}
    r = h[k]
    mid = (r["o"] + r["c"]) / 2
    after = h[k + 1:]
    vol_after = sum(x["v"] for x in after) / len(after) if after else None
    state = ("살아 있음(중심 위)" if c >= mid else "단기 시세 종료(중심 이탈)" if c >= r["o"]
             else "큰 시세도 종료(하단 이탈)")
    return {"기준 60분봉": r["t"].strftime("%m-%d %H:%M"), "중심(1차 지지)": r1(mid, 0), "하단(2차 지지)": r1(r["o"], 0),
            "판정": state, "이후 거래량/기준봉": r1(vol_after / r["v"] if vol_after else None, 2),
            "조정 거래량": None if vol_after is None else ("감소(건강)" if vol_after < r["v"] * 0.5 else "많음(위험)")}


def min5(m5):
    if not m5:
        return {"판정": "데이터 없음"}
    last_day = m5[-1]["t"].date()
    day = [r for r in m5 if r["t"].date() == last_day]
    if len(day) < 20:
        return {"판정": "당일 분봉 부족"}
    hi_i = max(range(len(day)), key=lambda i: day[i]["h"])
    lo_i = min(range(len(day)), key=lambda i: day[i]["l"])
    hi, lo, c = day[hi_i]["h"], day[lo_i]["l"], day[-1]["c"]
    q = (c - lo) / (hi - lo) * 100 if hi > lo else None
    tail = day[-12:]
    prev = day[-24:-12]
    late_support = min(r["l"] for r in tail) >= min(r["l"] for r in prev)
    return {"날짜": str(last_day), "당일 고가": hi, "당일 저가": lo, "고저 중 현재 위치(%)": r1(q, 0),
            "4등분 위치": None if q is None else ("3/4 위" if q >= 75 else "1/2~3/4" if q >= 50 else "1/4~1/2" if q >= 25 else "1/4 아래"),
            "고가 시각": day[hi_i]["t"].strftime("%H:%M"), "저가 시각": day[lo_i]["t"].strftime("%H:%M"),
            "장 후반 하방 지지(마지막 1시간 저점≥직전 1시간 저점)": late_support}


def flows(tr):
    if not tr:
        return {"판정": "수급 데이터 없음"}
    def s(k, n): return sum(r[k] for r in tr[-n:])
    avg = lambda k: sum(abs(r[k]) for r in tr[-21:-1]) / 20 if len(tr) > 21 else None
    out = {}
    for k in ("외국인", "기관", "개인"):
        out[f"{k} 당일(주)"] = tr[-1][k]
        out[f"{k} 5일(주)"] = s(k, 5)
        out[f"{k} 20일(주)"] = s(k, 20)
        a = avg(k)
        out[f"{k} 당일/평소"] = r1(abs(tr[-1][k]) / a if a else None)
    out["외국인 보유율"] = tr[-1]["보유율"]
    out["보유율 20일 변화(%p)"] = r1(tr[-1]["보유율"] - tr[-21]["보유율"], 2) if len(tr) > 21 else None
    # 연속 매수/매도 일수 (9-1 §16-1)
    for k in ("외국인", "기관"):
        n, sign = 0, (tr[-1][k] > 0) - (tr[-1][k] < 0)
        for r in reversed(tr):
            if ((r[k] > 0) - (r[k] < 0)) == sign and sign != 0:
                n += 1
            else:
                break
        out[f"{k} 연속"] = f"{n}일 {'순매수' if sign > 0 else '순매도'}" if sign else "보합"
    return out


# ───────────────────────── 9장: 시장 ─────────────────────────
def index_state(sym, name):
    d, _ = yahoo(sym, "1d", "2y")
    w, _ = yahoo(sym, "1wk", "10y")
    m, _ = yahoo(sym, "1mo", "max")
    if len(d) < 130:
        return {"이름": name, "판정": "데이터 부족"}
    cl = [r["c"] for r in d]
    c = cl[-1]
    ma = {n: sma(cl, n)[-1] for n in (5, 20, 60, 120)}
    ma20p = sma(cl, 20)[-6]
    hi250 = max(r["h"] for r in d[-250:])
    hi20 = max(r["h"] for r in d[-20:])
    big_down = [pct(d[i]["c"], d[i - 1]["c"]) for i in range(len(d) - 5, len(d))]
    out = {"이름": name, "날짜": d[-1]["t"].strftime("%Y-%m-%d"), "종가": r1(c, 2),
           "등락률": r1(pct(c, cl[-2]), 2), "5선 위": c >= ma[5], "20선 위": c >= ma[20],
           "20선 추이": "상승" if ma[20] > ma20p else "하락",
           "이격도5": r1(c / ma[5] * 100), "이격도20": r1(c / ma[20] * 100),
           "60선": r1(ma[60], 0), "120선": r1(ma[120], 0),
           "52주 고점 대비(%)": r1(pct(c, hi250)), "20일 고점 대비(%)": r1(pct(c, hi20)),
           "최근5일 최대 하락(%)": r1(min(big_down), 2), "RSI14": r1(rsi(cl)[-1])}
    if len(w) > 130:
        wc = [r["c"] for r in w]
        wm = {n: sma(wc, n)[-1] for n in (10, 13, 20, 60, 120)}
        out["주봉"] = {f"{n}주선": r1(v, 0) for n, v in wm.items()}
        out["주봉 10·20"] = "골든" if wm[10] >= wm[20] else "데드"
        out["주봉 이탈선"] = [n for n in (13, 20, 60, 120) if wc[-1] < wm[n]]
    if len(m) > 125:
        mc = [r["c"] for r in m]
        mm = {n: sma(mc, n)[-1] for n in (18, 20, 60, 120)}
        out["월봉"] = {f"{n}월선": r1(v, 0) for n, v in mm.items()}
        out["월봉 이탈선"] = [n for n in (18, 20, 60, 120) if mc[-1] < mm[n]]
    return out


def last_change(sym):
    d, meta = yahoo(sym, "1d", "1mo")
    if len(d) < 6:
        return None
    cl = [r["c"] for r in d]
    return {"종가": r1(cl[-1], 2), "등락률": r1(pct(cl[-1], cl[-2]), 2),
            "5선 위": cl[-1] >= sum(cl[-5:]) / 5, "날짜": d[-1]["t"].strftime("%m-%d %H:%M")}


# 9-4 §0-2 한 장 지도 + PART B 통계(S&P500 1950~2023 월평균, 하반기·1월만 수치가 있다)
SEASON = {1: "▲ 1월 효과 (+1.2%)", 2: "◆ 변동성 — 4분기 실적·연말 랠리 차익", 3: "▲ 봄 — 1분기 실적 기대",
          4: "▲ 봄 — 1분기 실적 기대", 5: "▼ '파는 계절' — 3·4월 시세 차익", 6: "▲ 서머랠리 시작",
          7: "▲ 서머랠리 (+1.4%)", 8: "◆ 변동성 — 상승폭 축소 (+0.6%)", 9: "▼ 가을 약세 (-1.1%)",
          10: "▼ 가을 약세 — 통계상 보합", 11: "▲ 연말 랠리 (+1.4%)", 12: "▲ 연말 랠리 (+1.3%)"}

# 4-3 제안 — 기본 스타일은 단기스윙, 장세(9-2)가 열어 주는 매매법만 판정에 올린다
기본스타일 = "단기스윙 (일봉 20선 + 주봉 확인)"
장세스위치 = {
    "대세 상승": ["신고가·전고점 돌파 매매", "눌림목 매매", "단기 스윙 (기본기)"],
    "횡보": ["박스권 매매", "음봉 바닥 기법", "단기 스윙 (기본기)"],
    "대세 하락": ["음봉 바닥 기법"],
    "폭락 진행": ["기술적 반등 매매"],
    "판정불가": [],
}
현금비중 = {"대세 상승": "20~30%", "횡보": "약 50%", "대세 하락": "60~70%",
            "폭락 진행": "100% 지향 + 기술적 반등만", "판정불가": "-"}


def market(adr=None):
    ks = index_state("^KS11", "코스피")
    kq = index_state("^KQ11", "코스닥")
    us = {n: last_change(s) for s, n in (("^IXIC", "나스닥"), ("^GSPC", "S&P500"), ("^SOX", "필라델피아 반도체"),
                                          ("ES=F", "S&P 선물"), ("NQ=F", "나스닥 선물"))}
    mac = {n: last_change(s) for s, n in (("^VIX", "VIX"), ("KRW=X", "원달러"), ("^TNX", "미 10년물"),
                                           ("CL=F", "WTI"), ("GC=F", "금"), ("DX-Y.NYB", "달러인덱스"))}
    vw, _ = yahoo("^VIX", "1wk", "1y")
    vix_w = vw[-1]["c"] if vw else None
    # 장세 판정 (9-2) — 지수 하나라도 폭락이면 폭락
    def regime(x):
        if x.get("판정") == "데이터 부족":
            return "판정불가"
        if (x["20일 고점 대비(%)"] <= -12 or x["최근5일 최대 하락(%)"] <= -5) and not x["5선 위"]:
            return "폭락 진행"
        if not x["20선 위"] and x["20선 추이"] == "하락" and x.get("주봉 10·20") == "데드":
            return "대세 하락"
        if x["20선 위"] and x["20선 추이"] == "상승" and x.get("주봉 10·20") == "골든" and 20 not in x.get("월봉 이탈선", []):
            return "대세 상승"
        return "횡보"
    rg = {"코스피": regime(ks), "코스닥": regime(kq)}
    order = ["폭락 진행", "대세 하락", "횡보", "대세 상승", "판정불가"]
    worst = min(rg.values(), key=lambda v: order.index(v))
    cash = 현금비중[worst]
    # 9-2 §19-1 비중 매트릭스 — 개별주 상태는 시장폭(ADR)으로 대신한다
    idx_good = worst == "대세 상승"
    adr_v = (adr or {}).get("ADR")
    stock_good = None if adr_v is None else adr_v >= 100
    if stock_good is None:
        matrix = "개별주 판정불가(ADR 없음)"
    elif idx_good and stock_good:
        matrix = "지수 좋음 · 개별주 좋음 → 주식 80~90%"
    elif not idx_good and stock_good:
        matrix = "지수 우하향 · 개별주 괜찮음 → 주식 30~50%"
    elif not idx_good:
        matrix = "지수 우하향 · 개별주 나쁨 → 주식 0~20%"
    else:
        matrix = "지수 좋음 · 개별주 약함 → 비중 축소"
    vb = ("공포 — 적극(50↑)" if vix_w and vix_w >= 50 else "공포 — 2차(40↑)" if vix_w and vix_w >= 40 else
          "공포 — 1차(30↑)" if vix_w and vix_w >= 30 else "평균(20~30)" if vix_w and vix_w >= 20 else
          "탐욕(20↓)" if vix_w else "판정불가")
    mon = datetime.now(KST).month
    return {"코스피": ks, "코스닥": kq, "미국": us, "매크로": mac, "VIX 주봉 종가": r1(vix_w, 2), "VIX 구간(4-6, 주봉)": vb,
            "장세(9-2)": rg, "가장 나쁜 장세": worst, "현금 비중(9-2)": cash,
            "시장폭": adr or {}, "비중 매트릭스(9-2 §19-1)": matrix,
            "기본 스타일": 기본스타일, "열린 매매법": 장세스위치[worst],
            "문턱 표기": "폭락 판정(20일 고점 -12%·5일 내 -5%)은 교재에 수치가 없어 정한 값이다",
            "계절성(9-4, S&P 1950~2023 월평균)": f"{mon}월 {SEASON[mon]} — 법칙이 아니라 성향",
            "캘린더(FOMC·CPI·고용·실적)": "출처 미연결 — 수동 확인 필요"}


# ───────────────────────── 6~7장: 매매법 판정 ─────────────────────────
def C(name, ok, ev=""):
    return {"조건": name, "충족": ok, "근거": ev}


def methods(D, W, M, H, F, M5, mk, 시총억):
    c = D["종가"]
    ks = mk["코스피"]
    idx5 = ks.get("5선 위")
    idx20 = ks.get("20선 위")
    worst = mk["가장 나쁜 장세"]
    us_fut = mk["미국"].get("나스닥 선물") or {}
    kb = D.get("일봉 기준봉")
    res = []

    def add(name, src, style, frame, conds, plan, expect, realtime=False):
        known = [x for x in conds if x["충족"] is not None]
        ok = sum(1 for x in known if x["충족"])
        fail = [x["조건"] for x in known if not x["충족"]]
        verdict = ("판정불가(장중 데이터 필요)" if realtime and not known else
                   "적합" if known and not fail else
                   "조건부(미충족 %d)" % len(fail) if len(fail) <= 1 and ok >= 2 else "부적합")
        res.append({"매매법": name, "교재": src, "스타일": style, "프레임": frame, "판정": verdict,
                    "충족": f"{ok}/{len(known)}", "미충족": fail,
                    "판정불가 항목": [x["조건"] for x in conds if x["충족"] is None],
                    "조건": conds, "계획(8장 틀)": plan, "예상 결과": expect})

    low_idx = D["아래 전저점(가까운 순)"]
    hi_idx = D["위 전고점(가까운 순)"]
    near_res = hi_idx[0] if hi_idx else None
    near_sup = low_idx[0] if low_idx else None
    ma5, ma20, ma60 = D["5선"], D["20선"], D["60선"]

    # 6-6 기술적 반등
    sup_stack = sum([
        bool(near_sup and abs(pct(c, near_sup)) <= 5),
        bool(D["라운드피겨"]["아래"] and pct(c, D["라운드피겨"]["아래"]) <= 5),
        "없음" not in D.get("매물대250일 아래", "없음"),
        any(g["방향"] == "상승갭" and g["하방"] <= c for g in D["미메움 갭(60일)"]),
        W.get("주봉 기준봉", {}).get("현재가 위치") in ("저점 위", "중심 위"),
    ])
    stop66 = min(ma5, c * 0.97) if ma5 else c * 0.97
    tgt66 = sorted(x for x in (ma20, near_res) if x and x > c)
    add("기술적 반등 매매", "6-6", "단타~단기", "일봉+분봉",
        [C("지수 과도한 폭락", ks.get("최근5일 최대 하락(%)", 0) <= -3 or ks.get("20일 고점 대비(%)", 0) <= -10,
           f"코스피 20일 고점 대비 {ks.get('20일 고점 대비(%)')}% · 5일 최대 {ks.get('최근5일 최대 하락(%)')}%"),
         C("지수 5일선 회복", idx5, f"코스피 이격도5 {ks.get('이격도5')}"),
         C("외국인 매도세 멈춤", None if not F.get("외국인 당일(주)") else F["외국인 당일(주)"] >= 0,
           f"외국인 당일 {F.get('외국인 당일(주)')}주 · {F.get('외국인 연속')}"),
         C("하락 추세 한가운데가 아님(5일선 위로 올라섬)", c >= ma5, f"종가 {c:,.0f} / 5선 {ma5:,.0f}"),
         C("지지 근거 3겹 이상", sup_stack >= 3, f"겹친 근거 {sup_stack}개"),
         C("V자 추격 아님 — 지지대에서 단봉·아래꼬리", any(t in D["오늘 캔들"]["형태"] for t in ("도지/단봉", "긴 아래꼬리")),
           "오늘 " + "/".join(D["오늘 캔들"]["형태"]))],
        {"진입": "지지대에서 단봉·아래꼬리 확인 후, 5일선 회복 시", "손절": f"5선 종가 이탈 또는 -3% → {stop66:,.0f}",
         "목표": " / ".join(f"{x:,.0f}" for x in tgt66) or "20선",
         "대응": "짧게 본다. 저항에서 비중 축소, 기술적 반등 고점 재돌파 시에만 본격 반등으로 본다"},
        {"교재 기대": "1차 목표 20선·전저점·위쪽 갭까지 — '짧게'", "손익비": r1((tgt66[0] - c) / (c - stop66), 1) if tgt66 and c > stop66 else None,
         "실패 시": "5선 이탈 = -3% 안쪽 손절. 폭락장에서는 반등이 짧고 재하락이 잦다"})

    # 7-1 종가 매매
    tail_ok = "긴 윗꼬리" not in D["오늘 캔들"]["형태"]
    gap5, gap20 = abs(D["이격도5"] - 100), abs(D["이격도20"] - 100)
    add("종가 매매", "7-1", "종가(1박)", "일봉·주봉+분봉+미국 선물",
        [C("① 긴 윗꼬리 없음", tail_ok, "/".join(D["오늘 캔들"]["형태"])),
         C("② 가격 이동이 자유로운 자리(박스 안·전고점 아래·매물대 가벼움)",
           D["40일 박스"]["위치(%)"] is not None and 20 <= D["40일 박스"]["위치(%)"] <= 80, f"40일 박스 위치 {D['40일 박스']['위치(%)']}%"),
         C("② 5·20선 이격 1~2% 이내", gap5 <= 2 and gap20 <= 2, f"이격도5 {D['이격도5']} · 이격도20 {D['이격도20']}"),
         C("② 일봉·주봉 상승 관성", D["20선 추이(5일)"] == "상승" and W.get("10·20주 상태", "").startswith("골든"),
           f"20선 {D['20선 추이(5일)']} · 주봉 {W.get('10·20주 상태')}"),
         C("③ 분봉 장 후반 하방 지지", M5.get("장 후반 하방 지지(마지막 1시간 저점≥직전 1시간 저점)"), f"당일 4등분 {M5.get('4등분 위치')}"),
         C("④ 수급 — 평소와 다른 매도 없음", None if F.get("외국인 당일/평소") is None else not (F["외국인 당일(주)"] < 0 and F["외국인 당일/평소"] >= 2),
           f"외국인 당일/평소 {F.get('외국인 당일/평소')}배"),
         C("⑤ 지수 급락 자리 아님", idx5, f"코스피 5선 위 {idx5}"),
         C("⑤ 미국 선물 마이너스 아님", None if not us_fut else us_fut["등락률"] >= 0, f"나스닥 선물 {us_fut.get('등락률')}%")],
        {"진입": "14:00 후보 → 15:20 전후", "손절": f"장대저점/5일선/-2~3% → {max(x for x in ((kb or {}).get('저점'), ma5, c * 0.97) if x and x < c):,.0f}",
         "목표": f"1차 전고점·박스상단 {near_res or D['40일 박스']['상단']:,.0f}", "대응": "다음 날 오전에 끝낸다. 저항마다 분할 매도"},
        {"교재 기대": "다음 날 아침 3~5%", "손익비": None, "실패 시": "미국 선물이 빠지면 갭하락으로 시작 — 교재는 그런 날 아예 하지 않는다"})

    # 7-2 눌림목
    nb = D["눌림목 거래대금"]
    add("눌림목 매매", "7-2", "단기(20선)/중기(60선)/장기(120선)", "일봉",
        [C("[0] 지수 상승 추세", idx20 and ks.get("20선 추이") == "상승", f"코스피 20선 위 {idx20}·{ks.get('20선 추이')}"),
         C("[1] 정배열 5>20>60", D["배열"].startswith("정배열") or (ma5 > ma20 > ma60), D["배열"]),
         C("[1] 5봉전 20봉 변동폭 10%↑", (D["5봉전 20봉 변동폭(%)"] or 0) >= 10, f"{D['5봉전 20봉 변동폭(%)']}%"),
         C("[2] 거래대금이 조용구간 밴드 안", nb["밴드 안"], f"최근5일 {nb['최근5일 평균(억)']}억 / 밴드 {nb['밴드(억)']}억"),
         C("[5] 60선이 1년선 위(데드 아님)", D["60선 vs 1년선"] == "60선 위", D["60선 vs 1년선"]),
         C("[7] 오늘 등락률 5% 이하", abs(D["오늘 캔들"]["등락률"] or 0) <= 5, f"{D['오늘 캔들']['등락률']}%")],
        {"진입": "방어선 2회 이상 지켜낸 뒤 트리거(십자도지 상방·직전 음봉 고점 돌파)", "손절": f"방어선(1차 변곡점) 이탈 → {near_sup or 0:,.0f}",
         "목표": "미리 정한 목표 수익률", "대응": "변곡점 갱신 시 손절선도 올린다"},
        {"교재 기대": "20선 눌림은 단기 — 일봉 파동 7~15%", "손익비": None, "실패 시": "하락 추세면 '매매 중단'이 교재 [0]"})

    # 7-3 신고가·전고점 돌파
    add("신고가·전고점 돌파 매매", "7-3", "단기 (중장기면 금지)", "일봉",
        [C("[0] 지수 폭락 중 아님", worst != "폭락 진행", worst),
         C("[1] 신고가 격 있음(오랜만의 고점)", D["신고가 격"] != "없음", D["신고가 격"]),
         C("[3] 20선과 가까움(총알이 총에)", gap20 <= 5, f"이격도20 {D['이격도20']}"),
         C("[3] 이번 시세 100% 미만", (D["120일 저점 대비(%)"] or 0) < 100, f"120일 저점 대비 {D['120일 저점 대비(%)']}%"),
         C("[3] 시총 충분(휩쏘 어려움)", None if 시총억 is None else 시총억 >= 5000, f"{시총억:,.0f}억" if 시총억 else "-")],
        {"진입": "④ 전고점+20선 교차 자리 > ③ 20선 반등 > ① 돌파 직전 (② 돌파 순간 금지)", "손절": "돌려세우고 만든 첫 저점",
         "목표": "슈팅 시 일부 익절", "대응": "흔한 조정폭 -15~-25%"},
        {"교재 기대": "확률 순서 4>3>1>2", "손익비": None, "실패 시": "첫 저점 이탈 = -3%인지 -70%인지 모른다 → 무조건 손절"})

    # 7-4 음봉 바닥
    ub = D.get("음봉바닥 기준봉") or {}
    stop74 = ub.get("몸통 하방")
    add("음봉 바닥 기법", "7-4", "단기 스윙", "일봉",
        [C("[1] 하락 중 + 고점 대비 충분히 하락", (D["60일 고점 대비(%)"] or 0) <= -15, f"60일 고점 대비 {D['60일 고점 대비(%)']}%"),
         C("[2] 음봉+거래량 양봉 기준봉 있음", bool(ub), f"{ub.get('날짜')} 몸통 {ub.get('몸통 하방', 0):,.0f}~{ub.get('몸통 상방', 0):,.0f}" if ub else "없음"),
         C("[4] 종가가 기준봉 상방 돌파", ub.get("종가 상방 돌파") if ub else False, f"종가 {c:,.0f}"),
         C("[5] 지수 반등 가능성(5선 회복)", idx5, f"코스피 5선 위 {idx5}"),
         C("[5] 실적 연속 적자 아님", None, "재무 데이터 미연결")],
        {"진입": "종가가 기준봉 몸통 상방 돌파 시에만", "손절": f"기준봉 저점(몸통 6~7%↑면 중심) → {stop74 or 0:,.0f}",
         "목표": "직전 고점대/갭 상단, 20일선 근방 1차 분할", "대응": "3~7종목 분산, 2종목 실패 전제"},
        {"교재 기대": "1차 목표 직전 고점대", "손익비": None, "실패 시": "기준봉 이탈 — 교재는 '이 기법 하나로 승률 80~90% 기대 금지'"})

    # 7-5 단기 스윙 기본
    add("단기 스윙 (기본기)", "7-5 / 7-5b", "단기스윙 3~4일~2주", "일봉 20선 (+주봉·월봉 확인)",
        [C("[0] 지수 상승 추세", idx20 and ks.get("20선 추이") == "상승", f"코스피 20선 위 {idx20}"),
         C("7-5b 지수 5일선 위", idx5, f"코스피 이격도5 {ks.get('이격도5')}"),
         C("[1] 주봉·월봉 우상향(월봉 20월선 위)", M.get("20월선 위"), f"20월선 {M.get('20월선')}"),
         C("[1] 정배열 + 20선 위 + 5선 위", D["배열"].startswith("정배열") and c >= ma20 and c >= ma5, f"{D['배열']}"),
         C("[3] 20선 이격 10% 미만", gap20 < 10, f"이격도20 {D['이격도20']}"),
         C("[2] 지지 근거 2개 이상", sup_stack >= 2, f"{sup_stack}개")],
        {"진입": "이평선과 가까울 때, 1차 5~10% 비중", "손절": f"20선/5선/박스 하단 이탈 → 손절폭 5~7%",
         "목표": "1차 가장 가까운 저항, 일봉 파동 7~15%(평균 10%)", "대응": "5선 올라오면 매도선도 올림. 지수 5선 이탈 → 신규 중단"},
        {"교재 기대": "월 5~10% (10-5)", "손익비": "목표 10% / 손절 5~7% ≈ 1.4~2", "실패 시": "비중이 실패의 진짜 원인 — 확신 비중 금지"})

    # 7-6 중기 스윙
    dd = D["60일 고점 대비(%)"] or 0
    add("중기 스윙", "7-6 [4][5]", "중기 1~4달", "주봉",
        [C("[4] 고점 대비 -30% 전후 조정", dd <= -25, f"60일 고점 대비 {dd}%"),
         C("[4] 하락 추세선 돌파(바닥 확인)", None, "추세선 작도 자동화 안 됨 — 저점 상향으로 대체"),
         C("[4] 저점을 옆·위로 올림(최근 두 저점)", D["최근 두 저점 상승"], f"최근 저점 {D['최근 두 저점']}"),
         C("[6] 전체 시장 상승장", worst == "대세 상승", worst),
         C("주봉 10주선 지지(결정의 시간)", (W.get("10주선 이격(%)") or -99) >= -3, f"10주선 이격 {W.get('10주선 이격(%)')}%")],
        {"진입": "추세 전환 확인 후 분할 — 20선 1주 / 60선 2주 / 120·200선 3주", "손절": "추세 전환 전 '어디까지 내려갈지 모른다' → 진입 보류가 손절",
         "목표": "무릎 = 추세 전환 → 쉬어줌 → 고점 돌파", "대응": "패닉장 대비 킵 현금 (예: 50%)"},
        {"교재 기대": "1~2달 큰 시세 하나", "손익비": None, "실패 시": "추세 전환 전 진입 = 바닥 예측 = 교재 금지"})

    # 1-11 박스권 (40일 박스 + 주봉 기준봉)
    bx = D["40일 박스"]
    add("박스권 매매", "1-11", "단기스윙", "일봉(주봉으로 찾는다)",
        [C("박스 하단 근방(위치 25% 이하)", bx["위치(%)"] is not None and bx["위치(%)"] <= 25, f"40일 박스 위치 {bx['위치(%)']}%"),
         C("하단 지지 확인(아래꼬리·단봉)", any(t in D["오늘 캔들"]["형태"] for t in ("도지/단봉", "긴 아래꼬리")), "/".join(D["오늘 캔들"]["형태"])),
         C("박스가 횡보 박스(하락 추세 아님)", D["20선 추이(5일)"] == "상승" or abs(D["이격도20"] - 100) <= 5, f"20선 {D['20선 추이(5일)']}·이격도20 {D['이격도20']}"),
         C("지수 폭락 중 아님", worst != "폭락 진행", worst)],
        {"진입": f"하단 {bx['하단']:,.0f} 근방에서 지지 확인 후", "손절": f"박스 하단 이탈 {bx['하단'] * 0.97:,.0f}",
         "목표": f"절반은 중심 {bx['중심']:,.0f}, 나머지 상단 {bx['상단']:,.0f}", "대응": "예외를 많이 만들지 않는다. 이탈해도 버리지 않고 관심종목 유지"},
        {"교재 기대": f"하단→상단 {pct(bx['상단'], bx['하단']):.0f}% (진입 전에 계산)", "손익비": r1((bx['중심'] - c) / (c - bx['하단'] * 0.97), 1) if bx['하단'] * 0.97 < c < bx['중심'] else None,
         "실패 시": "박스 이탈 — 아래 박스 하단까지 열린다 (1-3 4층 모형)"})

    # 중장기 (10-3 §9, 7-6 [2][3], 8-6 모델③)
    add("중장기 (월봉 기준)", "10-3 §9 · 7-6 [2][3] · 8-6", "중장기 5~30년", "월봉 60·120월선",
        [C("월봉 120월선 위(이탈한 적 없으면 보유)", M.get("120월선 위"), f"120월선 {M.get('120월선')}"),
         C("월봉 60월선 위", M.get("60월선 위"), f"60월선 {M.get('60월선')}"),
         C("월봉 박스 하단 근방('좋은 회사가 쌀 때')", M.get("월봉 박스") == "하단", f"36개월 박스 {M.get('월봉 박스')} ({M.get('36개월 박스 위치(%)')}%)"),
         C("신고가·우상향 중 아님", D["신고가 격"] == "없음", D["신고가 격"]),
         C("월봉 저점 대비 초급등 아님(+300% 미만, 1-14·8-5)", (M.get("저점 대비(%)") or 0) < 300, f"24개월 저점 대비 {M.get('저점 대비(%)')}%"),
         C("1등 회사·재무(ROE 15%↑ 등)", None, "재무 데이터 미연결"),
         C("코스피 월봉 60·120월선 동시 이탈 아님", not ({60, 120} <= set(ks.get("월봉 이탈선", []))), f"코스피 월봉 이탈선 {ks.get('월봉 이탈선')}")],
        {"진입": "3개월+ 분할, 종목 비중 상한 10~20%", "손절": "가격이 아니라 사실(횡령·적자 지속·섹터 소멸)",
         "목표": "연 20% 내외 (10-5)", "대응": "중장기 계좌 분리, 매일 보지 않는다"},
        {"교재 기대": "연 20%", "손익비": None, "실패 시": "-50% 경로를 미리 가격으로 적는다 (8-6 모델③)"})

    # 6-5 상한가·상따 유형2 (전일 급등주에만 의미)
    if (D["오늘 캔들"]["등락률"] or 0) >= 15:
        add("상한가 다음 날 매수 (유형 2)", "6-5", "단타", "일봉+분봉",
            [C("① 이슈", None, "뉴스 판독 필요(엔진 뉴스 모듈)"),
             C("② 거래대금 이상치", (D["거래량 20일평균 대비(배)"] or 0) >= 5, f"거래량 {D['거래량 20일평균 대비(배)']}배"),
             C("③ 전고점 돌파", D["신고가 격"] != "없음", D["신고가 격"]),
             C("④ 라운드피겨 돌파", D["라운드피겨"]["아래"] is not None and D["오늘 캔들"]["등락률"] and
               c >= D["라운드피겨"]["아래"] > c / (1 + D["오늘 캔들"]["등락률"] / 100), f"아래 라운드 {D['라운드피겨']['아래']}"),
             C("20선 이격 10% 이하(초보 기준)", D["이격도20"] <= 110, f"이격도20 {D['이격도20']}"),
             C("지수 폭락 아님", worst != "폭락 진행", worst)],
            {"진입": "아침 급등 추격 금지, 1·2·3차 가이드선까지 기다림", "손절": "-3% (망설임 없이)",
             "목표": "가이드 저항마다 분할", "대응": "추세 이탈에서 판다. 상한가 욕심 금지"},
            {"교재 기대": "손익비 1:3 이상일 때만", "손익비": None, "실패 시": "갭하락 출발 시 -3% 즉시"})

    # 초단타·오후·시초가 — 장중 실시간
    for nm, src in (("시초가 매매", "6-2"), ("초단타·스캘핑", "6-4"), ("오후 단타", "6-7"), ("장중 종목 선정 단타", "6-3")):
        add(nm, src, "단타(당일)", "1·3·5분봉 + 호가창",
            [C("지수 3분봉 20선 위", None, "장중 실시간"), C("호가창 받쳐줌", None, "호가 데이터 없음"),
             C("9:30 이전 매수 아님", None, "장중"), C("일봉 위치(5선 근접·20선 위)", c >= ma20 and abs(D["이격도5"] - 100) <= 3,
                                                      f"이격도5 {D['이격도5']} · 20선 위 {c >= ma20}")],
            {"진입": "다음 날 장중 조건으로만", "손절": "-3% 이내 / 타점 이탈", "목표": "1~2% 일부, 하루 1%", "대응": "하루 3종목, 9:30 전 매수 금지"},
            {"교재 기대": "하루 1% (10-5)", "손익비": None, "실패 시": "-3% 즉시"}, realtime=True)
    return res


# ───────────────────────── 8장(보유자) · 10장(결론) ─────────────────────────
def holder_lines(d):
    """8-5: 하락 직전의 '한 시세'를 찾아 저점·중심·고점 3선. 손실이 -20% 넘으면 '더 큰 시세'로 다시 그린다.
    작은 시세 = 최근 60일 고점과 그 앞 60일의 저점 / 큰 시세 = 최근 250일 고점과 그 앞 120일의 저점."""
    def swing(look, before):
        n = len(d)
        pk = max(range(n - look, n), key=lambda i: d[i]["h"])
        if look == 60:   # 직전 스윙 = 현재가보다 15% 이상 높은 가장 최근의 고점 피벗 (창 가장자리 회피)
            ph, _ = pivots(d[-120:], 5)
            cand = [n - 120 + i for i in ph if d[n - 120 + i]["h"] >= d[-1]["c"] * 1.15]
            if cand:
                pk = cand[-1]
        st = min(range(max(0, pk - before), pk + 1), key=lambda i: d[i]["l"])
        lo, hi = d[st]["l"], d[pk]["h"]
        return {"시세": f"{d[st]['t']:%y-%m-%d} {lo:,.0f} → {d[pk]['t']:%y-%m-%d} {hi:,.0f}",
                "1차선(시세 저점)": round(lo), "2차선(시세 중심, 핵심)": round((lo + hi) / 2), "3차선(시세 고점)": round(hi)}
    return {"작은 시세(직전 스윙)": swing(60, 60), "큰 시세(-20% 넘게 물렸으면)": swing(250, 120)}


def tb_wait(st):
    return next((m["미충족"] for m in st["매매법"] if m["매매법"] == "기술적 반등 매매"), [])


def conclude(st, mk):
    D, M = st["일봉"], st["월봉"]
    c = D["종가"]
    ks = mk["코스피"]
    worst = mk["가장 나쁜 장세"]
    gates = []
    if worst == "폭락 진행":
        gates.append("9-2: 폭락 진행 → 현금 100% 지향, 신규는 기술적 반등(6-6)만")
    elif worst == "대세 하락":
        gates.append("9-2: 대세 하락 → 현금 60~70%")
    if not ks.get("5선 위"):
        gates.append("9-1·7-5b·8-5: 지수 5일선 아래 → 신규 진입·추가 매수(물타기) 금지")
    if not ks.get("20선 위"):
        gates.append("9-1 §5: 지수 20선 이탈 → 단기 계좌는 비었거나 거의 줄였어야 정상")
    opened = mk["열린 매매법"]
    ok = [m["매매법"] for m in st["매매법"] if m["판정"] == "적합" and m["매매법"] in opened]
    ok_closed = [m["매매법"] for m in st["매매법"] if m["판정"] == "적합" and m["매매법"] not in opened
                 and not m["매매법"].startswith("중장기")]
    near = [m["매매법"] + f"({m['충족']})" for m in st["매매법"] if m["판정"].startswith("조건부")]
    H = holder_lines(st["_d"])
    pos = {}
    pos["단타"] = ("신규 금지" if gates else "장중 조건 확인") + " — 6-2·6-3·6-4·6-7 은 장중 실시간 조건(지수 3분봉 20선·호가창)이 핵심이라 일일 보고서로는 '내일 볼 조건'만 준다"
    pos["단기스윙"] = "신규 금지 (지수 5선·20선 아래, 7-5 [0] '이것이 틀리면 아래 전부 무효')" if gates else ("적합: " + ", ".join(ok) if ok else "대기")
    pos["중기스윙"] = "대기 — 7-6 [4] 추세 전환(하락 추세선 돌파·저점 상향) 확인 전 진입 = 바닥 예측"
    lt = []
    lt.append(f"월봉 120월선 {M.get('120월선'):,.0f} {'위' if M.get('120월선 위') else '아래'} · 60월선 {'위' if M.get('60월선 위') else '아래'} → " +
              ("보유자는 '이탈할 때까지 보유'(10-3 §9)" if M.get("120월선 위") and M.get("60월선 위") else "보유 근거 약함"))
    if (M.get("저점 대비(%)") or 0) >= 300:
        lt.append(f"24개월 저점 대비 +{M['저점 대비(%)']:.0f}% = 초급등 범주 → 신규 중장기는 '좋은 회사가 쌀 때'(월봉 박스 하단·18/20월선 {M['18월선']:,.0f}/{M['20월선']:,.0f})까지 대기 (1-14·8-5·7-6 [3])")
    vb = mk["VIX 구간(4-6, 주봉)"]
    lt.append(f"VIX 주봉 {mk['VIX 주봉 종가']} = {vb} → 4-6 분할매수 신호(30↑) 아님. 단, VIX는 S&P 기준이라 이번 하락처럼 국내만 무너질 때는 신호가 늦거나 안 나온다")
    pos["중장기"] = " / ".join(lt)
    # 기술적 반등 대기 조건
    tb = next(m for m in st["매매법"] if m["매매법"] == "기술적 반등 매매")
    if ok:
        line = f"{', '.join(ok)} 자리 — 계획표대로 분할 진입 검토"
    elif gates:
        line = f"신규 금지 · {worst} — 기다릴 조건: {', '.join(tb_wait(st)[:3]) or '없음'}"
    else:
        line = "오늘은 적합한 자리가 없다 — 관심종목 유지"
    return {"한 줄": line, "9장 게이트": gates or ["통과"], "적합 매매법": ok or ["없음"],
            "적합하지만 장세가 닫은 매매법": ok_closed or ["없음"], "조건부": near or ["없음"],
            "포지션별 결론": pos,
            "유일하게 열린 문(6-6 기술적 반등) — 기다릴 조건": tb["미충족"],
            "보유자 대응(8-5 가이드 3선)": H,
            "보유자 현재 위치(작은 시세 기준)": (lambda h: "1차선 아래 — 반등 시 1차선에서 30~50% 매도" if c < h["1차선(시세 저점)"] else
                           "1~2차선 사이 — 1차선 이탈은 추가 하락 신호, 반등 시 2차선(중심)이 핵심 매도선" if c < h["2차선(시세 중심, 핵심)"] else
                           "2차선 위")(H["작은 시세(직전 스윙)"]),
            "10-5 목표 상한": "단타 하루 1% / 스윙 월 5~10% / 중장기 연 20% — 이보다 큰 목표가는 교재 기준 '허황'",
            "8-1 물타기 판정식": "(첫 매수가−평단)÷(첫 매수가−현재가) < 0.4 이면 물타기 — 지금은 8-5 허용 4조건 중 '지수 5선 회복'부터 미충족"}


# ───────────────────────── 실행 ─────────────────────────
def analyze(code, name, 시총억, mk):
    S = load_stock(code)
    if not S:
        return {"이름": name, "코드": code, "상태": "시세를 받지 못했다"}
    D = daily(S["d"])
    W = weekly(S["w"])
    M = monthly(S["m"])
    H = hour60(S["h60"])
    M5 = min5(S["m5"])
    F = flows(naver_trend(code, 60))
    ms = methods(D, W, M, H, F, M5, mk, 시총억)
    con = conclude({"_d": S["d"], "일봉": D, "월봉": M, "매매법": ms}, mk)
    prev = S["d"][-2]["c"]
    return {"이름": name, "코드": code, "심볼": S["sym"], "현재가": D["종가"],
            "등락률": r1(pct(D["종가"], prev), 2), "10장 결론": con,
            "0장 프레임": {"월봉": len(S["m"]), "주봉": len(S["w"]), "일봉": len(S["d"]),
                        "60분봉": len(S["h60"]), "5분봉": len(S["m5"])},
            "월봉": M, "주봉": W, "일봉": D, "60분봉": H, "5분봉(당일)": M5, "수급": F, "매매법": ms}


def build(payload: dict, date: str) -> dict:
    """심층분석과 같은 대상(watchlist + 당일 대장주)을 교재 순서로 다시 본다."""
    mk = market(payload.get("adr"))
    targets = []
    for s in ((payload.get("심층분석") or {}).get("종목") or []):
        if s.get("코드") and not s.get("상태"):
            targets.append((s["코드"], s["이름"], s.get("시총(억)")))
    out = []
    for code, name, cap in targets:
        try:
            out.append(analyze(code, name, cap, mk))
        except Exception as exc:
            out.append({"이름": name, "코드": code, "상태": f"분석 실패: {type(exc).__name__}: {exc}"})
    return {"기준일": date, "생성시각": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
            "설계": "rulebook/교재적용체계.md", "9장 시장": mk, "종목": out}


if __name__ == "__main__":
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "data", "latest.json"), encoding="utf-8") as fh:
        pl = json.load(fh)
    res = build(pl, pl.get("거래일", ""))
    print(json.dumps({"시장": res["9장 시장"]["가장 나쁜 장세"],
                      "종목": [(x["이름"], (x.get("10장 결론") or {}).get("한 줄") or x.get("상태")) for x in res["종목"]]},
                     ensure_ascii=False, indent=1))
