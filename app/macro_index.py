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

    return {
        "추세": 추세,
        "MA20": ma20, "MA60": ma60, "MA120": ma120,
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


def _volatility(by: dict[str, dict]) -> dict:
    """매크로 변동성 → 포지션 운용. <확정 규칙>

    trading-desk:
      높음 → 현금비중 확보 + 초단타
      낮음 → 비중 확대 + 스윙 또는 초단타 병행

    변동성을 무엇으로 재는가 — 세 가지를 센다.
      VIX 수준 (4-6) · 국내지수가 20선 아래인가 (9-1) · 당일 낙폭이 1.5% 넘는가
    """
    점수, 근거 = 0, []

    vix = by.get("^VIX") or {}
    v = vix.get("종가")
    if v is not None:
        if v >= VIX_공포:
            점수 += 2
            근거.append(f"VIX {v} — 30 이상 공포 구간 (4-6)")
        elif v >= VIX_불안:
            점수 += 1
            근거.append(f"VIX {v} — 20 이상 불안 구간 (4-6)")
        else:
            근거.append(f"VIX {v} — 20 아래, 안정 구간")

    국내 = [by.get("^KS11") or {}, by.get("^KQ11") or {}]
    아래 = [x for x in 국내 if x.get("20선위") is False]
    if len(아래) == 2:
        점수 += 2
        근거.append("코스피·코스닥 모두 20선 아래 — 교재 9-1 기준 추세 이탈")
    elif 아래:
        점수 += 1
        근거.append(f"{아래[0].get('이름')} 20선 아래")
    else:
        근거.append("국내지수 둘 다 20선 위")

    낙폭 = [x for x in 국내 if (x.get("등락률") or 0) <= -1.5]
    if 낙폭:
        점수 += 1
        근거.append(" · ".join(f"{x['이름']} {x['등락률']}%" for x in 낙폭)
                    + " — 당일 낙폭 1.5% 초과")

    환율 = by.get("KRW=X") or {}
    if (환율.get("등락률") or 0) >= 0.5:
        점수 += 1
        근거.append(f"원/달러 {환율.get('등락률')}% 상승 — 9-3: 외국인 수급 이탈 압력")

    등급 = "높음" if 점수 >= 3 else "보통" if 점수 == 2 else "낮음"
    운용 = ("현금비중 확보 + 초단타" if 등급 == "높음"
            else "비중 확대 + 스윙 또는 초단타 병행" if 등급 == "낮음"
            else "둘 사이 — 비중을 늘리지 않고 초단타 위주 <제안>")

    return {"등급": 등급, "점수": 점수, "근거": 근거, "포지션운용": 운용,
            "표기": "높음/낮음 운용 지침은 <확정> · '보통' 구간 해석은 <제안>"}


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


def snapshot(save_charts: bool = True) -> dict:
    """지수 매크로 전체. 캔들은 파일로 따로 굽고 판정만 payload 에 담는다.

    캔들을 payload 에 넣으면 latest.json 이 수 MB 로 불어난다. 그래서 분리한다.
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

    return {
        "지표": 표,
        "받음": len(받음), "전체": len(표),
        "변동성": _volatility(by),
        "선행": _lead(by),
        "차트파일": {d["심볼"]: d["심볼"].replace("^", "idx_")
                     .replace("=", "_").replace(".", "_") + ".json"
                     for d in rows if d.get("캔들")},
    }
