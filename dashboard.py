"""
===========================================================
  특징주 손익비 데스크  —  HTML 생성
===========================================================

raw_최근.csv + raw_최근.json 을 읽어 out/dashboard.html 을 만든다.
데이터를 페이지 안에 박아 넣으므로 파일 하나만 열면 된다. 서버가 필요 없다.

[ 실행 ]
  python dashboard.py              # raw_최근.csv 기준
  python dashboard.py --open       # 만들고 브라우저로 열기

수집기(특징주_자동집계.py)를 돌린 뒤에 실행한다.
run_daily.ps1 이 매일 자동으로 호출한다.
===========================================================
"""

import json
import os
import sys
import webbrowser
from datetime import datetime

import pandas as pd

LATEST_CSV = "raw_최근.csv"
LATEST_META = "raw_최근.json"
OUT_DIR = "out"
OUT_FILE = os.path.join(OUT_DIR, "dashboard.html")

# risk_metrics.STOP_MULTIPLE 과 같은 기본값. 페이지에서 슬라이더로 바꿀 수 있다.
DEFAULT_MULTIPLE = 1.5


def _num(val):
    """NaN·공란을 None 으로. JSON 에 NaN 을 넣으면 JS 가 파싱하지 못한다."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, str):
        return val if val.strip() else None
    return float(val) if isinstance(val, float) else int(val)


def load_rows() -> tuple[list[dict], dict]:
    if not os.path.exists(LATEST_CSV):
        print(f"[중단] {LATEST_CSV} 이 없습니다. 특징주_자동집계.py 를 먼저 실행하세요.")
        sys.exit(1)

    df = pd.read_csv(LATEST_CSV, encoding="utf-8-sig")
    meta = {}
    if os.path.exists(LATEST_META):
        with open(LATEST_META, encoding="utf-8") as fh:
            meta = json.load(fh)

    rows = []
    for _, r in df.iterrows():
        rows.append({
            "조건": r.get("조건"),
            "시장": r.get("시장"),
            "종목명": r.get("종목명"),
            "티커": str(r.get("티커")).zfill(6),
            "종가": _num(r.get("종가")),
            "등락률": _num(r.get("등락률(%)")),
            "거래대금": _num(r.get("거래대금(억)")),
            "일중변동폭": _num(r.get("일중변동폭(%)")),
            "rsi": _num(r.get("RSI(14)")),
            "볼밴위치": _num(r.get("볼밴위치")),
            "볼밴": _num(r.get("볼밴%B")),
            "이격도": _num(r.get("이격도")),
            "평균변동폭": _num(r.get("평균변동폭(20일)")),
        })
    return rows, meta


TEMPLATE = r"""<title>특징주 손익비 데스크</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>
  :root {
    --bg:        #f4f6f8;
    --surface:   #ffffff;
    --surface-2: #eceff3;
    --line:      #d8dee6;
    --line-soft: #e7ebf0;
    --ink:       #141820;
    --ink-2:     #4d5868;
    --ink-3:     #7b8696;
    --accent:    #1f3864;
    --accent-2:  #35558c;
    --up:        #d2342c;
    --down:      #2560c0;
    --warn:      #b4480c;
    --warn-bg:   #fdf0e6;
    --ok:        #15663c;
    --ok-bg:     #e8f3ec;
    --flat:      #6b7480;
    --shadow:    0 1px 2px rgba(20,24,32,.06), 0 8px 24px rgba(20,24,32,.04);
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg:        #0e1116;
      --surface:   #161b22;
      --surface-2: #1d242e;
      --line:      #2b3340;
      --line-soft: #222a35;
      --ink:       #e6ebf2;
      --ink-2:     #a3aebf;
      --ink-3:     #73808f;
      --accent:    #7ba3e8;
      --accent-2:  #9dbcf2;
      --up:        #f2635a;
      --down:      #5e9bf0;
      --warn:      #f0974a;
      --warn-bg:   #2e2114;
      --ok:        #52b87c;
      --ok-bg:     #13291d;
      --flat:      #8b95a3;
      --shadow:    0 1px 2px rgba(0,0,0,.4), 0 8px 24px rgba(0,0,0,.3);
    }
  }
  :root[data-theme="dark"] {
    --bg:        #0e1116;
    --surface:   #161b22;
    --surface-2: #1d242e;
    --line:      #2b3340;
    --line-soft: #222a35;
    --ink:       #e6ebf2;
    --ink-2:     #a3aebf;
    --ink-3:     #73808f;
    --accent:    #7ba3e8;
    --accent-2:  #9dbcf2;
    --up:        #f2635a;
    --down:      #5e9bf0;
    --warn:      #f0974a;
    --warn-bg:   #2e2114;
    --ok:        #52b87c;
    --ok-bg:     #13291d;
    --flat:      #8b95a3;
    --shadow:    0 1px 2px rgba(0,0,0,.4), 0 8px 24px rgba(0,0,0,.3);
  }

  * { box-sizing: border-box; }

  body {
    margin: 0;
    background: var(--bg);
    color: var(--ink);
    font-family: "IBM Plex Sans KR", "Malgun Gothic", system-ui, sans-serif;
    font-size: 14px;
    line-height: 1.5;
    -webkit-font-smoothing: antialiased;
  }
  .num {
    font-family: "IBM Plex Mono", ui-monospace, Consolas, monospace;
    font-variant-numeric: tabular-nums;
  }

  .wrap { max-width: 1340px; margin: 0 auto; padding: 24px 20px 64px; }

  /* ── 헤더 ───────────────────────────────── */
  header {
    display: flex; flex-wrap: wrap; align-items: baseline; gap: 10px 18px;
    padding-bottom: 14px; border-bottom: 2px solid var(--accent);
  }
  h1 {
    margin: 0; font-size: 19px; font-weight: 600; letter-spacing: -.01em;
  }
  .date {
    font-size: 15px; font-weight: 600; color: var(--accent);
  }
  .asof { margin-left: auto; font-size: 11.5px; color: var(--ink-3); }

  /* ── 요약 스트립 ─────────────────────────── */
  .strip {
    display: flex; flex-wrap: wrap; gap: 0;
    margin: 0 0 20px; background: var(--surface);
    border: 1px solid var(--line); border-top: none;
    box-shadow: var(--shadow);
  }
  .cell {
    flex: 1 1 140px; padding: 12px 16px;
    border-right: 1px solid var(--line-soft);
  }
  .cell:last-child { border-right: none; }
  .cell .k {
    font-size: 10.5px; letter-spacing: .09em; text-transform: uppercase;
    color: var(--ink-3); margin-bottom: 3px;
  }
  .cell .v { font-size: 17px; font-weight: 600; }
  .cell .sub { font-size: 11.5px; color: var(--ink-3); }
  .cell.ref { background: var(--surface-2); }
  .cell.ref .v { font-size: 15px; color: var(--ink-2); }

  /* ── 시나리오 콘솔 ───────────────────────── */
  .console {
    background: var(--surface); border: 1px solid var(--line);
    border-left: 3px solid var(--accent);
    padding: 16px 18px; margin-bottom: 20px; box-shadow: var(--shadow);
  }
  .console h2 {
    margin: 0 0 3px; font-size: 13px; font-weight: 600;
    display: flex; align-items: center; gap: 8px;
  }
  .console p.hint { margin: 0 0 14px; font-size: 12px; color: var(--ink-3); }
  .controls {
    display: flex; flex-wrap: wrap; gap: 20px 28px; align-items: flex-end;
  }
  .ctl { display: flex; flex-direction: column; gap: 6px; }
  .ctl > label {
    font-size: 10.5px; letter-spacing: .08em; text-transform: uppercase;
    color: var(--ink-3);
  }
  .slider-row { display: flex; align-items: center; gap: 12px; }
  input[type="range"] { width: 190px; accent-color: var(--accent); }
  .readout {
    font-size: 16px; font-weight: 600; color: var(--accent);
    min-width: 54px;
  }
  .seg { display: flex; border: 1px solid var(--line); overflow: hidden; }
  .seg button {
    appearance: none; border: none; background: var(--surface);
    color: var(--ink-2); font: inherit; font-size: 12.5px;
    padding: 6px 13px; cursor: pointer;
    border-right: 1px solid var(--line-soft);
  }
  .seg button:last-child { border-right: none; }
  .seg button:hover { background: var(--surface-2); }
  .seg button[aria-pressed="true"] {
    background: var(--accent); color: #fff; font-weight: 600;
  }
  .check input { accent-color: var(--accent); }
  .check {
    display: flex; align-items: center; gap: 7px;
    font-size: 12.5px; color: var(--ink-2); cursor: pointer;
    padding-bottom: 6px;
  }
  button:focus-visible, input:focus-visible, th[role="button"]:focus-visible {
    outline: 2px solid var(--accent-2); outline-offset: 1px;
  }

  /* ── 표 ─────────────────────────────────── */
  .tablewrap {
    overflow-x: auto; background: var(--surface);
    border: 1px solid var(--line); box-shadow: var(--shadow);
  }
  table { width: 100%; border-collapse: collapse; white-space: nowrap; }
  thead th {
    position: sticky; top: 0; z-index: 2;
    background: var(--accent); color: #fff;
    font-size: 11px; font-weight: 600; letter-spacing: .04em;
    text-align: right; padding: 9px 10px; cursor: pointer;
    user-select: none;
  }
  thead th:first-child, thead th.l { text-align: left; }
  thead th .arrow { opacity: .45; font-size: 9px; margin-left: 3px; }
  thead th[data-active="1"] .arrow { opacity: 1; }
  tbody td {
    padding: 8px 10px; text-align: right;
    border-bottom: 1px solid var(--line-soft); font-size: 13px;
  }
  tbody td.l { text-align: left; }
  tbody tr:hover { background: var(--surface-2); }
  tbody tr.dim { opacity: .4; }

  .tag {
    display: inline-block; font-size: 10.5px; font-weight: 700;
    padding: 2px 6px; letter-spacing: .03em;
  }
  .tag.ab { background: var(--up); color: #fff; }
  .tag.a  { background: var(--warn-bg); color: var(--warn); border: 1px solid var(--warn); }
  .tag.b  { background: var(--surface-2); color: var(--ink-2); border: 1px solid var(--line); }

  .name { font-weight: 600; }
  .mkt { font-size: 11px; color: var(--ink-3); margin-left: 6px; }

  .up   { color: var(--up);   font-weight: 600; }
  .down { color: var(--down); font-weight: 600; }
  .flat { color: var(--flat); }

  .chip {
    display: inline-block; font-size: 11.5px; font-weight: 600;
    padding: 2px 7px; min-width: 46px; text-align: center;
  }
  .chip.hot  { background: var(--up); color: #fff; }
  .chip.cold { background: var(--down); color: #fff; }
  .chip.mid  { background: var(--surface-2); color: var(--ink-2); }
  .chip.none { background: none; color: var(--ink-3); font-weight: 400; }

  /* 볼밴 위치 게이지 */
  .gauge {
    display: inline-flex; align-items: center; gap: 8px;
  }
  .gauge .track {
    position: relative; width: 62px; height: 7px;
    background: linear-gradient(90deg, var(--surface-2) 0%, var(--surface-2) 100%);
    border: 1px solid var(--line);
  }
  .gauge .mid {
    position: absolute; left: 50%; top: -2px; bottom: -2px;
    width: 1px; background: var(--line);
  }
  .gauge .pin {
    position: absolute; top: -3px; width: 3px; height: 13px;
    background: var(--ink); transform: translateX(-1.5px);
  }
  .gauge .pin.high { background: var(--up); }
  .gauge .pin.low  { background: var(--down); }
  .gauge .lbl { font-size: 11.5px; color: var(--ink-2); min-width: 52px; text-align: left; }

  td.stop { color: var(--down); font-weight: 600; }
  td.take { color: var(--up);   font-weight: 600; }
  td.days { font-weight: 600; }
  td.days.far  { color: var(--warn); }
  td.days.near { color: var(--ok); }

  .empty {
    padding: 36px 16px; text-align: center; color: var(--ink-3); font-size: 13px;
  }

  /* ── 범례 ───────────────────────────────── */
  .legend {
    margin-top: 18px; padding: 14px 16px;
    background: var(--surface); border: 1px solid var(--line);
    font-size: 12px; color: var(--ink-2); line-height: 1.7;
  }
  .legend h3 {
    margin: 0 0 8px; font-size: 11px; letter-spacing: .09em;
    text-transform: uppercase; color: var(--ink-3); font-weight: 600;
  }
  .legend b { color: var(--ink); }
  .legend .sep { margin: 10px 0 0; padding-top: 10px; border-top: 1px solid var(--line-soft); }
  .badge {
    display: inline-block; font-size: 10px; font-weight: 700;
    padding: 1px 5px; border: 1px solid currentColor; margin-right: 5px;
  }
  .badge.fix { color: var(--ok); }
  .badge.sug { color: var(--warn); }

  .count { font-size: 12px; color: var(--ink-3); margin: 14px 0 7px; }
</style>

<div class="wrap">
  <header>
    <h1>특징주 손익비 데스크</h1>
    <span class="date" id="tradeDate"></span>
    <span class="asof" id="asof"></span>
  </header>

  <div class="strip" id="strip"></div>

  <section class="console">
    <h2>시나리오 — 손절을 얼마나 넓게 둘 것인가</h2>
    <p class="hint">
      평균 일중변동폭의 몇 배를 손절로 둘지 바꾸면 손절·익절·필요일수가 전부 다시 계산된다.
      익절은 항상 손절의 3배(3:1)로 고정된다.
    </p>
    <div class="controls">
      <div class="ctl">
        <label for="mult">손절 = 평균변동폭 ×</label>
        <div class="slider-row">
          <input type="range" id="mult" min="0.5" max="3" step="0.1" value="1.5">
          <span class="readout num" id="multOut">1.5</span>
        </div>
      </div>

      <div class="ctl">
        <label for="maxDays">필요일수 상한</label>
        <div class="slider-row">
          <input type="range" id="maxDays" min="2" max="20" step="0.5" value="20">
          <span class="readout num" id="maxDaysOut">제한없음</span>
        </div>
      </div>

      <div class="ctl">
        <label>조건</label>
        <div class="seg" id="condSeg">
          <button data-cond="ALL" aria-pressed="true">전체</button>
          <button data-cond="A+B" aria-pressed="false">A+B</button>
          <button data-cond="A" aria-pressed="false">A</button>
          <button data-cond="B" aria-pressed="false">B</button>
        </div>
      </div>

      <label class="check">
        <input type="checkbox" id="hideHot">
        RSI 70 이상 숨기기
      </label>
      <label class="check">
        <input type="checkbox" id="hideBand">
        볼밴 상단권 숨기기
      </label>
    </div>
  </section>

  <p class="count" id="count"></p>

  <div class="tablewrap">
    <table>
      <thead>
        <tr id="head"></tr>
      </thead>
      <tbody id="body"></tbody>
    </table>
  </div>

  <div class="legend">
    <h3>읽는 법</h3>
    <p>
      <span class="badge fix">확정</span>
      <b>RSI</b> 70 이상 과매수 · 30 이하 과매도 — 과열 척도이며 매수 신호가 아니다.
      <b>볼밴 σ2</b> 상단으로 갈수록 위험률 상승.
      <b>이격도</b> 종가÷20일 이동평균×100.
      <b>손익비 3:1</b> 익절은 손절의 3배.
    </p>
    <p>
      <span class="badge sug">제안</span>
      <b>손절 = 평균변동폭 × 배수</b> — 배수는 확정값이 아니다. 기본 1.5는 제안이며 슬라이더로 바꿔 본다.
      <b>필요일수 = 익절폭 ÷ 평균변동폭</b> — 익절까지 평균 며칠분 움직임이 필요한지. 작을수록 현실적이다.
    </p>
    <p class="sep">
      <b>시장 ADR 은 참고 지표다.</b> 판단을 ADR 로 결정하지 않는다.
      ADR 은 종목을 세는 지표라 단일종목에는 계산되지 않는다 — 좁힐 수 있는 최소 단위는 섹터다.
    </p>
    <p>
      <b>A+B</b> 등락률과 거래대금이 동시에 터진 종목 — 그날의 대장주 후보 1순위.
      <b>A</b> 등락률 15% 이상 · <b>B</b> 거래대금 500억 이상 + 일중변동폭 6% 이상.
      이력이 부족한 종목(신규상장·거래정지)은 지표가 <span class="chip none">—</span> 로 비어 있다.
    </p>
  </div>
</div>

<script>
const DATA = __DATA__;
const META = __META__;
const DEFAULT_MULT = __MULT__;

const KEY = "sonikbi-desk-v1";
const el = (id) => document.getElementById(id);

const state = {
  mult: DEFAULT_MULT,
  maxDays: 20,
  cond: "ALL",
  hideHot: false,
  hideBand: false,
  sort: null,
  dir: -1,
};

try {
  const saved = JSON.parse(localStorage.getItem(KEY) || "null");
  if (saved && typeof saved === "object") Object.assign(state, saved);
} catch (e) { /* 저장소를 못 읽어도 기본값으로 동작한다 */ }

function persist() {
  try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {}
}

const fmt = (v, d = 0) =>
  v === null || v === undefined ? "—"
  : v.toLocaleString("ko-KR", { minimumFractionDigits: d, maximumFractionDigits: d });

const BAND_LABEL = {
  "상단돌파": "상단 돌파", "상단": "상단", "중상단": "중상단",
  "중심": "중심", "중하단": "중하단", "하단": "하단",
};
const HIGH_BANDS = new Set(["상단돌파", "상단", "중상단"]);

/* 파생값: 손절 · 익절 · 필요일수 */
function derive(row) {
  const avg = row.평균변동폭;
  if (!avg) return { stop: null, take: null, days: null };
  const stop = avg * state.mult;
  const take = stop * 3;
  return { stop: -stop, take: take, days: take / avg };
}

const COLS = [
  { k: "조건",       t: "조건",   l: true,  sort: (r) => ({ "A+B": 0, A: 1, B: 2 }[r.조건] ?? 9) },
  { k: "종목명",     t: "종목",   l: true,  sort: (r) => r.종목명 },
  { k: "종가",       t: "종가",             sort: (r) => r.종가 },
  { k: "등락률",     t: "등락률",           sort: (r) => r.등락률 },
  { k: "거래대금",   t: "거래대금(억)",     sort: (r) => r.거래대금 },
  { k: "rsi",        t: "RSI(14)",          sort: (r) => r.rsi },
  { k: "볼밴",       t: "볼밴 σ2 위치", l: true, sort: (r) => r.볼밴 },
  { k: "이격도",     t: "이격도",           sort: (r) => r.이격도 },
  { k: "평균변동폭", t: "평균변동폭",       sort: (r) => r.평균변동폭 },
  { k: "stop",       t: "손절",             sort: (r) => derive(r).stop },
  { k: "take",       t: "익절",             sort: (r) => derive(r).take },
  { k: "days",       t: "필요일수",         sort: (r) => derive(r).days },
];

function buildHead() {
  el("head").innerHTML = COLS.map((c, i) => {
    const active = state.sort === i ? ' data-active="1"' : "";
    const arrow = state.sort === i ? (state.dir === 1 ? "▲" : "▼") : "▽";
    return `<th${active} class="${c.l ? "l" : ""}" role="button" tabindex="0"
             data-i="${i}">${c.t}<span class="arrow">${arrow}</span></th>`;
  }).join("");

  el("head").querySelectorAll("th").forEach((th) => {
    const go = () => {
      const i = Number(th.dataset.i);
      if (state.sort === i) state.dir = -state.dir;
      else { state.sort = i; state.dir = -1; }
      persist(); render();
    };
    th.addEventListener("click", go);
    th.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); }
    });
  });
}

