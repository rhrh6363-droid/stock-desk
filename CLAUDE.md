# stock-desk

국내 주식 특징주 수집 · 장중 5분 수집 · 손익비 데스크. 사용자는 **PC 두 대**로 작업한다.
두 PC 에서 똑같이 동작해야 하며, **PC 마다 손으로 설정하는 일을 만들지 않는다.**

## 세션을 열면 먼저
첫 작업 전에 `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\session-check.ps1` 을 실행한다.
최신 코드를 pull 하고 PC 상태를 점검하며, 문제가 없으면 아무것도 출력하지 않는다.
`[설정 필요]` 가 나오면 **사용자에게 키를 묻지 말고** `scripts\bootstrap.ps1` 을 실행한다.
(pc-sync 에도 키가 없을 때만, 키가 있는 PC 에서 `scripts\export-secrets.ps1` 을 먼저 돌려야 한다고 안내한다)
같은 스크립트를 SessionStart 훅으로 걸어 두면 자동으로 돈다 (사용자 승인 필요 — `.claude/settings.json`).

## 새 PC / 동기화
```
git clone https://github.com/rhrh6363-droid/stock-desk.git E:\Claude\stock-desk
powershell -ExecutionPolicy Bypass -File E:\Claude\stock-desk\scripts\bootstrap.ps1
```
- 필요한 것: `gh auth login` 이 되어 있을 것 (비공개 저장소 `pc-sync` 를 받는다)
- 하는 일: 패키지 설치 · 키/구글시트 설정/스킬/메모리 배치 · 작업 스케줄러 `주식 장중수집` 등록

## 비밀은 어디에
- **이 저장소는 공개다. 키·config.json·서비스 계정 JSON 을 절대 커밋하지 않는다.**
- 키는 `~/.stock-desk/secrets.env` 한 곳. 코드가 읽는다 (`app/stock_env.py`, `run_daily.ps1`, `시작.bat`).
  이미 환경변수에 있으면 덮어쓰지 않는다 — GitHub Actions 는 Secrets 를 그대로 쓴다.
- PC 사이 이동은 비공개 저장소 `rhrh6363-droid/pc-sync` 가 맡는다.
  올리기 `scripts/export-secrets.ps1` (키가 있는 PC 에서) / 받기 `scripts/bootstrap.ps1`.
- setx 는 쓰지 않는다 (재로그인이 필요하고 PC 마다 어긋난다).

## 구조
| 무엇 | 어디서 | 비고 |
|---|---|---|
| 장중 5분 수집 | 각 PC 작업 스케줄러 `주식 장중수집` → `scripts/장중수집.bat` → `app/collect_live.py` | 평일 08:55~15:40 밖에서는 조용히 끝난다. `docs/data/live.json` 만 커밋·푸시 |
| 일별 수집 | GitHub Actions `특징주 수집` (`.github/workflows/collect.yml`) | PC 가 꺼져 있어도 돈다. 크론이 밀려 하루 3번쯤 돈다 |
| 오전 보강 집계 | 작업 스케줄러 `특징주 오전집계` (평일 09:20·10:30·11:40) → `scripts/일배치.bat` → `app/run_batch.py` | GitHub 크론이 오전에 안 돌아서 첫 실행이 13시라 만들었다. pipeline → build_static → `app/data`·`docs/data` 커밋(live.json 제외). 이 PC 만 등록돼 있다 — 두 PC 가 함께 돌리지 않는 전제 |
| 로컬 일일집계 | 작업 스케줄러 `특징주 일일집계` → `run_daily.ps1` | 엑셀 누적 · 구글시트 전송. 클라우드가 대신하므로 필수는 아님 |
| 화면 | `docs/` (GitHub Pages) | |

- 토스 API 는 **해외 IP 를 403 으로 막는다.** GitHub 러너에서는 토스를 못 쓴다. 한국 PC 에서만 붙는다.
- 두 PC 가 모두 `main` 에 5분마다 커밋한다. 충돌은 `pull --rebase` 로 푼다 (`collect_live.py` push()).
- 작업 폴더 이름은 `stock-desk` (예전 이름 `trading` 에서 바꿨다).

## 가격 기준 규칙
- **일봉은 토스 통합 시세(KRX+NXT)가 기준이다.** `textbook_flow.toss_overlay` 가 네이버·pykrx(KRX 만) 일봉을 덮어쓴다.
  예) 10/15 삼성전자 시가 KRX 216,500 vs 토스 225,000.
- 장중 분봉: 종목은 토스 통합 1분봉(`day_replay.toss_min`)이 우선이고, 키가 없거나 막히면 네이버(KRX 정규장)로 떨어진다 (`day_replay.minute`).
  지수(코스피·코스닥)는 토스가 심볼을 안 줘서 네이버를 유지한다. 순위·테마 목록도 네이버다.

## 알려진 문제 (발생하면 그때 처리)
- **토스 토큰 충돌**: 토스는 새 토큰을 발급하면 이전 토큰을 즉시 끊는다(401 `token-revoked`). 두 PC 가 같은 키로 동시에 돌면 서로 끊는다.
  `toss.py` 가 토큰을 `~/.stock-desk/toss_token.json` 에 공유하고 401 이면 한 번 재발급해 재시도하지만, 두 PC 가 번갈아 돌면 호출이 늘어난다.
  → 토스 장중 수집은 한 PC 에서만 돌리거나, PC 마다 키를 따로 발급한다.
- **토스 허용 IP**: 토스증권 설정 > Open API > 허용 IP 에 등록된 공인 IP 에서만 붙는다(미등록 403 `IP address not allowed`). 공인 IP 가 바뀌면 다시 등록한다.
  막히면 장중 분봉은 네이버로 자동으로 떨어진다. 이 PC 는 2026-10-21 에 58.226.27.226 을 등록했다.
- **pc-sync 의 secrets.env 가 비어 있다**: 다른 PC 에서 토스를 쓰려면 키가 있는 PC 에서 `scripts\export-secrets.ps1` 을 먼저 돌린다.
- **토스 분봉 규격**: 한 번에 최대 200개, 초당 20회, 봉 시각은 끝나는 시각이다(네이버는 시작 시각 → `toss_min` 이 1분 당긴다). 거래량은 NXT 포함이라 네이버의 1.4~1.7배.
