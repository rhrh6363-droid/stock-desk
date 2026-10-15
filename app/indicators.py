"""
===========================================================
  교재 기반 차트 판정  —  계산할 수 있는 것만
===========================================================

근거 교재 (E:\\Claude\\siyun\\교재)
  7-3 신고가·전고점 돌파   네 개의 매수자리 / 돌파 확률 5조건 / 요란·조용 / 첫 저점 손절
  7-2 눌림목 매매          정배열 / 20봉 변동폭 / 거래대금 밴드 / 방어선 확인 횟수 / 데드크로스
  1-9 이격도와 이평선 수렴  이격도 110 근접 = 고점 지향, 95 근접 = 조정의 끝
  1-5 매물대 차트          과거 고점 군집 = 저항 밴드
  1-4 라운드피겨           가격대별 라운드 단위
  4-1 RSI                  70 이상은 "그 자리에서 창을 닫는다" — 위험 척도
  8-3 손절의 기술          손절선은 구조(첫 저점·변곡점)에서 나온다. 임의 %가 아니다

[ 이 모듈이 하지 않는 것 ]
  "사라 / 팔아라" 를 말하지 않는다. trading-desk 스킬 원칙 그대로
  **얼마나 위험하고 얼마나 벌 수 있는지 재는 자** 역할만 한다.
  체크카드 항목을 통과/미달/판정불가로 돌려주고 해석은 사람이 한다.

  교재에 있지만 데이터로 확인할 수 없는 항목(호가창·세력 흔적·수주 금액 대비 매출)은
  아예 넣지 않는다. 지어내는 것이 최악의 실패다.
===========================================================
"""

RSI_PERIOD = 14
BAND_PERIOD = 20
SPIKE_PCT = 20.0            # 하루 20% 이상 = '상 잘 가는' 날 = 끼
BODY_MIN = 60.0             # 장대양봉 몸통 비율
TAIL_MAX = 15.0             # 장대양봉 윗꼬리 허용치
간격 = 0.03                 # 고점 군집(매물대) 을 한 밴드로 묶는 가격 허용폭 3%


# ────────────────────────────────────────────────
# 기본 계산
# ────────────────────────────────────────────────
def _ma(vals: list[float], n: int) -> float | None:
    return round(sum(vals[-n:]) / n, 2) if len(vals) >= n else None


def _ma_series(vals: list[float], n: int) -> list[float | None]:
    out: list[float | None] = []
    for i in range(len(vals)):
        out.append(round(sum(vals[i - n + 1:i + 1]) / n, 2) if i >= n - 1 else None)
    return out


def rsi(closes: list[float], period: int = RSI_PERIOD) -> float | None:
    """Wilder RSI. 교재 4-1 — 70 이상 과매수 · 30 이하 과매도. **위험 척도일 뿐이다.**"""
    if len(closes) < period + 1:
        return None
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    ag, al = gains / period, losses / period
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (period - 1) + max(d, 0.0)) / period
        al = (al * (period - 1) + max(-d, 0.0)) / period
    if al == 0:
        return 100.0 if ag > 0 else 50.0
    return round(100 - 100 / (1 + ag / al), 1)


def bollinger(closes: list[float], n: int = BAND_PERIOD, k: float = 2.0) -> dict:
    """볼밴 σ2. %B = 밴드 안 위치 = 위험률. 상단으로 갈수록 위험하다."""
    if len(closes) < n:
        return {}
    win = closes[-n:]
    mid = sum(win) / n
    var = sum((x - mid) ** 2 for x in win) / n
    sd = var ** 0.5
    up, lo = mid + k * sd, mid - k * sd
    last = closes[-1]
    pb = (last - lo) / (up - lo) * 100 if up != lo else None
    위치 = ("상단이탈" if pb is not None and pb > 100 else
            "상단권" if pb is not None and pb >= 80 else
            "중상단" if pb is not None and pb >= 60 else
            "중심권" if pb is not None and pb >= 40 else
            "중하단" if pb is not None and pb >= 20 else
            "하단권" if pb is not None and pb >= 0 else
            "하단이탈" if pb is not None else "판정불가")
    return {"상단": round(up, 2), "중심": round(mid, 2), "하단": round(lo, 2),
            "%B": round(pb, 1) if pb is not None else None, "위치": 위치}


def avg_range(rows: list[dict], n: int = 20) -> float | None:
    """그 종목의 정상 일중변동폭(%). **손절폭의 기준점이다** (trading-desk 확정).

    평균 8% 움직이는 종목에 -5% 손절은 하루 노이즈에 털린다.
    """
    win = rows[-n:]
    vals = [(r["고가"] - r["저가"]) / r["저가"] * 100 for r in win if r["저가"] > 0]
    return round(sum(vals) / len(vals), 2) if vals else None