function visible() {
  return DATA.filter((r) => {
    if (state.cond !== "ALL" && r.조건 !== state.cond) return false;
    if (state.hideHot && r.rsi !== null && r.rsi >= 70) return false;
    if (state.hideBand && HIGH_BANDS.has(r.볼밴위치)) return false;
    if (state.maxDays < 20) {
      const d = derive(r).days;
      if (d === null || d > state.maxDays) return false;
    }
    return true;
  });
}

function rowHtml(r) {
  const d = derive(r);
  const tagCls = r.조건 === "A+B" ? "ab" : r.조건 === "A" ? "a" : "b";

  const chg = r.등락률 === null ? '<span class="flat">—</span>'
    : `<span class="${r.등락률 > 0 ? "up" : r.등락률 < 0 ? "down" : "flat"}">` +
      `${r.등락률 > 0 ? "+" : ""}${fmt(r.등락률, 2)}%</span>`;

  let rsi = '<span class="chip none">—</span>';
  if (r.rsi !== null) {
    const cls = r.rsi >= 70 ? "hot" : r.rsi <= 30 ? "cold" : "mid";
    rsi = `<span class="chip ${cls}">${fmt(r.rsi, 1)}</span>`;
  }

  let band = '<span class="chip none">—</span>';
  if (r.볼밴 !== null) {
    const pos = Math.max(0, Math.min(100, r.볼밴));
    const pin = r.볼밴 >= 80 ? "high" : r.볼밴 <= 20 ? "low" : "";
    band = `<span class="gauge"><span class="track">` +
           `<span class="mid"></span>` +
           `<span class="pin ${pin}" style="left:${pos}%"></span></span>` +
           `<span class="lbl">${BAND_LABEL[r.볼밴위치] || "—"}</span></span>`;
  }

  const daysCls = d.days === null ? "" : d.days <= 4 ? "near" : d.days >= 8 ? "far" : "";

  return `<tr>
    <td class="l"><span class="tag ${tagCls}">${r.조건}</span></td>
    <td class="l"><span class="name">${r.종목명}</span><span class="mkt">${r.시장}</span></td>
    <td class="num">${fmt(r.종가)}</td>
    <td class="num">${chg}</td>
    <td class="num">${fmt(r.거래대금)}</td>
    <td class="num">${rsi}</td>
    <td class="l">${band}</td>
    <td class="num">${r.이격도 === null ? "—" : fmt(r.이격도, 1)}</td>
    <td class="num">${r.평균변동폭 === null ? "—" : fmt(r.평균변동폭, 1) + "%"}</td>
    <td class="num stop">${d.stop === null ? "—" : fmt(d.stop, 1) + "%"}</td>
    <td class="num take">${d.take === null ? "—" : "+" + fmt(d.take, 1) + "%"}</td>
    <td class="num days ${daysCls}">${d.days === null ? "—" : fmt(d.days, 1) + "일"}</td>
  </tr>`;
}

