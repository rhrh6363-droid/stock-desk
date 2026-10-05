"""
===========================================================
  섹터 매핑 + 주도업종 판정
===========================================================

사용자가 구글시트 Apps Script 로 돌리던 로직을 그대로 옮긴 것이다.
새로 설계하지 않는다.

[ 매핑 — Waterfall 5단계 ] 위에서부터 먼저 맞는 것을 채택
  1. '종목' 열에 직접 등록된 종목명   ← 종목명 완전일치
  2. 대장주1~5 종목명                 ← 종목명 완전일치
  3. 세부섹터명 토큰                  ← 그 종목의 '키워드'와 대조
  4. '키워드' 열                      ← 그 종목의 '키워드'와 대조
  5. '비고' 열의 명시 키워드           ← 그 종목의 '키워드'와 대조

**3~5단계는 종목명이 아니라 종목의 키워드와 맞춘다.**
종목명에 대고 부분일치를 하면 비고의 '제조·전자 조립' 에서 '전자'가 튀어나와
성호전자·빛샘전자·덕우전자가 전부 로봇으로 들어간다. (실제로 그렇게 틀렸다.)
비고의 서술 문구는 매칭에 쓰지 않는다 — 화면 표시용이다.

종목 키워드는 뉴스(네이버 검색 API)에서 뽑거나 RAW 시트의 '키워드' 열에서 받는다.
키워드가 없으면 3~5단계는 동작하지 않고 미분류로 남는다. 그게 정상이다 —
틀린 섹터에 넣는 것보다 미분류가 낫다.

[ 판정 — 시트에 적힌 기준 그대로 ]
  같은 대섹터에 3종목 이상  → ★★★ 주도업종
  2종목 이하               → ○ 개별이슈
  섹터 합산 거래대금 내림차순 = 순위
  섹터 내 거래대금 1위      = 그 섹터의 대장주
===========================================================
"""

import os
import re

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DICT_FILE = os.path.join(HERE, "섹터사전.csv")

LEADER_COLS = ["대장주1", "대장주2", "대장주3", "대장주4", "대장주5"]
SPLIT = re.compile(r"[·\-/()\s,]+")

주도_최소종목수 = 3          # 시트 기준 <확정>

# 너무 흔해서 섹터를 가르지 못하는 토큰. 매칭에서 제외한다.
STOPWORDS = {
    "전자", "에너지", "건설", "소재", "시스템", "산업", "기술", "전기", "화학",
    "반도체", "부품", "장비", "솔루션", "코리아", "홀딩스", "그룹", "중공업",
    "제조", "조립", "수요", "확대", "급증", "국내", "글로벌", "기대", "수혜",
    "대장", "핵심", "전문", "중심", "주도", "최상위권", "거래대금", "전환",
}


def _tokens(text: str) -> list[str]:
    if not text:
        return []
    return [t for t in SPLIT.split(str(text)) if len(t) >= 2]


def _multi(cell) -> list[str]:
    """'A|B|C' 또는 'A, B, C' 를 리스트로."""
    if cell is None or (isinstance(cell, float) and pd.isna(cell)):
        return []
    return [p.strip() for p in re.split(r"[|,]", str(cell)) if p.strip()]


def load_dictionary(path: str = DICT_FILE) -> pd.DataFrame:
    """섹터 사전. 구글시트가 연결되면 sheets.read_sector_dict() 가 대신 준다."""
    if not os.path.exists(path):
        return pd.DataFrame(columns=["대섹터", "세부섹터"] + LEADER_COLS + ["비고", "종목", "키워드"])

    df = pd.read_csv(path, encoding="utf-8-sig", dtype=str).fillna("")
    # 대섹터가 빈 행은 위 값을 이어받는다 (시트의 carry-forward 와 동일)
    df["대섹터"] = df["대섹터"].replace("", pd.NA).ffill().fillna("기타")
    return df


def build_index(dic: pd.DataFrame) -> list[dict]:
    """Waterfall 단계별 조회표. 앞 단계가 우선한다."""
    rules = []
    for _, row in dic.iterrows():
        major = str(row.get("대섹터", "")).strip() or "기타"
        minor = str(row.get("세부섹터", "")).strip()
        base = {"대섹터": major, "세부섹터": minor, "비고": str(row.get("비고", "")).strip()}

        # 1단계 — 직접 등록 종목
        for name in _multi(row.get("종목")):
            rules.append({**base, "단계": 1, "키": name, "방식": "종목등록"})

        # 2단계 — 대장주
        for col in LEADER_COLS:
            name = str(row.get(col, "")).strip()
            if name:
                rules.append({**base, "단계": 2, "키": name, "방식": "대장주"})

        # 3단계 — 세부섹터명 토큰 (키워드와만 대조)
        for tok in _tokens(minor):
            if tok not in STOPWORDS:
                rules.append({**base, "단계": 3, "키": tok, "방식": "세부섹터"})

        # 4단계 — 키워드 열
        for kw in _multi(row.get("키워드")):
            rules.append({**base, "단계": 4, "키": kw, "방식": "키워드"})

        # 5단계 — 비고에 '|' 나 ',' 로 명시된 키워드만. 서술 문구는 쓰지 않는다
        remark = str(row.get("비고", ""))
        if "|" in remark or "," in remark:
            for kw in _multi(remark):
                if kw not in STOPWORDS and len(kw) >= 2:
                    rules.append({**base, "단계": 5, "키": kw, "방식": "비고"})

    rules.sort(key=lambda r: r["단계"])
    return rules