# ────────────────────────────────────────────────
# 7-3  신고가의 '격'
# ────────────────────────────────────────────────
def high_grade(rows: list[dict]) -> dict:
    """어느 기간의 고점을 깨고 있는가. 기간이 길어야 의미가 있다 (교재 7-3 PART B).

    그리고 **계속 경신 중인 종목은 신고가 매매가 아니다** — 며칠째 경신인지 센다.
    """
    if len(rows) < 25:
        return {}
    closes = [r["종가"] for r in rows]
    highs = [r["고가"] for r in rows]
    last = closes[-1]

    격 = None
    for 기간, 이름 in ((len(rows), "사상최고(조회구간)"), (250, "52주"),
                       (120, "120일"), (60, "60일"), (20, "20일")):
        if len(rows) < 기간:
            continue
        prior = max(highs[-기간:-1])
        if last > prior:
            격 = 이름
            break

    # 며칠째 신고가를 경신하고 있는가 — 1일이면 '오랜만의 돌파', 여러 날이면 경신 중
    경신일 = 0
    for i in range(len(rows) - 1, 19, -1):
        if closes[i] > max(highs[max(0, i - 60):i]):
            경신일 += 1
        else:
            break

    prior60 = max(highs[-61:-1]) if len(rows) >= 61 else max(highs[:-1])
    return {
        "신고가격": 격 or "해당없음",
        "60일전고점": round(prior60, 2),
        "전고점대비(%)": round((last / prior60 - 1) * 100, 2) if prior60 else None,
        "돌파": bool(last > prior60),
        "연속경신일": 경신일,
        # 교재: "계속 경신 중인 종목 → 신고가 매매가 아니다"
        "경신중": bool(경신일 >= 3),
    }


# ────────────────────────────────────────────────
# 7-3 PART D  돌파 확률 5조건
# ────────────────────────────────────────────────
def breakout_odds(rows: list[dict], 시총억: float | None = None) -> dict:
    """돌파 확률을 높이는 다섯 가지. 통과/미달을 체크카드 모양으로 돌려준다."""
    if len(rows) < 60:
        return {}
    closes = [r["종가"] for r in rows]
    lows = [r["저가"] for r in rows]
    highs = [r["고가"] for r in rows]
    last = closes[-1]
    ma20s = _ma_series(closes, 20)
    ma20 = ma20s[-1]

    체크 = []

    # (1) 이격도 — 20선과 가까운가. "총알이 총에 들어왔는가"
    이격 = round(last / ma20 * 100, 1) if ma20 else None
    체크.append({
        "항목": "이격도 — 20선과 가까운가",
        "값": f"{이격}" if 이격 else "판정불가",
        # 교재 1-9: 110 근접 이상이면 고점을 향해 가고 있다
        "통과": bool(이격 is not None and 이격 <= 110),
        "근거": "1-9 · 110 근접 이상이면 고점 지향 / 95 근접은 조정의 끝",
    })

    # (2) 시세 시작점 — 이번 상승이 몇 %인가. 100%면 과열
    구간저 = min(lows[-60:])
    상승률 = round((last / 구간저 - 1) * 100, 1) if 구간저 else None
    체크.append({
        "항목": "시세 시작점 대비 상승률",
        "값": f"{상승률}%" if 상승률 is not None else "판정불가",
        "통과": bool(상승률 is not None and 상승률 < 100),
        "근거": "7-3 D · 100% 넘으면 과열 — 총알을 이미 썼다",
    })

    # (3) ★ 20선의 '출발선' 이 전보다 올라왔는가
    출발선 = None
    if len(ma20s) >= 21 and ma20s[-21] and ma20:
        출발선 = round((ma20 / ma20s[-21] - 1) * 100, 1)
    체크.append({
        "항목": "★ 20선 출발선이 전보다 올라왔는가",
        "값": f"20일전 대비 {출발선}%" if 출발선 is not None else "판정불가",
        "통과": bool(출발선 is not None and 출발선 > 0),
        "근거": "7-3 D · 출발선이 올라와 있으면 눌려도 바닥이 높다",
    })

    # (4) 조정이 짧은가 — 상승분의 중심 또는 1/3 이상을 지켰는가
    구간고 = max(highs[-60:])
    되돌림 = None
    if 구간고 > 구간저:
        되돌림 = round((구간고 - last) / (구간고 - 구간저) * 100, 1)
    체크.append({
        "항목": "조정이 짧은가 (상승분 1/3 이내)",
        "값": f"고점에서 {되돌림}% 되돌림" if 되돌림 is not None else "판정불가",
        "통과": bool(되돌림 is not None and 되돌림 <= 33.3),
        "근거": "7-3 D · 상승분의 중심 또는 1/3 이상 지지",
    })

    # (5) ★ 시가총액 — 교재는 수치를 적지 않았다. 7-3 D 는 "충분히 큰가" 뿐이다.
    # 교재의 수치 기준은 1-9 의 500억(개인이 만들 수 없는 규모)이고,
    # 5천억은 **사용자 투자원칙**이다. 둘을 섞어 적지 않는다
    체크.append({
        "항목": "★ 시가총액 5천억 이상 (휩쏘 당하기 어려운 크기)",
        "값": f"{시총억:,.0f}억" if 시총억 else "확인 불가",
        "통과": bool(시총억 and 시총억 >= 5000),
        "근거": "<사용자 확정> 5천억 · 교재 7-3 D 는 수치 없음 (1-9 는 500억)",
    })

    return {
        "체크": 체크,
        "통과수": sum(1 for c in 체크 if c["통과"]),
        "전체": len(체크),
        "이격도": 이격, "시세상승률": 상승률, "20선출발선": 출발선,
        "되돌림(%)": 되돌림,
        "구간저": round(구간저, 2), "구간고": round(구간고, 2),
    }


