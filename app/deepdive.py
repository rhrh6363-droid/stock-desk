"""
===========================================================
  심층분석  —  단일종목 · 섹터
===========================================================

차트 · 시장 · 모멘텀 · 뉴스 네 가지를 한 종목(또는 한 섹터)에 모아 붙인다.

[ 무엇을 쓰는가 ]
  차트   indicators.py   교재 7-3 돌파 / 7-2 눌림목 / 1-5 매물대 / 1-4 라운드피겨
  모멘텀 indicators.py   RSI(4-1) · 볼밴 · 이격도(1-9) · 거래대금 추세(1-7)
  뉴스   news.py         구글뉴스 RSS. 여기서는 **재료의 성격**을 교재 5-5 로 가른다
  시장   payload         지수 · ADR · 매크로 (수집기가 이미 받아둔 것)

[ 출력 원칙 — trading-desk 스킬 그대로 ]
  "사라/팔아라" 를 쓰지 않는다. 체크카드 통과/미달과 척도만 돌려준다.
  확인 못 한 값은 "확인 불가" 로 둔다. 그럴듯한 숫자를 지어내지 않는다.
  사용자 규칙이 아닌 내 추론은 <제안> 으로 표시한다.

[ 분석 대상은 두 군데서 온다 ]
  watchlist.csv   사용자가 적어둔 고정 관심종목·섹터
  당일 대장주     그날 A+B 로 잡힌 거래대금 1위 후보들
===========================================================
"""

import json
import os
import re
from datetime import datetime

import indicators as ind
import ohlcv

HERE = os.path.dirname(os.path.abspath(__file__))
WATCHLIST = os.path.join(HERE, "watchlist.csv")

LOOKBACK = 400              # 일봉 조회 봉수. 220일선·52주 신고가를 보려면 이만큼 필요하다
NEWS_PER = 6                # 종목당 기사 수

# ── 교재 5-5 "뉴스와 재료 활용" — 재료의 성격을 가르는 말들
# "개발 중 / 출품 / 전시회 / 협력 논의" 는 교재가 직접 "새 뉴스 아님" 으로 분류한다
약한재료 = re.compile(
    r"개발\s*중|개발\s*착수|출품|전시회|참가|시연|협력\s*논의|MOU|업무협약|"
    r"검토|추진|기대|전망|예정|목표|계획|협의|논의|방침")
# 구체적 숫자 + 기한 + 처음 나온 정책·계약 = ★ 새 뉴스
강한재료 = re.compile(
    r"수주|계약\s*체결|공급\s*계약|납품|양산|승인|허가|판매\s*개시|출시|"
    r"특허\s*등록|임상\s*\d|품목허가|낙찰|선정|인수|증설|준공|가동")
금액 = re.compile(r"(\d[\d,.]*)\s*(조|억|백만|천만|million|billion)")
정책 = re.compile(r"정책|예산|법안|국책|정부|지원금|세액공제|규제\s*완화|관세|조달")


# ────────────────────────────────────────────────
# 분석 대상 명단
# ────────────────────────────────────────────────
def load_watchlist() -> list[dict]:
    """watchlist.csv — 사용자가 직접 적는 분석 대상.

    열: 구분(종목|섹터) · 코드 · 이름 · 시장(KOSPI|KOSDAQ) · 비고
    파일이 없으면 빈 명단. 그래도 당일 대장주는 자동으로 분석된다.
    """
    if not os.path.exists(WATCHLIST):
        return []
    out = []
    try:
        import pandas as pd
        df = pd.read_csv(WATCHLIST, encoding="utf-8-sig", dtype=str).fillna("")
    except Exception as exc:
        print(f"  watchlist 읽기 실패: {type(exc).__name__}")
        return []
    for _, r in df.iterrows():
        구분 = (r.get("구분") or "종목").strip()
        이름 = (r.get("이름") or "").strip()
        코드 = (r.get("코드") or "").strip()
        if not 이름 and not 코드:
            continue
        out.append({"구분": 구분, "코드": 코드.zfill(6) if 코드 and 구분 == "종목" else 코드,
                    "이름": 이름, "시장": (r.get("시장") or "KOSPI").strip(),
                    "비고": (r.get("비고") or "").strip(), "출처": "watchlist"})
    return out


