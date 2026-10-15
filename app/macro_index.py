"""
===========================================================
  지수 매크로  —  필수 장표
===========================================================

투자원칙 a: "시장분위기 = 매크로 무조건 확인(나스닥 + 유가 + 환율)"
교재 9-1 주가지수 보는 법 / 9-2 상승장·하락장·폭락장 대응 / 9-3 금리·환율·원자재
     4-6 VIX 공포지수

[ 왜 야후인가 ]
  키가 필요 없고 **지수 원본**을 준다 (대용 ETF 가 아니다).
  토스 Open API 는 지수 심볼을 받지 않고, 해외 IP 도 막는다 → 수집 런너에서 못 쓴다.
  pykrx 의 `get_index_ohlcv` 는 KRX 로그인이 필요하다 → 로컬에서 안 돌아간다.
  야후는 세 환경 전부에서 같은 값을 준다. ^KS11 ^KQ11 ^IXIC ^GSPC ^SOX ^VIX
  ^TNX CL=F GC=F KRW=X 005930.KS 000660.KS 전부 실측 통과.

[ 이 모듈의 산출물 두 가지 ]
  1. 판정   지수별 추세·20선 위치·RSI·52주 위치  →  화면 표
  2. 캔들   250봉 OHLC  →  docs/data/charts/*.json  (화면에서 캔들차트로 그린다)

  브라우저에서 야후를 직접 부를 수 없다 (응답에 CORS 헤더가 없다). 그래서
  **수집 단계에서 받아 파일로 구워둔다.** 갱신 주기는 수집 배치와 같다.
===========================================================
"""

import json
import os

import indicators as ind
import ohlcv

HERE = os.path.dirname(os.path.abspath(__file__))
CHART_DIR = os.path.join(HERE, "data", "charts")

CANDLES = 250           # 화면에 그릴 봉수 = 약 1년
HISTORY = 400           # 판정용 조회 봉수 (220일선을 보려면 이만큼)

# (심볼, 이름, 묶음, 비고)  — 비고는 교재 9-3 이 말하는 '무엇에 영향을 주는가'
SYMBOLS = [
    ("^IXIC",     "나스닥",           "해외지수", "국내 성장주·반도체 선행"),
    ("^GSPC",     "S&P 500",          "해외지수", "글로벌 위험선호 기준"),
    ("^SOX",      "필라델피아 반도체", "해외지수", "국내 반도체 선행"),
    ("^KS11",     "코스피",           "국내지수", ""),
    ("^KQ11",     "코스닥",           "국내지수", ""),
    ("^VIX",      "VIX 공포지수",     "변동성",   "4-6 · 20 이상은 불안, 30 이상은 공포"),
    ("^TNX",      "미 10년물 금리",    "매크로",   "9-3 · 오르면 성장주에 부담"),
    ("CL=F",      "WTI 유가",         "매크로",   "9-3 · 원가·화학·정유"),
    ("GC=F",      "금",               "매크로",   "9-3 · 위험회피 자금의 행방"),
    ("KRW=X",     "원/달러",          "매크로",   "9-3 · 오르면 외국인 수급 이탈"),
    ("005930.KS", "삼성전자",         "대표종목", "코스피 대용 · 반도체 대장"),
    ("000660.KS", "SK하이닉스",       "대표종목", "HBM · 반도체 대장"),
]

# VIX 구간 — 교재 4-6
VIX_불안 = 20.0
VIX_공포 = 30.0


def _trend(closes: list[float]) -> dict:
    """교재 9-1 — 지수는 이평선으로 추세를 본다. 추세가 꺾였으면 매매를 멈춘다.

    7-2 [0] "지수는 상승 추세인가? (하락 추세면 매매 중단)"
    """
    ma20 = ind._ma(closes, 20)
    ma60 = ind._ma(closes, 60)
    ma120 = ind._ma(closes, 120)
    last = closes[-1]
    if not (ma20 and ma60):
        return {"추세": "판정불가"}

    if last > ma20 > ma60 and (not ma120 or ma60 > ma120):
        추세 = "상승추세"
    elif last < ma20 < ma60 and (not ma120 or ma60 < ma120):
        추세 = "하락추세"
    elif last > ma20:
        추세 = "20선 위 · 중립"
    else:
        추세 = "20선 아래 · 중립"

    ma5 = ind._ma(closes, 5)
    return {
        "추세": 추세,
        # 교재 9-1 이 매일 보라고 한 것은 5일선·20일선이다. 60·120 은 참고로 둔다
        "MA5": ma5, "MA20": ma20, "MA60": ma60, "MA120": ma120,
        "5선위": None if not ma5 else bool(last > ma5),
        "20선위": bool(last > ma20),
        "20선이격(%)": round((last / ma20 - 1) * 100, 2) if ma20 else None,
        "매매가능": 추세 in ("상승추세", "20선 위 · 중립"),
    }