def map_stock(name: str, keywords: list[str], rules: list[dict]) -> dict | None:
    """종목 하나를 섹터에 배정한다.

    1·2단계 — 종목명 완전일치
    3~5단계 — 종목의 키워드와 대조 (종목명에 대고 부분일치하지 않는다)
    """
    target = str(name).strip()
    if not target:
        return None
    keys = [k.strip() for k in (keywords or []) if k and str(k).strip()]

    for rule in rules:
        key = rule["키"]
        if rule["단계"] <= 2:
            if target == key:
                return rule
        elif keys:
            for kw in keys:
                if key == kw or key in kw or kw in key:
                    return rule
    return None


def apply(df: pd.DataFrame, dic: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """특징주 표에 대섹터·세부섹터·매핑방식을 붙인다. 미매핑 종목명을 함께 돌려준다.

    종목 키워드가 있으면 `키워드` 열(리스트 또는 '|' 구분 문자열)에서 읽는다.
    """
    rules = build_index(dic)
    majors, minors, hows, unmapped = [], [], [], []

    kw_col = df["키워드"] if "키워드" in df.columns else [None] * len(df)

    for name, kws in zip(df["종목명"], kw_col):
        if isinstance(kws, str):
            kws = _multi(kws)
        hit = map_stock(name, kws or [], rules)
        if hit:
            majors.append(hit["대섹터"])
            minors.append(hit["세부섹터"])
            hows.append(hit["방식"])
        else:
            majors.append("미분류")
            minors.append("")
            hows.append("")
            unmapped.append(str(name))

    out = df.copy()
    out["대섹터"] = majors
    out["세부섹터"] = minors
    out["매핑"] = hows
    return out, unmapped


def aggregate(df: pd.DataFrame) -> list[dict]:
    """대섹터별로 묶어 주도업종/개별이슈를 판정하고 거래대금 순으로 세운다."""
    if df.empty:
        return []

    groups = []
    for major, part in df.groupby("대섹터", sort=False):
        part = part.sort_values("거래대금(억)", ascending=False)
        n = len(part)
        총액 = int(part["거래대금(억)"].sum())
        # 미분류는 '아직 섹터를 모르는 종목 묶음'이지 업종이 아니다. 주도로 치지 않는다
        if major == "미분류":
            분류, 등급 = "미분류", "?"
        elif n >= 주도_최소종목수:
            분류, 등급 = "주도업종", "★★★"
        else:
            분류, 등급 = "개별이슈", "○"

        groups.append({
            "대섹터": major,
            "종목수": n,
            "합산거래대금": 총액,
            "분류": 분류,
            "등급": 등급,
            "평균상승률": round(float(part["등락률(%)"].mean()), 2),
            "최고상승률": round(float(part["등락률(%)"].max()), 2),
            "최저상승률": round(float(part["등락률(%)"].min()), 2),
            "대장주": str(part.iloc[0]["종목명"]),
            "종목": part.to_dict("records"),
        })

    # 미분류는 항상 맨 뒤로
    groups.sort(key=lambda g: (g["대섹터"] == "미분류", -g["합산거래대금"]))
    for i, g in enumerate(groups, 1):
        g["순위"] = i
    return groups


def leaders(groups: list[dict], limit: int = 3) -> list[dict]:
    """그날의 대장주 후보. 주도업종의 거래대금 1위부터 차례로 고른다.

    사용자 규칙: 하루 3종목 이상 관찰하지 못한다.
    여기서는 '관심도' 축만 적용한 1차 후보이며, 재료·차트·수급은 화면에서 확인한다.
    """
    out = []
    for g in groups:
        if g["분류"] != "주도업종" or g["대섹터"] == "미분류":
            continue
        top = g["종목"][0]
        out.append({
            "종목명": top["종목명"],
            "대섹터": g["대섹터"],
            "세부섹터": top.get("세부섹터", ""),
            "거래대금": top["거래대금(억)"],
            "등락률": top["등락률(%)"],
            "섹터합산": g["합산거래대금"],
            "섹터종목수": g["종목수"],
            "조건": top.get("조건", ""),
            "rsi": top.get("RSI(14)"),
            "볼밴위치": top.get("볼밴위치"),
            "평균변동폭": top.get("평균변동폭(20일)"),
            "근거": top.get("상승원인", ""),
            "2등주": g["종목"][1]["종목명"] if g["종목수"] > 1 else None,
            "2등주등락률": g["종목"][1]["등락률(%)"] if g["종목수"] > 1 else None,
        })
        if len(out) >= limit:
            break
    return out