def targets(payload: dict, limit_leader: int = 3) -> list[dict]:
    """watchlist + 당일 대장주. 중복은 코드/이름으로 합친다."""
    picked = load_watchlist()
    seen = {t["코드"] or t["이름"] for t in picked}

    # 당일 대장주 후보 — 주도업종 거래대금 1위들
    for c in (payload.get("대장주후보") or [])[:limit_leader]:
        이름 = c.get("종목명")
        코드 = str(c.get("티커") or "").zfill(6) if c.get("티커") else ""
        key = 코드 or 이름
        if not 이름 or key in seen:
            continue
        seen.add(key)
        picked.append({"구분": "종목", "코드": 코드, "이름": 이름,
                       "시장": c.get("시장") or "KOSPI",
                       "비고": f"당일 대장주 후보 · {c.get('대섹터') or ''}".strip(" ·"),
                       "출처": "당일대장주"})
    return picked


def _ticker_of(이름: str, rows: list[dict]) -> str:
    """수집 결과에서 종목명 → 티커. 없으면 pykrx 로 역조회한다."""
    for r in rows or []:
        if r.get("종목명") == 이름 and r.get("티커"):
            return str(r["티커"]).zfill(6)
    return ""


def intraday(code: str, minutes: int = 5) -> dict:
    """장중 분봉 — 토스만 줄 수 있고, **한국 IP 에서만 된다.**

    토스 Open API 는 해외 IP 를 403 으로 막는다. GitHub 런너(미국)에서는 못 받으므로
    self-hosted 러너(사용자 PC)나 로컬 실행일 때만 값이 들어온다.
    키가 없거나 차단되면 사유만 담아 돌려준다 — 전체를 멈추지 않는다.

    교재 6-3 장중 종목 선정 / 투자원칙 1.3 "장중 대장주가 바뀌기도 하니
    거래대금 위주 모니터링" 이 요구하는 자료다.
    """
    import toss

    if not toss.available():
        return {"상태": "토스 키 없음 — 분봉은 한국에서 돌릴 때만 붙습니다"}
    try:
        mins = toss.candles(code, "1m", 300)
    except Exception as exc:
        return {"상태": f"분봉 조회 실패: {type(exc).__name__}"}
    if not mins:
        return {"상태": "분봉 없음 — 해외 IP 차단(403)이거나 장외 시간입니다"}

    bars = toss.resample(mins, minutes)
    if len(bars) < 3:
        return {"상태": "분봉이 부족합니다"}

    closes = [b["종가"] for b in bars]
    vols = [b["거래량"] for b in bars]
    평균 = sum(vols[:-1]) / max(1, len(vols) - 1)
    시가 = bars[0]["시가"]
    고 = max(b["고가"] for b in bars)

    return {
        "주기": f"{minutes}분봉",
        "봉수": len(bars),
        "현재가": bars[-1]["종가"],
        "시가대비(%)": round((closes[-1] / 시가 - 1) * 100, 2) if 시가 else None,
        "고가대비(%)": round((closes[-1] / 고 - 1) * 100, 2) if 고 else None,
        "최근거래량배수": round(vols[-1] / 평균, 2) if 평균 else None,
        "RSI(14)": ind.rsi(closes),
        "캔들": [{"t": b["시각"], "o": b["시가"], "h": b["고가"],
                  "l": b["저가"], "c": b["종가"], "v": b["거래량"]} for b in bars[-80:]],
    }


def _market_cap(code: str, date: str) -> float | None:
    """시가총액(억). KRX 로그인이 있을 때만 나온다 — 없으면 None 으로 둔다."""
    try:
        from pykrx import stock
        df = stock.get_market_cap_by_date(date, date, code)
        if df is not None and not df.empty:
            return round(float(df.iloc[-1]["시가총액"]) / 1e8, 1)
    except Exception:
        pass
    return None