def one(symbol: str, 이름: str, 묶음: str, 비고: str) -> dict:
    """지수·종목 하나. 못 받으면 상태만 담아 돌려준다 — 전체를 멈추지 않는다."""
    rows = (ohlcv.index_daily(symbol, HISTORY) if not symbol[0].isdigit()
            else ohlcv.index_daily(symbol, HISTORY))
    if len(rows) < 30:
        return {"심볼": symbol, "이름": 이름, "묶음": 묶음, "상태": "조회 실패"}

    closes = [r["종가"] for r in rows]
    last, prev = rows[-1], rows[-2]
    고 = max(r["고가"] for r in rows[-250:])
    저 = min(r["저가"] for r in rows[-250:])

    return {
        "심볼": symbol, "이름": 이름, "묶음": 묶음, "비고": 비고,
        "날짜": last["날짜"],
        "종가": round(last["종가"], 2),
        "전일": round(prev["종가"], 2),
        "등락률": round((last["종가"] / prev["종가"] - 1) * 100, 2) if prev["종가"] else None,
        **_trend(closes),
        # VIX 는 교재가 "일봉으로 판단하지 말라" 고 못 박았다 (4-6).
        # 주봉을 따로 받지 않고 5거래일 평균으로 그 수준을 대신 본다
        "5일평균": round(sum(closes[-5:]) / 5, 2) if len(closes) >= 5 else None,
        "RSI(14)": ind.rsi(closes),
        "52주고": round(고, 2), "52주저": round(저, 2),
        "52주위치(%)": round((last["종가"] - 저) / (고 - 저) * 100, 1) if 고 > 저 else None,
        "5일(%)": (round((last["종가"] / closes[-6] - 1) * 100, 2)
                   if len(closes) > 6 else None),
        "20일(%)": (round((last["종가"] / closes[-21] - 1) * 100, 2)
                    if len(closes) > 21 else None),
        "캔들": [{"t": c["날짜"], "o": round(c["시가"], 2), "h": round(c["고가"], 2),
                  "l": round(c["저가"], 2), "c": round(c["종가"], 2)}
                 for c in rows[-CANDLES:]],
    }


def _vix_band(by: dict[str, dict]) -> dict:
    """VIX 구간 판정 — 교재 4-6 원문 그대로.

    **방향을 틀리면 안 된다.** 교재는 VIX 를 "위험 점수" 로 쓰지 않는다.
      20 이하  탐욕 — 신규 중기 매수 중단 · 분할 매도 · 현금 확대
      20~30    평균 — 관망. 단타·스윙은 평소대로
      30 이상  공포 — 준비한 리스트에서 분할 매수 (30 1차 / 40 2차 / 50 적극)

    그리고 **주봉·월봉으로 본다.** "일봉 VIX 로 판단 → X", "VIX 로 단타 → X
    (3년에 한 번 신호)" 가 교재의 금지 항목이다. 그래서 당일 등락률로 판정하지 않고
    최근 5거래일 평균(≒ 주봉 수준)으로 구간만 가른다.
    """
    vix = by.get("^VIX") or {}
    v, 주 = vix.get("종가"), vix.get("5일평균")
    기준 = 주 if 주 is not None else v
    if 기준 is None:
        return {"구간": "판정불가", "사유": "VIX 를 받지 못했다"}

    if 기준 >= 50:
        구간, 행동 = "공포 — 적극", "준비한 리스트에서 적극 매수 (4-6: VIX 50)"
    elif 기준 >= 40:
        구간, 행동 = "공포 — 2차", "분할 매수 2차 (4-6: VIX 40)"
    elif 기준 >= VIX_공포:
        구간, 행동 = "공포 — 1차", "분할 매수 시작 (4-6: VIX 30)"
    elif 기준 >= VIX_불안:
        구간, 행동 = "평균", "관망. 단타·스윙은 평소대로 (4-6)"
    elif 기준 > 10:
        구간, 행동 = "탐욕", "신규 중기 매수 중단 · 보유분 분할 매도 · 현금 확대 (4-6)"
    else:
        구간, 행동 = "탐욕 — 극단", "중기 보유분 정리 완료 (4-6: VIX 10 근처)"

    return {
        "구간": 구간, "행동": 행동, "VIX": v, "5일평균": 주,
        "주의": ("VIX 는 S&P500 기준이라 국내와 시차가 있다. "
                 "바닥은 'VIX 최고점' 이 아니라 '최고점 이후' 에 온다 (4-6)"),
        "표기": "구간·행동은 <교재 4-6> · 일봉 판단과 단타 사용은 교재가 금지한다",
    }