# ────────────────────────────────────────────────
# 7-3 PART C  네 개의 매수 자리  (확률 4 > 3 > 1 > 2)
# ────────────────────────────────────────────────
def entry_zone(rows: list[dict]) -> dict:
    """지금 가격이 네 자리 중 어디인가. 자리 번호와 교재가 매긴 확률 등급을 같이 준다."""
    if len(rows) < 60:
        return {}
    closes = [r["종가"] for r in rows]
    highs = [r["고가"] for r in rows]
    last = closes[-1]
    ma20 = _ma(closes, 20)
    전고 = max(highs[-61:-1])
    if not ma20 or not 전고:
        return {}

    이격20 = (last / ma20 - 1) * 100
    전고대비 = (last / 전고 - 1) * 100
    근접 = abs(이격20) <= 3.0                      # 20선 근방
    전고근접 = abs(전고대비) <= 2.0                 # 전고점 교차권

    if 전고근접 and 근접:
        자리, 등급, 말 = 4, "★ 가장 높은 확률", "전고점 + 20선 교차 — 마지막 기회 자리"
    elif 근접 and last < 전고:
        자리, 등급, 말 = 3, "○ 좋다", "20선 근방 반등 자리"
    elif -8 < 전고대비 < 0:
        자리, 등급, 말 = 1, "△ 수익 크지만 돌파 실패 위험", "돌파 직전 자리"
    elif 0 <= 전고대비 <= 3:
        자리, 등급, 말 = 2, "✕ 가장 많이 하고 가장 나쁘다", "돌파하는 순간 — 교재가 가장 경계하는 자리"
    else:
        자리, 등급, 말 = 0, "해당 자리 아님", (
            "전고점에서 멀다 — 돌파 매매 구간이 아니다" if 전고대비 > 3
            else "전고점에서 많이 눌렸다 — 눌림목(7-2)으로 봐야 한다")

    return {"자리": 자리, "등급": 등급, "설명": 말,
            "20선이격(%)": round(이격20, 2), "전고점대비(%)": round(전고대비, 2),
            "확률순서": "4 > 3 > 1 > 2"}


# ────────────────────────────────────────────────
# 7-3 PART E  요란한가 조용한가
# ────────────────────────────────────────────────
def loud_or_quiet(rows: list[dict]) -> dict:
    """요란함 = 단타용. 조용함 = ★ 스윙 수익 매매에 적합 (교재 7-3 PART E)."""
    if len(rows) < 25:
        return {}
    closes = [r["종가"] for r in rows]
    vols = [r["거래량"] for r in rows]
    last = rows[-1]
    ma20 = _ma(closes, 20)
    평균거래량 = sum(vols[-21:-1]) / 20 if len(vols) >= 21 else None

    배수 = round(vols[-1] / 평균거래량, 2) if 평균거래량 else None
    rng = last["고가"] - last["저가"]
    몸통 = abs(last["종가"] - last["시가"]) / rng * 100 if rng else 0.0
    윗꼬리 = (last["고가"] - last["종가"]) / rng * 100 if rng else 0.0
    이격 = round(last["종가"] / ma20 * 100, 1) if ma20 else None

    요란 = bool(배수 and 배수 >= 3 and 몸통 >= BODY_MIN and 이격 and 이격 >= 110)
    조용 = bool(배수 and 배수 <= 1.8 and 이격 and 이격 <= 107)
    성격 = "요란한 신고가" if 요란 else "조용한 신고가" if 조용 else "중간"
    쓰임 = ("단타로만 — 5·10선 이격 축소 + 단봉 기준이 있을 때만" if 요란
            else "★ 스윙 수익 매매에 적합 — 캔들·5선이 밴드 안" if 조용
            else "교재가 가른 두 유형 어느 쪽도 아니다")

    return {"성격": 성격, "쓰임": 쓰임, "거래량배수": 배수,
            "몸통(%)": round(몸통, 1), "윗꼬리(%)": round(윗꼬리, 1), "이격도": 이격,
            "장대양봉": bool(몸통 >= BODY_MIN and 윗꼬리 <= TAIL_MAX
                             and last["종가"] > last["시가"])}


