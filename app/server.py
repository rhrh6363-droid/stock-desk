"""
===========================================================
  로컬 웹앱 서버 + 장중 배치
===========================================================

  python app/server.py              → http://localhost:8765
  python app/server.py --port 9000
  python app/server.py --no-batch   → 자동 배치 없이 보기만

[ 자동 배치 ]
  평일 09:00~16:30 사이 BATCH_MINUTES 간격으로 파이프라인을 돌린다.
  장이 끝난 뒤 16:30 에 한 번 더 돌려 종가 기준 자료를 확정한다.
  화면은 60초마다 최신 JSON 을 다시 읽으므로 새로고침하지 않아도 갱신된다.
===========================================================
"""

import argparse
import json
import os
import sys
import threading
import time
import webbrowser
from datetime import datetime, time as dtime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STATIC = os.path.join(HERE, "static")
DATA = os.path.join(HERE, "data")
for p in (HERE, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

BATCH_MINUTES = 60
MARKET_OPEN = dtime(9, 0)
MARKET_CLOSE = dtime(16, 30)

_status = {"상태": "대기", "마지막실행": None, "마지막결과": None, "다음예정": None}
_lock = threading.Lock()


# ────────────────────────────────────────────────
# 배치
# ────────────────────────────────────────────────
def run_pipeline(reason: str = "수동") -> dict:
    import pipeline

    with _lock:
        _status["상태"] = f"실행 중 ({reason})"
    try:
        payload = pipeline.run()
        with _lock:
            _status.update({
                "상태": "대기",
                "마지막실행": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "마지막결과": payload.get("상태", "성공"),
            })
        return payload
    except Exception as exc:
        with _lock:
            _status.update({
                "상태": "대기",
                "마지막실행": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "마지막결과": f"실패: {type(exc).__name__}: {exc}",
            })
        print(f"[배치 실패] {type(exc).__name__}: {exc}")
        return {"상태": "실패"}


def in_market_hours() -> bool:
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    return MARKET_OPEN <= now.time() <= MARKET_CLOSE


def batch_loop():
    print(f"[배치] 평일 {MARKET_OPEN:%H:%M}~{MARKET_CLOSE:%H:%M}, {BATCH_MINUTES}분 간격")
    while True:
        if in_market_hours():
            run_pipeline("자동")
        with _lock:
            _status["다음예정"] = datetime.fromtimestamp(
                time.time() + BATCH_MINUTES * 60).strftime("%H:%M:%S")
        time.sleep(BATCH_MINUTES * 60)


# ────────────────────────────────────────────────
# 히트맵 — 저장된 날짜별 JSON 을 모아 섹터×일자 거래대금을 만든다
# ────────────────────────────────────────────────
def build_heatmap(limit_days: int = 30) -> dict:
    if not os.path.isdir(DATA):
        return {"날짜": [], "섹터": []}

    files = sorted(f for f in os.listdir(DATA)
                   if f.endswith(".json") and f[:8].isdigit())[-limit_days:]

    dates, table = [], {}
    for fname in files:
        try:
            with open(os.path.join(DATA, fname), encoding="utf-8") as fh:
                payload = json.load(fh)
        except Exception:
            continue
        date = payload.get("거래일")
        if not date:
            continue
        dates.append(date)
        for g in payload.get("그룹", []):
            table.setdefault(g["대섹터"], {})[date] = g["합산거래대금"]

    # 월별 합산 — 눌림목 기간 추세를 보려면 일별만으로는 모자란다
    months = sorted({d[:6] for d in dates})

    sectors = []
    for name, row in table.items():
        월합 = {m: 0 for m in months}
        for d, v in row.items():
            if v:
                월합[d[:6]] += v
        sectors.append({
            "대섹터": name,
            "값": [row.get(d) for d in dates],
            "월별": [월합[m] or None for m in months],
            "합계": sum(v for v in row.values() if v),
            "등장일수": sum(1 for v in row.values() if v),
        })
    sectors.sort(key=lambda s: -s["합계"])

    return {"날짜": dates, "월": months, "섹터": sectors}


# ────────────────────────────────────────────────
# HTTP
# ────────────────────────────────────────────────
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=STATIC, **kw)

    def log_message(self, fmt, *args):
        pass                       # 요청 로그는 조용히

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/api/latest":
            f = os.path.join(DATA, "latest.json")
            if not os.path.exists(f):
                return self._json({"상태": "없음",
                                   "안내": "아직 수집된 자료가 없습니다. '지금 갱신'을 누르세요."})
            with open(f, encoding="utf-8") as fh:
                return self._json(json.load(fh))

        if path == "/api/status":
            with _lock:
                return self._json({**_status, "장중": in_market_hours()})

        if path == "/api/heatmap":
            return self._json(build_heatmap())

        if path == "/api/run":
            threading.Thread(target=run_pipeline, args=("수동",), daemon=True).start()
            return self._json({"시작": True})

        return super().do_GET()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-batch", action="store_true")
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()

    os.makedirs(DATA, exist_ok=True)

    if not args.no_batch:
        threading.Thread(target=batch_loop, daemon=True).start()

    url = f"http://localhost:{args.port}"
    print("=" * 58)
    print(f"  특징주 데스크   {url}")
    print("  멈추려면 이 창에서 Ctrl+C")
    print("=" * 58)

    if not args.no_open:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    try:
        ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\n종료합니다.")


if __name__ == "__main__":
    main()