def breadth(adr: dict | None) -> dict:
    """시장 폭 — 교재 3-6. 상승/하락 종목 수로 오늘의 강도를 가른다.

      상승 > 하락       적극 매매
      하락 > 상승       소극 매매
      하락이 2배 이상   거의 쉰다

    사용자 지시(2026-10-05)로 ADR 은 **참고 지표**다. 그래서 같은 자료를 쓰면서도
    "ADR 판정" 이라고 부르지 않고 **시장 폭**으로 따로 적는다. 판단은 사용자가 한다.
    """
    if not adr:
        return {"판정": "자료 없음"}
    up = int(adr.get("상승") or 0)
    dn = int(adr.get("하락") or 0)
    if up + dn == 0:
        return {"판정": "자료 없음"}

    if up and dn >= up * 2:
        판정, 행동 = "하락이 2배 이상", "거의 쉰다 (3-6)"
    elif dn > up:
        판정, 행동 = "하락 > 상승", "소극 매매 (3-6)"
    else:
        판정, 행동 = "상승 > 하락", "적극 매매 (3-6)"

    return {"판정": 판정, "행동": 행동, "상승": up, "하락": dn,
            "배수": round(dn / up, 2) if up else None,
            "표기": "<교재 3-6> · ADR 은 사용자 지시에 따라 참고 지표로만 쓴다"}


def _index_state(by: dict[str, dict]) -> dict:
    """지수 체크리스트 [매일] 중 자료로 확인 가능한 항목 — 교재 9-1.

    교재가 매일 보라고 한 것은 **일봉 5일선 / 20일선 위인가** 다.
    이전 구현이 쓰던 20·60·120 조합은 교재 항목이 아니었다
    (주말 항목이 주봉 13·20·60·120주다).
    """
    out, 중단 = [], []
    for sym in ("^KS11", "^KQ11"):
        d = by.get(sym) or {}
        if d.get("종가") is None:
            continue
        ma5, ma20 = d.get("MA5"), d.get("MA20")
        row = {
            "이름": d.get("이름"), "종가": d.get("종가"), "등락률": d.get("등락률"),
            "5일선위": None if not ma5 else bool(d["종가"] > ma5),
            "20일선위": None if not ma20 else bool(d["종가"] > ma20),
            "MA5": ma5, "MA20": ma20,
        }
        out.append(row)
        if row["5일선위"] is False:
            중단.append(f"{row['이름']} 5일선 이탈 — 신규 진입 중단·비중 축소 (7-5b) · "
                        "추가 매수 금지 (8-5)")
        if row["20일선위"] is False:
            중단.append(f"{row['이름']} 20일선 아래 (9-1 매일 체크 항목)")
    return {"지수": out, "중단조건": 중단}


def _sector_bias(by: dict[str, dict]) -> dict:
    """지수 방향 → 어떤 섹터를 보는가. 교재 5-3.

      지수 양봉 → 시총 큰 섹터 (반도체·2차전지·AI·로봇·바이오)
      지수 음봉 → 시총 작은 단기 테마 (방산·원자재·유가·비료·정책)
    """
    chg = (by.get("^KS11") or {}).get("등락률")
    if chg is None:
        return {"판정": "자료 없음"}
    if chg > 0:
        return {"판정": "지수 양봉",
                "볼섹터": "시총 큰 섹터 — 반도체·2차전지·AI·로봇·바이오",
                "표기": "<교재 5-3>"}
    return {"판정": "지수 음봉",
            "볼섹터": "시총 작은 단기 테마 — 방산·원자재·유가·비료·정책",
            "표기": "<교재 5-3>"}


