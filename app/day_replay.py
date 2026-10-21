"""
6장 단타 장마감 복기 — "오늘 이 종목을 교재 규칙대로 단타했다면"

장중엔 1시간 간격 수집이라 단타 타점을 실시간으로 잡을 수 없다. 대신 장이 끝나면 그날 1분봉이 다 있으므로
교재 6-2·6-3·6-4·6-7 의 매수·손절·익절 규칙을 기계적으로 대입해 본다.

  데이터 : 네이버 1분봉(시가·고가·저가·종가·누적거래량). 종목과 지수(코스피/코스닥) 모두.
           야후 1분봉은 점심·장 막판이 비는 날이 있어 쓰지 않는다.
           전일 분봉까지 받아 3분봉 20선을 09:00 부터 바로 계산한다(HTS 와 같은 방식).
  공통 규칙 (6-4 PART B·D, 6-2·6-7)
    · 진입 : 3분봉이 마감될 때 그 종가로 산다. 지수 3분봉이 20선 아래면 사지 않는다.
    · 손절 : 방법별 손절가(최대 -3%). 1분봉 저가가 닿으면 손절가로 판다(시가가 이미 아래면 시가).
    · 1차 목표 : 절반을 판다. 그다음 남은 절반의 손절은 본전으로 올린다("수익 본 종목은 손실로 끝내지 않는다").
    · 보유선 : 종목 3분봉이 20선 아래로 마감하거나, 지수 3분봉이 20선 아래로 마감하면 나머지를 판다.
    · 당일 정리 : 15:19 종가로 모두 판다(단타는 당일 매매).
    · 비용 : 왕복 0.2% 를 뺀다 — "실제 1% 수익은 1.2% 이상이 나야 한다"(6-4 #12).
  한계 : 호가창(체결 강도·잔량)은 반영 못 한다. 같은 1분봉에서 손절가와 목표가가 둘 다 닿으면 손절로 친다(보수적).
         한 매매법당 첫 신호 1회만 본다.
"""
import json
import time
import urllib.request
from datetime import datetime, timedelta, timezone

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
COST = 0.2      # 왕복 수수료·세금(%)


def _get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read())


def naver_min(sym, kind, day):
    """하루치 1분봉. kind = 'item'(종목코드) / 'index'(KOSPI·KOSDAQ). 정규장 09:00~15:30 만 남긴다
    (15:40 이후는 대체거래소 시간외라 버린다). accumulatedTradingVolume 은 이름과 달리 그 1분의 거래량이다."""
    d = day.strftime("%Y%m%d")
    try:
        rows = _get(f"https://api.stock.naver.com/chart/domestic/{kind}/{sym}/minute"
                    f"?startDateTime={d}0900&endDateTime={d}1530")
    except Exception:
        return []
    out = []
    for r in rows:
        t = datetime.strptime(r["localDateTime"], "%Y%m%d%H%M%S")
        if t.date() != day or not ("0900" <= t.strftime("%H%M") <= "1530"):
            continue
        c = r.get("currentPrice")
        if c is None:
            continue
        out.append({"t": t, "o": r.get("openPrice") or c, "h": r.get("highPrice") or c,
                    "l": r.get("lowPrice") or c, "c": c, "v": r.get("accumulatedTradingVolume") or 0})
    return out


_toss_cache = {}        # 코드 → {"t": 받은 시각, "봉": 오래된 순 1분봉, "다음": 다음 쪽 before}
TOSS_최대_쪽수 = 12     # 한 번에 200개씩. 통합 분봉은 하루 최대 720개라 전일·오늘 두 날이면 8쪽 안팎이다


def _toss_ts(v):
    """토스 캔들 시각 → KST naive datetime. ISO 문자열(오프셋 유무 모두)과 epoch(초·밀리초)를 받는다."""
    kst = timezone(timedelta(hours=9))
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, kst).replace(tzinfo=None)
    t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    return t.astimezone(kst).replace(tzinfo=None) if t.tzinfo else t