function buildStrip() {
  const withRsi = DATA.filter((r) => r.rsi !== null);
  const hot = withRsi.filter((r) => r.rsi >= 70).length;
  const ab = DATA.filter((r) => r.조건 === "A+B").length;
  const adr = META.ADR;
  const zoneColor = META.구간 === "과열" ? "var(--up)"
    : META.구간 === "침체" ? "var(--down)" : "var(--ink-2)";

  el("strip").innerHTML = `
    <div class="cell">
      <div class="k">특징주</div>
      <div class="v num">${DATA.length}<span class="sub"> 종목</span></div>
      <div class="sub">A+B ${ab} · A ${DATA.filter(r=>r.조건==="A").length} · B ${DATA.filter(r=>r.조건==="B").length}</div>
    </div>
    <div class="cell">
      <div class="k">RSI 70 이상</div>
      <div class="v num" style="color:${hot ? "var(--up)" : "var(--ink)"}">${hot}<span class="sub"> / ${withRsi.length}</span></div>
      <div class="sub">과매수 = 위험 가산</div>
    </div>
    <div class="cell">
      <div class="k">볼밴 상단권</div>
      <div class="v num">${DATA.filter(r=>HIGH_BANDS.has(r.볼밴위치)).length}<span class="sub"> 종목</span></div>
      <div class="sub">중상단 이상</div>
    </div>
    <div class="cell">
      <div class="k">지표 공란</div>
      <div class="v num">${DATA.length - withRsi.length}<span class="sub"> 종목</span></div>
      <div class="sub">이력 부족</div>
    </div>
    <div class="cell ref">
      <div class="k">시장 ADR · 참고</div>
      <div class="v num" style="color:${zoneColor}">${adr === undefined ? "—" : adr} <span class="sub">${META.구간 || ""}</span></div>
      <div class="sub">상승 ${fmt(META.상승)} / 하락 ${fmt(META.하락)}</div>
    </div>`;
}