# ────────────────────────────────────────────────
# 7-3 PART G / 8-3  손절선 — 구조에서 뽑는다
# ────────────────────────────────────────────────
def first_pivot_low(rows: list[dict], lookback: int = 40) -> dict:
    """"돌려세우고 만든 첫 번째 저점" — 교재 7-3 PART G 의 손절 기준.

    최근 고점 이후에 생긴 첫 스윙 저점을 찾는다. 임의 % 손절이 아니라
    **구조가 깨지는 가격**이다 (8-3).
    """
    win = rows[-lookback:]
    if len(win) < 7:
        return {}
    highs = [r["고가"] for r in win]
    hi = max(range(len(highs)), key=lambda i: highs[i])
    after = win[hi:]
    if len(after) < 3:
        return {"상태": "고점 직후 — 아직 저점이 만들어지지 않았다"}

    # 좌우 한 봉보다 낮은 첫 지점 = 첫 스윙 저점
    last = rows[-1]["종가"]
    for i in range(1, len(after) - 1):
        if after[i]["저가"] <= after[i - 1]["저가"] and after[i]["저가"] <= after[i + 1]["저가"]:
            저 = after[i]["저가"]
            거리 = round((저 / last - 1) * 100, 2) if last else None
            # 현재가가 첫 저점 아래면 손절 지점이 아니다 — 이미 깨고 내려온 것이다.
            # 교재 7-3 PART G 의 매도 조건이 벌써 충족된 상태라는 뜻이고,
            # 이걸 손절가로 내놓으면 현재가보다 위에 있는 손절가가 된다.
            깨짐 = bool(거리 is not None and 거리 > 0)
            return {
                "첫저점": round(저, 2), "날짜": after[i]["날짜"],
                "현재가대비(%)": 거리,
                "이미깨짐": 깨짐,
                "의미": ("현재가가 이 저점 아래다 — 교재 7-3 PART G 의 매도 조건이 "
                          "이미 충족된 상태. 손절선으로 쓸 수 없다" if 깨짐
                          else "이 저점을 깨면 구조가 깨진 것 — 교재가 말한 손절 지점"),
            }
    return {"상태": "아직 첫 저점이 확정되지 않았다"}


def supply_bands(rows: list[dict], top: int = 4, window: int = 250,
                 최대거리: float = 45.0) -> list[dict]:
    """과거 고점 군집 = 매물대·변곡점 밴드 (교재 1-5 · 7-2 [4]).

    가까운 고점끼리 3% 안으로 묶는다. 겹치는 지점이 많은 밴드가 저항·지지 밴드다.

    범위를 1년(250봉)으로, 거리를 ±45% 로 조인다. 그보다 먼 밴드는 지금 매매에
    저항으로 작동하지 않는다 — 삼성전자처럼 몇 배 오른 종목은 2년 전 6만원대
    고점 군집이 가장 두껍게 잡히는데, 그건 오늘 자리와 아무 상관이 없다.
    """
    rows = rows[-window:]
    if len(rows) < 40:
        return []
    피크 = []
    for i in range(2, len(rows) - 2):
        h = rows[i]["고가"]
        if h >= max(rows[i - 2]["고가"], rows[i - 1]["고가"],
                    rows[i + 1]["고가"], rows[i + 2]["고가"]):
            피크.append(h)
    if not 피크:
        return []

    피크.sort()
    묶음: list[list[float]] = [[피크[0]]]
    for p in 피크[1:]:
        if p <= 묶음[-1][-1] * (1 + 간격):
            묶음[-1].append(p)
        else:
            묶음.append([p])

    last = rows[-1]["종가"]
    out = [{"밴드": round(sum(g) / len(g), 2), "하단": round(min(g), 2),
            "상단": round(max(g), 2), "겹침": len(g),
            "현재가대비(%)": round((sum(g) / len(g) / last - 1) * 100, 2) if last else None}
           for g in 묶음]
    out = [b for b in out if abs(b["현재가대비(%)"] or 999) <= 최대거리]
    out.sort(key=lambda x: (-x["겹침"], abs(x["현재가대비(%)"] or 999)))
    for b in out:
        # 교재 1-5 는 HTS 매물대 지표(가격대별 누적 거래량)를 쓴다. 그 자료가 없어
        # 고점 군집으로 대신한다. 3% 허용폭은 교재 사례(35,000원 매물대 → 34,000~36,000)
        # 에서 역산한 값이지 교재가 명시한 규칙이 아니다
        b["근거"] = "1-5 대체 <역산> · 고점 군집 ±3%"
    return out[:top]