def _toss_load(code, day):
    """day 의 첫 봉까지 거슬러 올라가며 받는다. 이미 받은 쪽은 60초 동안 다시 받지 않는다."""
    import toss
    hit = _toss_cache.get(code)
    if not hit or time.time() - hit["t"] > 60:
        rows, nxt = toss.candles_page(code, "1m", 200)
        hit = _toss_cache[code] = {"t": time.time(), "봉": rows, "다음": nxt, "쪽": 1}
    while hit["다음"] and hit["쪽"] < TOSS_최대_쪽수 and hit["봉"] and _toss_ts(hit["봉"][0]["시각"]).date() >= day:
        rows, nxt = toss.candles_page(code, "1m", 200, hit["다음"])
        if not rows:
            break
        seen = {r["시각"] for r in hit["봉"]}
        hit["봉"] = [r for r in rows if r["시각"] not in seen] + hit["봉"]
        hit["다음"], hit["쪽"] = nxt, hit["쪽"] + 1
        time.sleep(0.06)            # 초당 20회 한도
    return hit["봉"]


def toss_min(code, day):
    """토스 통합(KRX+NXT) 1분봉에서 하루치를 뽑아 naver_min 과 같은 모양으로 돌려준다.
    키가 없거나 허용 IP 에 없어 막히면 빈 리스트 → 호출한 쪽이 네이버로 넘어간다."""
    try:
        import toss
        if not toss.available():
            return []
        bars = _toss_load(code, day)
    except Exception:
        return []
    out = []
    for r in bars:
        try:
            # 토스 봉 시각은 그 1분이 끝나는 시각이다(09:01 봉이 첫 거래 구간). 네이버는 시작 시각이라 1분 당겨 맞춘다
            t = _toss_ts(r["시각"]) - timedelta(minutes=1)
        except (KeyError, ValueError, TypeError, OSError):
            continue
        if t.date() != day or not ("0900" <= t.strftime("%H%M") <= "1530"):
            continue
        out.append({"t": t, "o": r["시가"], "h": r["고가"], "l": r["저가"], "c": r["종가"], "v": r["거래량"]})
    return out


def minute(sym, kind, day):
    """종목은 토스 통합 분봉 우선, 없으면 네이버(KRX 정규장). 지수는 토스에 심볼이 없어 네이버만."""
    if kind == "item":
        rows = toss_min(sym, day)
        if rows:
            return rows
    return naver_min(sym, kind, day)