function render() {
  const rows = visible();

  if (state.sort !== null) {
    const f = COLS[state.sort].sort;
    rows.sort((a, b) => {
      const x = f(a), y = f(b);
      if (x === null || x === undefined) return 1;
      if (y === null || y === undefined) return -1;
      if (typeof x === "string") return state.dir * y.localeCompare(x, "ko");
      return state.dir * (x - y);
    });
  }

  el("body").innerHTML = rows.length
    ? rows.map(rowHtml).join("")
    : `<tr><td colspan="${COLS.length}" class="empty">조건에 맞는 종목이 없습니다. 필터를 풀어 보세요.</td></tr>`;

  el("count").textContent =
    `${rows.length}종목 표시 (전체 ${DATA.length})` +
    (state.maxDays < 20 ? ` · 필요일수 ${state.maxDays}일 이하` : "");

  buildHead();
}

/* ── 컨트롤 ─────────────────────────────── */
function wire() {
  const mult = el("mult"), maxDays = el("maxDays");

  mult.value = state.mult;
  el("multOut").textContent = Number(state.mult).toFixed(1);
  mult.addEventListener("input", () => {
    state.mult = Number(mult.value);
    el("multOut").textContent = state.mult.toFixed(1);
    persist(); render();
  });

  maxDays.value = state.maxDays;
  const showDays = () => {
    el("maxDaysOut").textContent = state.maxDays >= 20 ? "제한없음" : state.maxDays + "일";
  };
  showDays();
  maxDays.addEventListener("input", () => {
    state.maxDays = Number(maxDays.value);
    showDays(); persist(); render();
  });

  el("condSeg").querySelectorAll("button").forEach((b) => {
    b.setAttribute("aria-pressed", String(b.dataset.cond === state.cond));
    b.addEventListener("click", () => {
      state.cond = b.dataset.cond;
      el("condSeg").querySelectorAll("button").forEach((x) =>
        x.setAttribute("aria-pressed", String(x.dataset.cond === state.cond)));
      persist(); render();
    });
  });

  el("hideHot").checked = state.hideHot;
  el("hideHot").addEventListener("change", (e) => {
    state.hideHot = e.target.checked; persist(); render();
  });
  el("hideBand").checked = state.hideBand;
  el("hideBand").addEventListener("change", (e) => {
    state.hideBand = e.target.checked; persist(); render();
  });
}

/* ── 시작 ───────────────────────────────── */
const raw = String(META.날짜 || "");
el("tradeDate").textContent = raw.length === 8
  ? `${raw.slice(0,4)}.${raw.slice(4,6)}.${raw.slice(6,8)} 종가 기준`
  : raw;
el("asof").textContent = `수집 ${META.수집시각 || "—"}`;

buildStrip();
wire();
render();
</script>
"""


def build() -> str:
    rows, meta = load_rows()
    html = (TEMPLATE
            .replace("__DATA__", json.dumps(rows, ensure_ascii=False))
            .replace("__META__", json.dumps(meta, ensure_ascii=False))
            .replace("__MULT__", str(DEFAULT_MULTIPLE)))

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as fh:
        fh.write(html)

    path = os.path.abspath(OUT_FILE)
    print(f"  화면 생성: {path}")
    print(f"  {len(rows)}종목  |  거래일 {meta.get('날짜', '?')}  |  "
          f"ADR {meta.get('ADR', '?')} [{meta.get('구간', '?')}] (참고)")
    return path


def main():
    path = build()
    if "--open" in sys.argv:
        webbrowser.open(f"file:///{path.replace(os.sep, '/')}")


if __name__ == "__main__":
    main()