def round_figure(price: float) -> dict:
    """라운드피겨 — 교재 1-4 가 적어둔 단위는 다섯 개다.

        1,000 / 5,000 / 10,000 / 50,000 / 100,000원

    100원 단위는 교재에 없다(이전 구현의 오류). 현재가보다 큰 단위 중 가장 작은 것을
    고르고, 그 단위로 위·아래 라운드피겨를 잡는다.
    """
    # "종목 주가에 맞는" 단위 = 한 칸이 주가의 10% 를 넘지 않는 가장 큰 단위.
    # 그래야 다음 라운드피겨가 실제로 닿을 거리에 있다 — 20만원 종목에 10만원 단위를
    # 쓰면 '위 30만원(+44%)' 처럼 쓸 수 없는 값이 나온다
    단위목록 = [1000, 5000, 10000, 50000, 100000]
    후보 = [u for u in 단위목록 if u <= price * 0.1]
    단위 = max(후보) if 후보 else 단위목록[0]
    아래 = int(price // 단위) * 단위
    위 = 아래 + 단위 if 아래 < price else 아래
    return {"단위": 단위, "아래": 아래, "위": 위,
            "위까지(%)": round((위 / price - 1) * 100, 2) if price else None,
            "아래까지(%)": round((아래 / price - 1) * 100, 2) if price else None,
            "근거": "1-4 · 단위 1,000/5,000/10,000/50,000/100,000원"}


# ────────────────────────────────────────────────
# 7-2  눌림목 체크
# ────────────────────────────────────────────────
def pullback(rows: list[dict]) -> dict:
    """눌림목 자격 — 정배열 · 20봉 변동폭 · 거래대금 밴드 · 방어선 확인 횟수."""
    if len(rows) < 70:
        return {}
    closes = [r["종가"] for r in rows]
    lows = [r["저가"] for r in rows]
    금액 = [r.get("추정거래대금") or 0 for r in rows]
    last = closes[-1]
    ma5, ma20, ma60 = _ma(closes, 5), _ma(closes, 20), _ma(closes, 60)
    ma220 = _ma(closes, 220) if len(closes) >= 220 else None

    체크 = []
    정배열 = bool(ma5 and ma20 and ma60 and ma5 > ma20 > ma60)
    체크.append({"항목": "5 > 20 > 60 정배열", "값": f"{ma5} / {ma20} / {ma60}",
                 "통과": 정배열, "근거": "7-2 [1] 종목 자격"})

    # 5봉 전부터 과거 20봉간 변동폭 10% 이상 = 움직일 힘이 있는 종목
    win = rows[-25:-5]
    변동 = None
    if win:
        변동 = round((max(r["고가"] for r in win) / min(r["저가"] for r in win) - 1) * 100, 1)
    체크.append({"항목": "5봉 전부터 과거 20봉 변동폭 10% 이상",
                 "값": f"{변동}%" if 변동 is not None else "판정불가",
                 "통과": bool(변동 is not None and 변동 >= 10),
                 "근거": "7-2 [1] 힘이 있는 종목인가"})

    # 거래대금 밴드 — 급등 전 조용했던 구간 평균 ~ 2배
    조용 = 금액[-60:-20]
    평균 = sum(조용) / len(조용) if 조용 else 0
    현재 = 금액[-1]
    체크.append({"항목": "거래대금이 '평균 ~ 평균×2' 밴드에 들어왔는가",
                 "값": (f"현재 {현재/1e8:,.0f}억 / 밴드 {평균/1e8:,.0f}~{평균*2/1e8:,.0f}억"
                        if 평균 else "판정불가"),
                 "통과": bool(평균 and 평균 <= 현재 <= 평균 * 2),
                 "근거": "7-2 [2] 물량이 소화되었는가"})

    # 방어선 — 최근 저점대를 몇 번 지켜냈는가 (2회면 관심종목)
    기준 = min(lows[-20:])
    방어 = sum(1 for r in rows[-40:]
               if 기준 * 0.99 <= r["저가"] <= 기준 * 1.03 and r["종가"] > r["시가"])
    체크.append({"항목": "방어선을 2회 이상 지켜냈는가",
                 "값": f"{기준:,.0f}원 근방 {방어}회",
                 "통과": bool(방어 >= 2),
                 "근거": "7-2 [3] 2회면 관심종목, 3~4회면 신뢰도 상승"})

    # 데드크로스 — 60선이 1년선 아래로 가면 제외
    체크.append({"항목": "60선이 1년선(220일) 위에 있는가",
                 "값": (f"60선 {ma60} / 220선 {ma220}" if ma220 else "220일 자료 부족"),
                 "통과": bool(ma220 and ma60 and ma60 > ma220),
                 "근거": "7-2 [5] 데드크로스 발생하면 제외"})

    # 사지 않는 자리 — 오늘 등락률 5% 초과면 눌림목이 아니다
    등락 = round((last / closes[-2] - 1) * 100, 2) if len(closes) > 1 else None
    체크.append({"항목": "오늘 등락률이 5% 이내인가 (아니면 눌림목이 아니다)",
                 "값": f"{등락}%" if 등락 is not None else "판정불가",
                 "통과": bool(등락 is not None and abs(등락) <= 5),
                 "근거": "7-2 [7] 사지 않는 자리"})

    return {"체크": 체크, "통과수": sum(1 for c in 체크 if c["통과"]), "전체": len(체크),
            "MA5": ma5, "MA20": ma20, "MA60": ma60, "MA220": ma220, "정배열": 정배열}


# ────────────────────────────────────────────────
# 손익비 — trading-desk 확정 3:1
# ────────────────────────────────────────────────
# 교재 7-5: "일봉 파동은 보통 7~15%, 평균 10% — 과욕 금지"
파동_평균 = 10.0
파동_최대 = 15.0


def stop_candidates(rows: list[dict]) -> list[dict]:
    """손절 후보를 **구조에서** 뽑는다. 교재 8-3 의 네 가지 기준 순서대로.

        ① 전저점  ② 이평선  ③ 캔들  ④ 박스권

    교재 7-5b 는 **"평단가 기준 비율 손절선"을 "합리화의 통로"로 금지**한다.
    그래서 % 손절은 후보에 넣지 않고, 아래 구조 후보들의 폭이 감당 가능한지만 본다.
    """
    if len(rows) < 25:
        return []
    closes = [r["종가"] for r in rows]
    last = closes[-1]
    out = []

    def add(이름, 가격, 근거):
        if not 가격 or not last or 가격 >= last:      # 현재가 위는 손절선이 아니다
            return
        out.append({"이름": 이름, "가격": round(가격, 2),
                    "손절폭(%)": round((1 - 가격 / last) * 100, 2), "근거": 근거})

    피벗 = first_pivot_low(rows)
    if not 피벗.get("이미깨짐"):
        add("돌려세운 뒤 첫 저점", 피벗.get("첫저점"), "7-3 [7] · 깨면 무조건 손절")
    add("5일선", _ma(closes, 5), "7-3 [7] 초단기 · 1-8 · 6-6(종가 이탈)")
    add("20일선", _ma(closes, 20), "7-3 [7] 스윙 1차 · 7-5")
    add("20일 전저점", min(r["저가"] for r in rows[-20:]), "8-3 ① 전저점")

    # 캔들 — 직전 장대양봉의 저점·중심 (교재 2-1 은 양봉 크기로 둘을 가른다)
    for r in reversed(rows[-20:]):
        rng = r["고가"] - r["저가"]
        if not rng or r["종가"] <= r["시가"]:
            continue
        몸통 = abs(r["종가"] - r["시가"]) / rng * 100
        크기 = (r["종가"] / r["시가"] - 1) * 100 if r["시가"] else 0
        if 몸통 >= BODY_MIN and 크기 >= 3:
            if 크기 <= 5:
                add("장대양봉 저점", r["저가"], f"2-1 · 돌파양봉 {크기:.1f}%(3~5%) → 저점")
            elif 크기 <= 10:
                add("장대양봉 중심", (r["고가"] + r["저가"]) / 2,
                    f"2-1 · 돌파양봉 {크기:.1f}%(7~10%) → 중심")
            else:
                out.append({"이름": "진입 보류", "가격": None, "손절폭(%)": None,
                            "근거": f"2-1 · 돌파양봉 {크기:.1f}% (10% 초과) → 조정 기다린다"})
            break

    out.sort(key=lambda x: (x["손절폭(%)"] is None, x["손절폭(%)"] or 999))
    return out


def risk_reward(rows: list[dict]) -> dict:
    """손익비 3:1 이 **성립하는 자리인지**를 본다.

    [ 교재가 정한 두 울타리 ]
      목표 거리  일봉 파동은 보통 **7~15%, 평균 10%** — 그걸 넘는 목표는 과욕 (7-5)
      손익비     최소 **1:3** (6-5) · 사용자 <확정>

      → 손절폭 × 3 ≤ 15%  이어야 성립한다. 즉 **손절폭 5% 이하**.
        평균 10% 를 목표로 하면 손절폭은 3.3% 이하여야 한다.

    [ 손절은 구조에서 ]
      교재 7-5b 가 평단가 기준 % 손절을 금지하므로 구조 후보(stop_candidates)를
      1순위로 쓴다. 평균변동폭은 "그 손절폭이 이 종목의 노이즈보다 큰가" 를
      검산하는 데만 쓴다 — 평균 8% 움직이는 종목에 −3% 손절은 하루에 털린다.
    """
    if len(rows) < 25:
        return {}
    last = rows[-1]["종가"]
    변동 = avg_range(rows, 20)
    if not last:
        return {}

    후보 = stop_candidates(rows)
    쓸수있는 = [c for c in 후보 if c["손절폭(%)"] is not None]

    # 손절폭이 들어와야 하는 창(窓)은 양쪽이 막혀 있다
    #   아래쪽  평균변동폭보다 커야 한다 — 작으면 하루 노이즈에 털린다
    #   위쪽    ×3 이 일봉 파동 최대 15% 안에 들어와야 한다 (7-5) → 5% 이하
    하한 = 변동 or 0
    상한 = 파동_최대 / 3
    채택 = next((c for c in 쓸수있는 if 하한 <= c["손절폭(%)"] <= 상한), None)

    결과 = {
        "평균변동폭(20일)": 변동,
        "손절후보": 후보,
        "손익비": "3:1 <사용자 확정 · 교재 6-5 최소 1:3>",
        "파동상한": f"일봉 파동 7~15%, 평균 10% (7-5)",
        "표기": "손절가는 <교재 구조 기준> · 평단가 % 손절은 교재 7-5b 가 금지한다",
    }
    결과["손절창"] = (f"{하한:.2f}% ~ {상한:.2f}% "
                      "(아래: 평균변동폭 / 위: 익절 3배가 파동 15% 안)")
    if not 채택:
        너무좁음 = [c for c in 쓸수있는 if c["손절폭(%)"] < 하한]
        너무넓음 = [c for c in 쓸수있는 if c["손절폭(%)"] > 상한]
        결과["판정"] = (
            "들어갈 자리가 아니다 — 구조 손절선이 "
            + ("평균변동폭보다 가까워 노이즈에 털린다" if 너무좁음 and not 너무넓음
               else "너무 멀어 손익비 3:1 이 파동 한계를 넘는다" if 너무넓음 and not 너무좁음
               else "손절창 안에 하나도 없다" if 쓸수있는
               else "현재가 아래에 아예 없다"))
        결과["조건미달"] = [결과["판정"]]
        return 결과

    손절폭 = 채택["손절폭(%)"]
    익절폭 = round(손절폭 * 3, 2)
    목표가 = round(last * (1 + 익절폭 / 100), 2)

    # 머리 위 저항 — 목표가까지 가는 길에 매물대가 몇 개 있나
    위밴드 = [b for b in supply_bands(rows, top=6) if (b["현재가대비(%)"] or 0) > 0]
    가로막 = [b for b in 위밴드 if b["밴드"] <= 목표가]

    미달 = []
    if 익절폭 > 파동_최대:
        미달.append(f"목표 {익절폭}% — 일봉 파동 최대 15% 를 넘는다. 갈 수 없는 거리 (7-5)")
    if 변동 and 손절폭 < 변동:
        미달.append(f"손절폭 {손절폭}% 가 평균변동폭 {변동}% 보다 작다 — 하루 노이즈에 털린다")
    if 가로막:
        미달.append(f"목표가 아래 매물대 {len(가로막)}개 — 그만큼 길이 막혀 있다")

    결과.update({
        "채택손절": 채택,
        "손절가": 채택["가격"], "손절폭(%)": 손절폭,
        "익절폭(%)": 익절폭, "목표가": 목표가,
        "목표가까지_저항밴드": 가로막,
        "조건미달": 미달,
        "판정": ("손익비 3:1 이 성립한다" if not 미달
                 else f"조건 미달 {len(미달)}건 — 교재 기준 들어갈 자리가 아니다"),
    })
    return 결과


def wave_count(rows: list[dict]) -> dict:
    """지금 몇 번째 상승 시세인가 — 교재 2-8 · 1-9.

      1~2파  추가 상승 가능. 조정을 노린다
      3파+   추격 자제 (1-9: 3파까지가 평균적으로 안전)

    20일선을 기준으로 위로 올라선 구간을 하나의 파동으로 센다. 교재가 말하는
    '시세'와 완전히 같지는 않다 — 그래서 <제안> 으로 표기한다.
    """
    if len(rows) < 80:
        return {}
    closes = [r["종가"] for r in rows]
    ma20 = _ma_series(closes, 20)

    파동 = 0
    위 = False
    for i in range(len(closes) - 60, len(closes)):
        if ma20[i] is None:
            continue
        now = closes[i] > ma20[i]
        if now and not 위:
            파동 += 1
        위 = now

    return {
        "파동수": 파동,
        "판정": ("1~2파 — 추가 상승 가능. 조정을 노린다 (2-8)" if 파동 <= 2
                 else "3파 — 평균적으로 여기까지가 안전 (1-9)" if 파동 == 3
                 else f"{파동}파 — 추격 자제 (2-8)"),
        "표기": "<제안> — 20선 상향 돌파 횟수로 센 것이다. 교재의 '시세' 정의와 같지 않다",
    }


# ────────────────────────────────────────────────
# 모멘텀 묶음
# ────────────────────────────────────────────────
def momentum(rows: list[dict]) -> dict:
    """RSI · 볼밴 · 이격도 · 거래대금 추세 · 2일 누적. **전부 척도다. 신호가 아니다.**"""
    if len(rows) < 25:
        return {}
    closes = [r["종가"] for r in rows]
    금액 = [r.get("추정거래대금") or 0 for r in rows]
    last = closes[-1]
    ma20 = _ma(closes, 20)

    등락 = round((last / closes[-2] - 1) * 100, 2) if len(closes) > 1 else None
    이틀 = round((last / closes[-3] - 1) * 100, 2) if len(closes) > 2 else None
    최근5 = sum(금액[-5:]) / 5 if len(금액) >= 5 else 0
    과거20 = sum(금액[-25:-5]) / 20 if len(금액) >= 25 else 0

    r = rsi(closes)
    bb = bollinger(closes)
    이격 = round(last / ma20 * 100, 1) if ma20 else None

    # 거래대금 — 교재가 쓰는 기준은 두 개다 (1-6 · 7-2)
    #   ① 조용했던 구간 평균의 1~2배까지 줄었다  → 자리다
    #   ② 평균 대비 5~20배로 터졌다              → 음봉일 때 위험 감지
    # 이전 구현의 1.3배 / 0.7배 는 교재에 없는 수치였다
    조용 = sum(금액[-60:-20]) / 40 if len(금액) >= 60 else 과거20
    배수 = round(금액[-1] / 조용, 2) if 조용 else None
    음봉 = rows[-1]["종가"] < rows[-1]["시가"]
    if 배수 is None:
        거래대금말 = None
    elif 배수 >= 5:
        거래대금말 = (f"조용했던 구간 평균의 {배수}배 — 5~20배 구간. "
                      + ("음봉이라 위험 감지 구간 (1-6)" if 음봉
                         else "양봉이면 분출, 음봉이면 위험 (1-6)"))
    elif 1 <= 배수 <= 2:
        거래대금말 = f"조용했던 구간 평균의 {배수}배 — 교재가 말한 '자리' 밴드(1~2배) 안 (1-6·7-2)"
    elif 배수 < 1:
        거래대금말 = f"조용했던 구간 평균의 {배수}배 — 평균 아래. 아직 물량이 안 들어왔다"
    else:
        거래대금말 = f"조용했던 구간 평균의 {배수}배 — 자리 밴드(1~2배)를 넘었다"

    return {
        "RSI(14)": r,
        "RSI판정": ("70 이상 과매수 — 교재 4-1: 그 자리에서 창을 닫는다" if r and r >= 70
                    else "30 이하 과매도" if r and r <= 30 else "30~70 정상 구간"),
        # 볼린저는 교재가 쓰지 않는다 (0-2: "고수 중에 사용하는 사람 별로 없습니다").
        # 사용자 투자원칙의 위험 척도 4종 중 하나라서 남긴다 — 교재 근거가 아니다
        "볼밴": bb,
        "볼밴출처": "<사용자 확정> — 교재 0-2 는 볼린저를 쓰지 않는다",
        "이격도": 이격,
        "이격판정": None if 이격 is None else (
            "110 이상 — 진입 제외·분할 매도 구간 (1-9·6-5·7-5)" if 이격 >= 110
            else "107 초과 — 급등직전 후보 기준(107) 밖 (2-5)" if 이격 > 107
            else "103 초과 — 엔벨로프 3% 밴드 밖 (4-4)" if 이격 > 103
            else "95 이하 — 조정의 끝 구간. 아직 사지 않는다 (1-9)" if 이격 <= 95
            else "95~103 — 교재 기준 가장 가까운 구간"),
        "당일등락률(%)": 등락,
        "2일누적(%)": 이틀,
        # 투자원칙: 이틀 40% 이상은 과열
        "이틀과열": bool(이틀 is not None and 이틀 >= 40),
        "거래대금배수": 배수,
        "거래대금말": 거래대금말,
        "끼(20%급등일수)": sum(
            1 for i in range(1, len(closes))
            if closes[i - 1] > 0 and (closes[i] / closes[i - 1] - 1) * 100 >= SPIKE_PCT),
    }