def to3(m1):
    """09:00 기준 3분 묶음. 키 = (날짜, 묶음 번호). 1분봉 인덱스 범위도 같이 들고 간다."""
    bars = []
    for i, r in enumerate(m1):
        k = (r["t"].date(), (r["t"].hour * 60 + r["t"].minute - 540) // 3)
        if bars and bars[-1]["k"] == k:
            b = bars[-1]
            b["h"], b["l"], b["c"], b["v"], b["j"] = max(b["h"], r["h"]), min(b["l"], r["l"]), r["c"], b["v"] + r["v"], i
        else:
            bars.append({"k": k, "t": r["t"], "o": r["o"], "h": r["h"], "l": r["l"], "c": r["c"], "v": r["v"], "i": i, "j": i})
    for n, b in enumerate(bars):
        b["ma"] = sum(x["c"] for x in bars[n - 19:n + 1]) / 20 if n >= 19 else None
    return bars


def _hm(t):
    return t.strftime("%H:%M")


def _r(x, k=2):
    return None if x is None else round(x, k)


def _tick_round(p):
    return round(p) if p >= 1000 else round(p, 2)


class Day:
    """하루 복기 재료: 종목 1분봉·3분봉(오늘), 지수 3분봉 상태, 전일 고가·종가."""

    def __init__(self, s1, s1p, i1, i1p, prev_hi, prev_close):
        self.m1 = s1
        all3 = to3(s1p + s1)
        self.b3 = [b for b in all3 if b["k"][0] == s1[0]["t"].date()]
        off = len(s1p)
        for b in self.b3:        # 1분봉 인덱스를 오늘 기준으로
            b["i"] -= off
            b["j"] -= off
        ix = to3(i1p + i1)
        today = s1[0]["t"].date()
        self.idx = {b["k"][1]: b for b in ix if b["k"][0] == today}
        self.prev_hi, self.prev_close = prev_hi, prev_close
        self.open = s1[0]["o"]

    def idx_ok(self, k):
        """그 3분봉 마감 시점에 지수 3분봉이 20선 위였나. 그 시각 봉이 없으면 직전 봉."""
        ks = [x for x in self.idx if x <= k]
        if not ks:
            return None
        b = self.idx[max(ks)]
        return None if b["ma"] is None else b["c"] >= b["ma"]


def simulate(day, n_entry, entry, stop, t1):
    """3분봉 n_entry 마감에 entry 로 산 뒤 1분봉으로 따라간다. 반환: 체결 목록·순수익률."""
    b3, m1 = day.b3, day.m1
    j0 = b3[n_entry]["j"]
    ends = {b["j"]: n for n, b in enumerate(b3)}      # 1분봉 인덱스 → 그 분에 마감되는 3분봉
    fills, left, half = [], 1.0, False

    def sell(i, px, w, why):
        nonlocal left
        fills.append({"시각": _hm(m1[i]["t"]), "i3": next(n for n, b in enumerate(b3) if b["i"] <= i <= b["j"]),
                      "가격": _tick_round(px), "비중": w, "사유": why, "손익(%)": _r((px / entry - 1) * 100)})
        left -= w

    for i in range(j0 + 1, len(m1)):
        r = m1[i]
        if r["t"].strftime("%H%M") >= "1520":      # 15:20~ 동시호가 — 직전 1분봉 종가로 정리
            sell(i - 1, m1[i - 1]["c"], left, "장 마감 전 정리(당일 매매)")
            break
        if not half:
            if r["l"] <= stop:
                sell(i, min(stop, r["o"]), left, "손절가 이탈")
                break
            if r["h"] >= t1:
                sell(i, max(t1, r["o"]), 0.5, "1차 목표 — 절반 매도")
                half, stop = True, entry
                if r["l"] <= stop:       # 같은 분에 본전까지 밀렸으면 본전 정리
                    sell(i, entry, left, "본전 이탈(남은 절반)")
                    break
                continue
        elif r["l"] <= stop:
            sell(i, min(stop, r["o"]), left, "본전 이탈(남은 절반)")
            break
        n = ends.get(i)
        if n is not None:
            b = b3[n]
            if b["ma"] is not None and b["c"] < b["ma"]:
                sell(i, b["c"], left, "종목 3분봉 20선 아래 마감(보유선 이탈)")
                break
            if day.idx_ok(b["k"][1]) is False:
                sell(i, b["c"], left, "지수 3분봉 20선 아래 마감 — 보유하지 않는다")
                break
    else:
        if left > 1e-9:
            sell(len(m1) - 1, m1[-1]["c"], left, "장 마감")
    gross = sum(f["비중"] * (f["가격"] / entry - 1) * 100 for f in fills)
    return fills, _r(gross - COST)


def _window(b, a, z):
    return a <= b["t"].strftime("%H%M") <= z


def m_open(day):
    """6-2 시초가 매매 — 초보는 9:20 이후. '밀린 뒤 시가 회복' + 고저 1/2 중심선 위 + 음봉을 이겨내는 양봉.
    시가 돌파 직전 이미 +10% 넘게 시세가 났으면 버린다('힘쓰면 조정')."""
    b3, o = day.b3, day.open
    blocked = []
    for n in range(1, len(b3)):
        b, p = b3[n], b3[n - 1]
        if not _window(b, "0920", "1030"):
            continue
        hi = max(x["h"] for x in b3[:n + 1]); lo = min(x["l"] for x in b3[:n + 1])
        dipped = lo < o
        if not (dipped and b["c"] > o and b["c"] > (hi + lo) / 2 and p["c"] < p["o"] and b["c"] > p["h"] and b["c"] > b["o"]):
            continue
        if hi >= o * 1.10:
            blocked.append(f"{_hm(b['t'])} 신호였지만 이미 시가 대비 +10% 시세 — 버림")
            continue
        if day.idx_ok(b["k"][1]) is False:
            blocked.append(f"{_hm(b['t'])} 신호였지만 지수 3분봉 20선 아래 — 안 삼")
            continue
        stop = max(lo, b["c"] * 0.97)
        return n, b["c"], stop, b["c"] * 1.02, (f"{_hm(b['t'])}봉: 시가 {o:,.0f} 아래로 밀렸다가 회복, 고저 중심 {(hi + lo) / 2:,.0f} 위, "
                                                f"직전 음봉 고가 {p['h']:,.0f} 돌파"), blocked
    return None, None, None, None, None, blocked


def m_pick(day):
    """6-3 장중 종목 선정 — 첫 봉 따라가지 않기 → 이평선(3분봉 20선)을 지키는 음봉 기다리기 → 음봉 회복 양봉에 매수.
    오늘 강한 종목이어야 하므로 전일 종가 위에서만. 손절가 = 음봉 저점."""
    b3, blocked = day.b3, []
    for n in range(1, len(b3)):
        b, p = b3[n], b3[n - 1]
        if not _window(b, "0930", "1430") or p["ma"] is None:
            continue
        if not (p["c"] < p["o"] and p["l"] >= p["ma"] * 0.998 and b["c"] > b["o"] and b["c"] > p["h"] and b["c"] > day.prev_close):
            continue
        if day.idx_ok(b["k"][1]) is False:
            blocked.append(f"{_hm(b['t'])} 신호였지만 지수 3분봉 20선 아래 — 안 삼")
            continue
        stop = max(p["l"], b["c"] * 0.97)
        return n, b["c"], stop, b["c"] * 1.02, (f"{_hm(p['t'])} 음봉이 20선({p['ma']:,.0f}) 위에서 멈추고, {_hm(b['t'])} 양봉이 "
                                                f"음봉 고가 {p['h']:,.0f} 회복"), blocked
    return None, None, None, None, None, blocked


def m_scalp(day):
    """6-4 초단타 — 전일 고가(자석) 돌파 → 그 위에서 음봉 조정(안착) → 음봉 회복 양봉에 매수.
    '양봉에 사지 않는다, 음봉을 기다린다' · 매수 가용구간(전일 고가 +3% 안). 활발 시간대 09:30~10:30, 13:30~15:00."""
    b3, lv, blocked = day.b3, day.prev_hi, []
    broke = None
    for n in range(1, len(b3)):
        b, p = b3[n], b3[n - 1]
        if broke is None and b["c"] > lv:
            broke = n
        if broke is None or n <= broke:
            continue
        if not (_window(b, "0930", "1030") or _window(b, "1330", "1500")):
            continue
        if not (p["c"] < p["o"] and p["l"] >= lv * 0.995 and b["c"] > b["o"] and b["c"] > p["h"]):
            continue
        if b["c"] > lv * 1.03:
            blocked.append(f"{_hm(b['t'])} 신호였지만 전일 고가에서 +3% 넘게 떨어진 자리(가용구간 밖)")
            continue
        if day.idx_ok(b["k"][1]) is False:
            blocked.append(f"{_hm(b['t'])} 신호였지만 지수 3분봉 20선 아래 — 안 삼")
            continue
        stop = max(min(p["l"], lv * 0.995), b["c"] * 0.97)
        return n, b["c"], stop, b["c"] * 1.015, (f"{_hm(b3[broke]['t'])} 전일 고가 {lv:,.0f} 돌파 → {_hm(p['t'])} 음봉이 그 위에서 버팀(안착) → "
                                                 f"{_hm(b['t'])} 양봉 회복"), blocked
    if broke is None:
        blocked.append(f"전일 고가 {lv:,.0f} 위로 3분봉이 한 번도 마감하지 못함 — 자석 자리가 안 열림")
    return None, None, None, None, None, blocked


def m_after(day):
    """6-7 오후 단타 — 지수가 오후에 더 밀리지 않고(오전 저점 위), 종목은 오전 상승 뒤 많이 빠지지 않고(오전 고저 중심 위)
    13:00~14:30 에 오전 고점을 돌파하면 매수. 목표 5%(5~7% 분할)."""
    b3, blocked = day.b3, []
    am = [b for b in b3 if b["t"].strftime("%H%M") < "1200"]
    if not am:
        return None, None, None, None, None, ["오전 분봉 없음"]
    H, Lo = max(b["h"] for b in am), min(b["l"] for b in am)
    ia = [b for k, b in day.idx.items() if b["t"].strftime("%H%M") < "1200"]
    i_lo = min(b["l"] for b in ia) if ia else None
    for n in range(len(b3)):
        b = b3[n]
        if not _window(b, "1300", "1430") or b["c"] <= H:
            continue
        mid = [x for x in b3[:n] if x["t"].strftime("%H%M") >= "1200"]
        if mid and min(x["l"] for x in mid) < (H + Lo) / 2:
            blocked.append(f"{_hm(b['t'])} 오전 고점 돌파였지만 점심에 오전 상승분 절반 아래까지 빠졌던 종목")
            return None, None, None, None, None, blocked
        ip = [x for k, x in day.idx.items() if "1200" <= x["t"].strftime("%H%M") <= b["t"].strftime("%H%M")]
        if i_lo is not None and ip and min(x["l"] for x in ip) < i_lo:
            blocked.append(f"{_hm(b['t'])} 오전 고점 돌파였지만 지수가 오후에 오전 저점을 깸 — 오후 매매 전제 실패")
            return None, None, None, None, None, blocked
        if day.idx_ok(b["k"][1]) is False:
            blocked.append(f"{_hm(b['t'])} 오전 고점 돌파였지만 지수 3분봉 20선 아래 — 안 삼")
            continue
        low = min(x["l"] for x in mid) if mid else b["l"]
        stop = max(low, b["c"] * 0.97)
        return n, b["c"], stop, b["c"] * 1.05, f"{_hm(b['t'])}봉이 오전 고점 {H:,.0f} 돌파(점심 저점 {low:,.0f} 이 오전 고저 중심 위)", blocked
    blocked.append(f"13:00~14:30 에 오전 고점 {H:,.0f} 을 넘지 못함")
    return None, None, None, None, None, blocked


METHODS = [
    ("시초가 매매", "6-2", m_open, "9:20~10:30 · 밀린 뒤 시가 회복 + 고저 중심 위 + 음봉 이기는 양봉", "당일 저점(최대 -3%)", "+2% 절반"),
    ("장중 종목 선정 단타", "6-3", m_pick, "9:30~14:30 · 20선 지키는 음봉 → 회복 양봉 · 전일 종가 위", "음봉 저점(최대 -3%)", "+2% 절반"),
    ("초단타·스캘핑", "6-4", m_scalp, "9:30~10:30·13:30~15:00 · 전일 고가 돌파 → 안착 음봉 → 회복 양봉", "음봉 저점·전일 고가 -0.5%(최대 -3%)", "+1.5% 절반"),
    ("오후 단타", "6-7", m_after, "13:00~14:30 · 오전 고점 돌파 · 지수 오후 저점 유지", "점심 저점(최대 -3%)", "+5% 절반"),
]


def opening_check(day):
    """6-2 #7~11 — 9:10 이후 생존/붕괴. ① 9:10~9:30 저점 ≥ 9:00~9:10 저점 ② 9:30 전 고점 돌파 ③ 저점을 올려감."""
    m = day.m1
    seg = lambda a, z: [r for r in m if a <= r["t"].strftime("%H%M") < z]
    a, b, c1, c2 = seg("0900", "0910"), seg("0910", "0930"), seg("0910", "0920"), seg("0920", "0930")
    if not (a and b and c1 and c2):
        return None
    p910 = a[-1]["c"]
    ok = [min(r["l"] for r in b) >= min(r["l"] for r in a), max(r["h"] for r in b) > max(r["h"] for r in a),
          min(r["l"] for r in c2) > min(r["l"] for r in c1)]
    close = m[-1]["c"]
    return {"9:10 가격": p910, "종가": close, "9:10 대비 종가(%)": _r((close / p910 - 1) * 100),
            "저점 지킴": ok[0], "9:30 전 고점 돌파": ok[1], "저점 올림": ok[2], "공통점 수": sum(ok),
            "결과": "생존" if close >= p910 else "붕괴"}


def chase_open(day):
    """교재가 하지 말라는 매매 — 09:00 시가에 바로 샀다면(같은 손절·익절 규칙)."""
    b0 = day.b3[0]
    o = day.open
    # 09:00 시가 진입: 첫 1분봉 시가에 사고 그 1분봉부터 따라간다 — simulate 는 3분봉 마감 이후부터 보므로 직접 계산
    m1, stop, t1 = day.m1, o * 0.97, o * 1.02
    for i, r in enumerate(m1):
        if r["l"] <= stop:
            return {"매수": o, "결과": _r((stop / o - 1) * 100 - COST), "청산": f"{_hm(r['t'])} -3% 손절"}
        if r["h"] >= t1:
            rest = m1[i:]
            for q in rest[1:]:
                if q["t"].strftime("%H%M") >= "1520" or q["l"] <= o:
                    px = o if q["l"] <= o else q["c"]
                    return {"매수": o, "결과": _r(((t1 / o - 1) * 50 + (px / o - 1) * 50) - COST),
                            "청산": f"{_hm(r['t'])} +2% 절반 → {_hm(q['t'])} {'본전' if px == o else '마감'} 정리"}
            return {"매수": o, "결과": _r((t1 / o - 1) * 100 - COST), "청산": f"{_hm(r['t'])} +2%"}
    return {"매수": o, "결과": _r((m1[-1]["c"] / o - 1) * 100 - COST), "청산": "손절·목표 없이 마감"}


def replay(code, idx_kind, d_rows):
    """d_rows = 네이버 일봉(마지막이 오늘). 오늘·전일 1분봉으로 4개 매매법을 대입한다."""
    today, prev = d_rows[-1]["t"].date(), d_rows[-2]["t"].date()
    s1, s1p = minute(code, "item", today), minute(code, "item", prev)
    i1, i1p = naver_min(idx_kind, "index", today), naver_min(idx_kind, "index", prev)
    if len(s1) < 30:
        return {"판정": "오늘 분봉 부족", "날짜": str(today)}
    day = Day(s1, s1p, i1, i1p, d_rows[-2]["h"], d_rows[-2]["c"])
    last = s1[-1]["t"].strftime("%H%M")
    done = last >= "1519"
    res = []
    for nm, src, fn, rule, sl, tp in METHODS:
        n, px, stop, t1, why, blocked = fn(day)
        r = {"매매법": nm, "교재": src, "규칙": rule, "손절 규칙": sl, "1차 목표 규칙": tp, "막힌 신호": blocked[:3]}
        if n is None:
            r["결과"] = "신호 없음"
        else:
            fills, net = simulate(day, n, px, stop, t1)
            r.update({"결과": "매매", "매수 시각": _hm(day.b3[n]["t"]), "i3": n, "매수가": _tick_round(px),
                      "손절가": _tick_round(stop), "1차 목표": _tick_round(t1), "근거": why,
                      "체결": fills, "순수익(%)": net})
        res.append(r)
    under = []      # 지수 3분봉 20선 아래 구간 (3분봉 인덱스)
    for n, b in enumerate(day.b3):
        ok = day.idx_ok(b["k"][1])
        if ok is False:
            if under and under[-1][1] == n - 1:
                under[-1][1] = n
            else:
                under.append([n, n])
    hi_i = max(range(len(s1)), key=lambda i: s1[i]["h"]); lo_i = min(range(len(s1)), key=lambda i: s1[i]["l"])
    fb = [b for b in day.b3 if b["t"].strftime("%H%M") < "1520"]   # 15:30 동시호가 봉은 거래량이 커서 차트에서 뺀다
    frame = {"t": [b["t"].strftime("%H:%M") for b in fb], "o": [b["o"] for b in fb], "h": [b["h"] for b in fb],
             "l": [b["l"] for b in fb], "c": [b["c"] for b in fb], "v": [int(b["v"]) for b in fb],
             "ma": {"20": [_r(b["ma"], 1) for b in fb]}}
    return {"날짜": str(today), "확정": done, "마지막 분봉": _hm(s1[-1]["t"]), "지수": idx_kind,
            "시가": day.open, "고가": s1[hi_i]["h"], "고가 시각": _hm(s1[hi_i]["t"]), "저가": s1[lo_i]["l"],
            "저가 시각": _hm(s1[lo_i]["t"]), "종가": s1[-1]["c"], "전일 고가": day.prev_hi, "전일 종가": day.prev_close,
            "지수 20선 아래 구간": under, "지수 20선 위 비율(%)": _r(100 - sum(b - a + 1 for a, b in under) / len(day.b3) * 100, 0),
            "시초가 생존 체크": opening_check(day), "시가 즉시 매수였다면": chase_open(day),
            "매매법": res, "비용(%)": COST, "_frame": frame}


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    import textbook_flow as tf
    code = sys.argv[1] if len(sys.argv) > 1 else "005930"
    d = tf.naver_chart(code, "day", 30)
    out = replay(code, sys.argv[2] if len(sys.argv) > 2 else "KOSPI", d)
    out.pop("_frame", None)
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