# ────────────────────────────────────────────────
# 뉴스 — 교재 5-5 로 재료의 성격을 가른다
# ────────────────────────────────────────────────
def news_read(이름: str, 보조: str = "") -> dict:
    """기사 제목만으로 판정할 수 있는 것: 보도 집중도 · 재료의 지속성 · 금액 유무.

    교재 5-5 체크카드에서 데이터로 확인 가능한 항목만 가져왔다.
    "수주 금액이 매출액 대비 몇 %인가" 는 매출 자료가 없어 넣지 않았다 — 기준 없음.
    """
    import news

    items = news.search(f"{이름} 주가" if not 보조 else f"{이름} {보조}", limit=NEWS_PER)
    if not items:
        items = news.search(이름, limit=NEWS_PER)
    if not items:
        return {"상태": "기사 없음", "기사": []}

    매체 = {(it.get("출처") or "").strip() for it in items if (it.get("출처") or "").strip()}
    강 = [it for it in items if 강한재료.search(it.get("제목") or "")]
    약 = [it for it in items if 약한재료.search(it.get("제목") or "")]
    돈 = [it for it in items if 금액.search(it.get("제목") or "")]
    정 = [it for it in items if 정책.search(it.get("제목") or "")]

    성격 = ("★ 구체적 재료 — 계약·승인·양산 같은 확정 사건" if 강
            else "정책·예산 재료" if 정
            else "약한 재료 — 교재 5-5: 개발 중·출품·협력 논의는 '새 뉴스' 가 아니다" if 약
            else "성격 판별 어려움 — 제목만으로는 재료를 가를 수 없다")

    return {
        "기사수": len(items),
        "매체수": len(매체),
        "도배": bool(len(매체) >= 3),
        "도배말": ("여러 언론사에 걸쳐 보도됐다" if len(매체) >= 3
                   else "한두 매체만 썼다 — 교재 5-5 는 이걸 먼저 보라고 한다"),
        "재료성격": 성격,
        "지속성": ("이어지는 재료로 볼 근거가 있다" if 강 or 정
                   else "1회성일 가능성" if 약 else "판정불가"),
        "금액언급": bool(돈),
        "강한재료기사": [{"제목": it["제목"], "링크": it["링크"], "출처": it.get("출처", "")}
                         for it in 강[:3]],
        "기사": [{"제목": it["제목"], "링크": it["링크"],
                  "출처": it.get("출처", ""), "날짜": it.get("날짜", "")}
                 for it in items[:NEWS_PER]],
        "검색": "https://news.google.com/search?q=" + 이름,
    }


# ────────────────────────────────────────────────
# 종합 — 국면 분기
# ────────────────────────────────────────────────
def _phase(hg: dict, ez: dict, pb: dict, mo: dict) -> dict:
    """돌파 국면인가 눌림목 국면인가. 교재는 이 둘을 전혀 다르게 다룬다.

    섞으면 전부 틀어지므로 어느 교재를 적용할지 먼저 고정한다.
    """
    전고대비 = (ez or {}).get("전고점대비(%)")
    if 전고대비 is None:
        return {"국면": "판정불가", "적용교재": None,
                "설명": "일봉이 부족해 국면을 가를 수 없다"}

    if hg.get("돌파") and not hg.get("경신중"):
        국면, 교재 = "돌파 국면", "7-3 신고가·전고점 돌파"
        말 = f"{hg.get('신고가격')} 고점을 깼다. 연속경신 {hg.get('연속경신일')}일"
    elif hg.get("경신중"):
        국면, 교재 = "경신 중", "7-3 (단, 교재는 '신고가 매매가 아니다' 로 분류)"
        말 = f"{hg.get('연속경신일')}일째 경신 중 — 교재 7-3 PART B 가 제외하는 자리"
    elif 전고대비 >= -10:
        국면, 교재 = "돌파 직전", "7-3 (매수자리 1번)"
        말 = f"전고점 대비 {전고대비}% — 돌파를 시도할 수 있는 거리"
    else:
        국면, 교재 = "눌림목 국면", "7-2 눌림목 매매"
        말 = f"전고점 대비 {전고대비}% — 돌파가 아니라 눌림목으로 봐야 한다"

    주된체크 = (pb if 국면 == "눌림목 국면" else None)
    return {"국면": 국면, "적용교재": 교재, "설명": 말,
            "주된체크": "7-2 눌림목 체크" if 주된체크 else "7-3 돌파 5조건"}