def _position(vix: dict, bre: dict, index: dict) -> dict:
    """포지션 운용 — 사용자 투자원칙 <확정> 을 교재 자료 위에 올린다.

    사용자 규칙(trading-desk):
      매크로 변동성 높음 → 현금비중 확보 + 초단타
      매크로 변동성 낮음 → 비중 확대 + 스윙 또는 초단타 병행

    변동성을 무엇으로 재는지는 사용자 규칙에 없다. 그래서 **교재가 명시한 매매 중단
    조건 개수**로 센다 — 세는 방식은 <제안> 이고, 조건 자체는 <교재> 다.
    """
    위험 = list(index.get("중단조건") or [])
    if bre.get("판정") in ("하락이 2배 이상", "하락 > 상승"):
        위험.append(f"시장 폭 {bre['판정']} — {bre['행동']}")

    등급 = "높음" if len(위험) >= 2 else "보통" if len(위험) == 1 else "낮음"
    운용 = ("현금비중 확보 + 초단타" if 등급 == "높음"
            else "비중 확대 + 스윙 또는 초단타 병행" if 등급 == "낮음"
            else "둘 사이 — 비중을 늘리지 않고 초단타 위주 <제안>")

    return {
        "등급": 등급, "위험요인": 위험, "포지션운용": 운용,
        "VIX구간": vix.get("구간"), "VIX행동": vix.get("행동"),
        "표기": ("운용 지침(높음·낮음)은 <사용자 확정> · 중단 조건은 "
                 "<교재 7-5b·8-5·9-1·3-6> · 등급을 조건 개수로 세는 것은 <제안>"),
    }


def _lead(by: dict[str, dict]) -> list[dict]:
    """선행 관계 한 줄씩. 교재 9-3 이 말하는 영향 경로를 **값과 함께** 적는다.

    해석을 단정하지 않는다 — 어제 무엇이 움직였고 그게 무엇에 걸리는지만 적는다.
    """
    out = []
    for sym, 경로 in (("^SOX", "국내 반도체(삼성전자·SK하이닉스)"),
                      ("^IXIC", "국내 성장주·AI 테마"),
                      ("^TNX", "성장주 밸류에이션 — 오르면 부담"),
                      ("CL=F", "화학·정유 원가"),
                      ("KRW=X", "외국인 수급")):
        d = by.get(sym)
        if not d or d.get("등락률") is None:
            continue
        out.append({"지표": d["이름"], "등락률": d["등락률"],
                    "영향경로": 경로, "추세": d.get("추세")})
    return out


def snapshot(save_charts: bool = True, adr: dict | None = None) -> dict:
    """지수 매크로 전체. 캔들은 파일로 따로 굽고 판정만 payload 에 담는다.

    캔들을 payload 에 넣으면 latest.json 이 수 MB 로 불어난다. 그래서 분리한다.

    adr 을 주면 교재 3-6 의 **시장 폭**(상승/하락 종목 수) 판정까지 같이 낸다.
    """
    rows, by = [], {}
    for sym, 이름, 묶음, 비고 in SYMBOLS:
        d = one(sym, 이름, 묶음, 비고)
        by[sym] = d
        rows.append(d)

    if save_charts:
        os.makedirs(CHART_DIR, exist_ok=True)
        for d in rows:
            if not d.get("캔들"):
                continue
            name = d["심볼"].replace("^", "idx_").replace("=", "_").replace(".", "_")
            with open(os.path.join(CHART_DIR, f"{name}.json"), "w", encoding="utf-8") as fh:
                json.dump({"심볼": d["심볼"], "이름": d["이름"],
                           "캔들": d["캔들"]}, fh, ensure_ascii=False)

    표 = [{k: v for k, v in d.items() if k != "캔들"} for d in rows]
    받음 = [d for d in 표 if d.get("종가") is not None]

    vix = _vix_band(by)
    bre = breadth(adr)
    idx = _index_state(by)

    return {
        "지표": 표,
        "받음": len(받음), "전체": len(표),
        "VIX": vix,                      # 교재 4-6 구간 — 위험 점수가 아니다
        "시장폭": bre,                    # 교재 3-6 상승/하락 종목 수
        "지수상태": idx,                  # 교재 9-1 매일 체크 (5일선·20일선)
        "섹터선택": _sector_bias(by),      # 교재 5-3 지수 양봉/음봉
        "변동성": _position(vix, bre, idx),  # 사용자 확정 운용 지침
        "선행": _lead(by),
        "미확인": [
            "미국 지수 선물 (7-1·9-1·9-3) — 야후 연속선물 심볼 미검증",
            "국내 변동성지수 VKOSPI (9-1) — 야후에 없음",
            "다우 (9-1)", "예탁금·신용융자 잔고 (3-6·9-1)",
            "CNN Fear & Greed (4-6)", "버핏지수 (9-3)",
        ],
        "차트파일": {d["심볼"]: d["심볼"].replace("^", "idx_")
                     .replace("=", "_").replace(".", "_") + ".json"
                     for d in rows if d.get("캔들")},
    }
