"""
===========================================================
  PC 공용 비밀 로더 — ~/.stock-desk/secrets.env
===========================================================

PC 마다 setx 를 따로 하지 않으려고 만들었다. 키는 이 파일 한 곳에만 둔다.

  위치   : %USERPROFILE%\\.stock-desk\\secrets.env      (한 줄에 KEY=값)
  채우는 법: scripts\\bootstrap.ps1 이 비공개 저장소(pc-sync)에서 가져온다
  규칙   : 이미 환경변수에 있으면 덮어쓰지 않는다 — GitHub Actions 의 Secrets 가 우선이다
           파일이 없으면 조용히 넘어간다 (환경변수만으로 돌던 기존 방식 그대로)

pykrx 는 import 시점에 KRX_ID / KRX_PW 로 로그인하므로,
이 모듈은 pykrx 보다 먼저 import 되어야 한다.
===========================================================
"""
import os

FILE = os.path.join(os.path.expanduser("~"), ".stock-desk", "secrets.env")


def load(path=FILE):
    """secrets.env 의 값을 os.environ 에 채운다. 새로 채운 개수를 돌려준다."""
    try:
        with open(path, encoding="utf-8-sig") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return 0
    n = 0
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if not key or not val or val == "CHANGEME" or os.environ.get(key):
            continue
        os.environ[key] = val
        n += 1
    return n


load()