def _verdict(bo: dict, pb: dict, mo: dict, phase: dict, rr: dict) -> dict:
    """판단을 선언하지 않는다. **조건이 몇 개 성립했고 무엇이 위험한지**만 적는다."""
    주 = pb if phase.get("국면") == "눌림목 국면" else bo
    통과, 전체 = 주.get("통과수"), 주.get("전체")

    위험 = []
    r = mo.get("RSI(14)")
    if r is not None and r >= 70:
        위험.append(f"RSI {r} — 70 이상 과매수 (교재 4-1: 그 자리에서 창을 닫는다)")
    if (mo.get("볼밴") or {}).get("위치") in ("상단권", "상단이탈"):
        위험.append(f"볼밴 {mo['볼밴']['위치']} ({mo['볼밴'].get('%B')}%) — 밴드 상단 위험")
    이격 = mo.get("이격도")
    if 이격 is not None and 이격 >= 110:
        위험.append(f"이격도 {이격} — 110 이상은 고점 지향 (1-9)")
    if mo.get("이틀과열"):
        위험.append(f"이틀 누적 {mo.get('2일누적(%)')}% — 40% 이상 과열 (투자원칙)")
    추세 = mo.get("거래대금추세")
    if 추세 is not None and 추세 <= 0.7:
        위험.append(f"거래대금이 과거 평균의 {추세}배 — 자금이 빠지고 있다")

    막힘 = rr.get("목표가까지_저항밴드") or []
    if 막힘:
        위험.append(f"목표가 아래 매물대 {len(막힘)}개 — 익절 폭까지 길이 막혀 있다")
    if rr.get("구조손절가") is None and "이미 충족" in (rr.get("구조상태") or ""):
        위험.append("첫 저점을 이미 깨고 내려왔다 — 교재 7-3 PART G 매도 조건이 충족된 상태")

    말 = (f"{phase.get('적용교재')} 기준 {통과}/{전체} 항목 통과."
          if 통과 is not None else "체크 항목을 계산할 수 없었다.")
    if 위험:
        말 += f" 위험 요인 {len(위험)}개."
    else:
        말 += " 위에 적은 척도 중 경고 구간에 걸린 것은 없다."

    return {"통과": 통과, "전체": 전체, "요약": 말, "위험요인": 위험,
            "표기": "<제안> — 조건 성립 여부만 센 것이다. 진입 판단은 사용자가 한다"}


