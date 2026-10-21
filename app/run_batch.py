"""
===========================================================
  일배치 로컬 실행 — 특징주 수집 + 화면 데이터 빌드 + 커밋·푸시
===========================================================

GitHub Actions(collect.yml) 크론은 밀리거나 건너뛰어서 하루 첫 실행이 보통 13시다.
오전에도 화면이 오늘 기준이 되도록 같은 일을 이 PC 의 작업 스케줄러가 한 번 더 한다.

  collect.yml 과 같은 순서   pipeline.py → build_static.py → app/data · docs/data 커밋
  다른 점                    docs/data/live.json 은 장중 수집(collect_live.py)이 쓰는 파일이라 건드리지 않는다

  python app/run_batch.py             # 수집·빌드·푸시
  python app/run_batch.py --no-push   # 푸시는 건너뛴다
===========================================================
"""
import os
import subprocess
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import stock_env  # noqa: F401,E402  ~/.stock-desk/secrets.env


def sh(*cmd, check=True):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=check)


def step(label, *cmd):
    print(f"[{label}]")
    r = subprocess.run(cmd, cwd=ROOT, env={**os.environ, "PYTHONUTF8": "1"})
    if r.returncode:
        print(f"  [{label}] 실패 (종료코드 {r.returncode})")
        return False
    return True


def push():
    paths = ["app/data", "docs/data"]
    sh("git", "add", "--", *paths)
    sh("git", "reset", "-q", "--", "docs/data/live.json", check=False)      # 장중 수집이 따로 올린다
    if not sh("git", "diff", "--cached", "--quiet", check=False).returncode:
        print("  바뀐 것 없음 — 휴장일이거나 자료가 같다")
        return
    sh("git", "commit", "-q", "-m", f"자동수집 {datetime.now().strftime('%Y-%m-%d %H:%M')} (로컬)", "--", *paths)
    for _ in range(3):
        if sh("git", "push", "-q", check=False).returncode == 0:
            print("  푸시 완료")
            return
        r = sh("git", "pull", "--rebase", "--autostash", "-q", check=False)
        if r.returncode:
            sh("git", "rebase", "--abort", check=False)
            print(f"  푸시 보류(다음 회차에 다시 시도): {r.stderr.strip()[:160]}")
            return
    print("  푸시 실패 - 다음 회차에 다시 시도")


if __name__ == "__main__":
    ok = step("1/2 수집", sys.executable, os.path.join("app", "pipeline.py"))
    ok = ok and step("2/2 빌드", sys.executable, os.path.join("app", "build_static.py"))
    if ok and "--no-push" not in sys.argv[1:]:
        push()
    sys.exit(0 if ok else 1)