# ────────────────────────────────────────────────
# 종목 하나
# ────────────────────────────────────────────────
def stock_one(대상: dict, date: str, rows: list[dict] | None = None) -> dict:
    """한 종목 심층분석. 실패해도 예외를 던지지 않고 사유를 담아 돌려준다."""
    이름 = 대상.get("이름") or ""
    코드 = 대상.get("코드") or _ticker_of(이름, rows or [])
    if not 코드:
        return {"이름": 이름, "상태": "종목코드를 찾지 못했다 — watchlist.csv 에 코드를 적어주세요"}

    market = "KQ" if str(대상.get("시장", "")).upper().startswith("KOSDAQ") else "KS"
    candles = ohlcv.daily(코드, date, LOOKBACK, market=market)
    if len(candles) < 70:
        return {"이름": 이름, "코드": 코드,
                "상태": f"일봉이 {len(candles)}봉뿐 — 판정에 필요한 70봉을 못 채웠다"}

    last = candles[-1]
    수집행 = next((r for r in (rows or []) if r.get("종목명") == 이름), {})
    시총 = 수집행.get("시총(억)") or _market_cap(코드, date)

    hg = ind.high_grade(candles)
    ez = ind.entry_zone(candles)
    lq = ind.loud_or_quiet(candles)
    bo = ind.breakout_odds(candles, 시총)
    pb = ind.pullback(candles)
    mo = ind.momentum(candles)
    rr = ind.risk_reward(candles)
    phase = _phase(hg, ez, pb, mo)

    return {
        "이름": 이름, "코드": 코드, "시장": 대상.get("시장"),
        "출처": 대상.get("출처"), "비고": 대상.get("비고"),
        "기준일": last["날짜"], "봉수": len(candles),
        "현재가": last["종가"],
        "당일등락률(%)": mo.get("당일등락률(%)"),
        "시총(억)": 시총,
        "거래대금(억)": (round(수집행.get("거래대금(억)"), 0)
                         if 수집행.get("거래대금(억)") is not None
                         else round(last.get("추정거래대금", 0) / 1e8, 0)),
        "거래대금추정": 수집행.get("거래대금(억)") is None,
        "수급주체": 수집행.get("수급주체"),
        "섹터": 수집행.get("대섹터"), "세부섹터": 수집행.get("세부섹터"),

        "국면": phase,
        "차트": {
            "신고가": hg, "매수자리": ez, "요란조용": lq,
            "돌파5조건": bo, "눌림목체크": pb,
            "매물대": ind.supply_bands(candles),
            "라운드피겨": ind.round_figure(last["종가"]),
            "첫저점": ind.first_pivot_low(candles),
            "MA": {k: pb.get(k) for k in ("MA5", "MA20", "MA60", "MA220")},
        },
        "모멘텀": mo,
        "손익비": rr,
        "뉴스": news_read(이름, 수집행.get("대표키워드") or ""),
        # 분봉은 한국 IP 에서만 들어온다 (토스가 해외를 막는다)
        "분봉": intraday(코드),
        "종합": _verdict(bo, pb, mo, phase, rr),
        # 화면에서 캔들을 그릴 자료. 1년치면 충분하다
        "캔들": [{"t": c["날짜"], "o": c["시가"], "h": c["고가"],
                  "l": c["저가"], "c": c["종가"], "v": c["거래량"]}
                 for c in candles[-250:]],
        "차트이미지": {
            # 네이버가 알아서 갱신하는 이미지 — CORS 가 없는 <img> 라 정적 사이트에서도 뜬다
            "일봉": f"https://ssl.pstatic.net/imgfinance/chart/item/candle/day/{코드}.png",
            "3개월": f"https://ssl.pstatic.net/imgfinance/chart/item/area/month3/{코드}.png",
            "네이버": f"https://finance.naver.com/item/main.naver?code={코드}",
            "트레이딩뷰": f"KRX:{코드}",
        },
    }


# ────────────────────────────────────────────────
# 섹터 하나
# ────────────────────────────────────────────────
def sector_one(섹터명: str, payload: dict) -> dict:
    """섹터 심층분석.

    **ADR 은 종목 하나에 쓸 수 없다** (1÷0 아니면 0÷1). 좁힐 수 있는 최소 단위가
    섹터다 — trading-desk 원칙. 그래서 섹터 레벨에서만 상승/하락 종목수를 센다.
    """
    그룹 = next((g for g in (payload.get("그룹") or [])
                 if g.get("대섹터") == 섹터명 or g.get("세부섹터") == 섹터명), None)
    if not 그룹:
        # 오늘 특징주가 없더라도 재료는 돌고 있을 수 있다. 뉴스만이라도 붙여 둔다 —
        # 빈 카드를 내놓는 것보다 "거래대금은 안 붙었는데 기사는 이만큼" 이 쓸모 있다
        return {"이름": 섹터명,
                "상태": "오늘 이 섹터에 특징주가 잡히지 않았다 — 거래대금 집계 없음",
                "뉴스": news_read(섹터명, "테마")}

    종목 = 그룹.get("종목") or []
    up = sum(1 for r in 종목 if (r.get("등락률(%)") or 0) > 0)
    dn = sum(1 for r in 종목 if (r.get("등락률(%)") or 0) < 0)
    rsis = [r.get("rsi") for r in 종목 if r.get("rsi") is not None]

    # 전일 대비 — 섹터가 살아 있는지 끝물인지
    rep = payload.get("보고서") or {}
    변화 = next((x for x in ((rep.get("섹터변화") or {}).get("증감") or [])
                 if x.get("대섹터") == 섹터명), None)

    키워드 = {}
    for r in 종목:
        for k in (r.get("키워드") or []):
            키워드[k] = 키워드.get(k, 0) + 1

    return {
        "이름": 섹터명,
        "등급": 그룹.get("등급"), "분류": 그룹.get("분류"),
        "종목수": 그룹.get("종목수"), "합산거래대금": 그룹.get("합산거래대금"),
        "대장주": 그룹.get("대장주"),
        "평균상승률": 그룹.get("평균상승률"),
        "섹터ADR": round(up / dn * 100, 1) if dn else None,
        "상승": up, "하락": dn,
        "평균RSI": round(sum(rsis) / len(rsis), 1) if rsis else None,
        "전일대비": 변화,
        "살아있나": (None if not 변화 else
                     ("거래대금이 늘고 있다 — 아직 살아 있다" if (변화.get("증감") or 0) > 0
                      else "거래대금이 줄고 있다 — 끝물 가능성")),
        "공통키워드": sorted(키워드.items(), key=lambda x: -x[1])[:6],
        "종목": [{"종목명": r.get("종목명"), "거래대금(억)": r.get("거래대금(억)"),
                  "등락률(%)": r.get("등락률(%)"), "rsi": r.get("rsi"),
                  "수급주체": r.get("수급주체"), "조건": r.get("조건"),
                  "대표키워드": r.get("대표키워드")} for r in 종목[:12]],
        "뉴스": news_read(섹터명, "테마"),
        "표기": "섹터 ADR 은 특징주로 잡힌 종목만 센 것이다 — 섹터 전체가 아니다",
    }


# ────────────────────────────────────────────────
# 파이프라인 입구
# ────────────────────────────────────────────────
def build(payload: dict, date: str) -> dict:
    """watchlist + 당일 대장주를 전부 분석해서 한 덩어리로 돌려준다.

    캔들은 payload 에 넣지 않고 data/charts/<코드>.json 으로 따로 굽는다 —
    종목 하나당 250봉이면 latest.json 이 금방 수 MB 가 된다.
    """
    rows = [r for g in (payload.get("그룹") or []) for r in (g.get("종목") or [])]
    대상들 = targets(payload)

    종목결과, 섹터결과 = [], []
    for t in 대상들:
        try:
            if t["구분"] == "섹터":
                섹터결과.append(sector_one(t["이름"], payload))
            else:
                종목결과.append(stock_one(t, date, rows))
        except Exception as exc:
            (섹터결과 if t["구분"] == "섹터" else 종목결과).append(
                {"이름": t.get("이름"), "상태": f"분석 실패: {type(exc).__name__}: {exc}"})

    chart_dir = os.path.join(HERE, "data", "charts")
    os.makedirs(chart_dir, exist_ok=True)
    for d in 종목결과:
        candles = d.pop("캔들", None)
        if not candles or not d.get("코드"):
            continue
        with open(os.path.join(chart_dir, f"{d['코드']}.json"), "w", encoding="utf-8") as fh:
            json.dump({"심볼": d["코드"], "이름": d["이름"], "캔들": candles},
                      fh, ensure_ascii=False)
        d["차트파일"] = f"{d['코드']}.json"

    return {
        "생성시각": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "기준일": date,
        "종목": 종목결과,
        "섹터": 섹터결과,
        "대상수": {"종목": len(종목결과), "섹터": len(섹터결과),
                   "watchlist": sum(1 for t in 대상들 if t["출처"] == "watchlist"),
                   "당일대장주": sum(1 for t in 대상들 if t["출처"] == "당일대장주")},
    }
