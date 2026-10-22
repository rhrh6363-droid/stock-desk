# 작업 루트 (주식 · 유튜브)

> 이 파일은 `stock\stock-desk\scripts\workspace.ps1` 이 `scripts\workspace\ROOT_CLAUDE.md` 로 덮어쓴다. 고칠 때는 원본을 고친다.

사용자는 **PC 두 대**로 같은 작업을 한다. 루트 이름은 PC 마다 다르다(`D:\github`, `E:\Claude` 등). **루트 아래 구조는 두 PC 가 똑같아야 한다.**

## 구조 (이 밖의 폴더를 루트에 만들지 않는다)
| 묶음 | 폴더 | 저장소 | 무엇 |
|---|---|---|---|
| `stock\` | `stock-desk` | `rhrh6363-droid/stock-desk` (공개) | 특징주 수집·장중 5분 수집·대시보드(GitHub Pages). bootstrap·workspace 스크립트가 여기 있다 |
| | `backtest` | `rhrh6363-droid/backtest` (비공개) | 교재 단타 규칙을 과거 분봉에 대입. `..\stock-desk` 모듈을 쓴다 |
| | `simulation` | `rhrh6363-droid/simulation` (비공개) | 장중 5분 가상 매매. `..\stock-desk` 모듈을 쓰고 결과를 stock-desk `docs/` 로 푸시 |
| `youtube\` | `youtube` | `rhrh6363-droid/youtube` (비공개) | 영상 제작. 기준 문서 `STANDARDS.md` |
| | `siyun` | `rhrh6363-droid/siyun` (비공개) | 시윤주식 강의 교재 81편. youtube 가 `..\siyun\교재` 로 읽는다 |

- **주식·유튜브와 상관없는 일(SAP·회사 업무 등)은 이 루트에 두지 않는다** → `D:\work\` 같은 별도 폴더에서 Claude 를 연다 (메모리도 따로 쌓인다).
- 같은 저장소를 두 번 클론하지 않는다 (예전 `trading` = stock-desk 중복 사본이었다).
- 폴더 사이 참조는 **상대 경로**(`..\stock-desk`, `..\siyun`)로만 한다. `D:\github\…`·`E:\Claude\…` 를 코드에 박지 않는다.

## 작업 스케줄러 (이 PC 기준)
| 작업 | 실행 위치 |
|---|---|
| `장중수집` | `stock\stock-desk\scripts\장중수집.vbs` (5분, 평일 장중) |
| `특징주 오전집계` · `특징주 일일집계` | `stock\stock-desk\scripts\일배치.vbs` · `run_daily.vbs` |
| `모의투자 SIMULATION` | `stock\simulation\run_tick.vbs` |
| `백테스트 분봉저장 BACKTEST` | `stock\backtest\run_fetch.vbs` |

## 자동 커밋·푸시 (Claude 훅)
`.claude\settings.json` 의 **Stop 훅**(응답이 끝날 때마다, 백그라운드)과 **SessionEnd 훅**(세션을 닫을 때)이
`stock\stock-desk\scripts\auto-commit.ps1` 을 돌린다 → `stock\*`·`youtube\*` 저장소에서 바뀐 것(코드·.md 전부)을 커밋하고 pull --rebase 뒤 push.
- 빼는 것: stock-desk 의 `app/data`·`docs/data`(수집기가 직접 커밋), `*.err`·`*.log`·`*.tmp`, 키로 보이는 파일·내용(걸리면 그 저장소는 커밋 안 함).
- 기록: `%USERPROFILE%\.stock-desk\auto-commit.log`. 충돌이면 커밋은 로컬에 남고 다음 응답 때 다시 올린다.
- 그래서 응답이 끝난 뒤 IDE 를 꺼도 된다. 의미 있는 단위로 남기고 싶은 작업은 지금처럼 직접 메시지를 써서 커밋해도 된다.

## 세션을 열면
`.claude\settings.json` 의 SessionStart 훅이 `stock\stock-desk\scripts\session-check.ps1` 을 돌린다(코드 pull · 구조 점검 · PC 점검).
**`[구조 변경 필요]` 가 나오면 다른 작업보다 먼저** 안내된 `workspace.ps1` 을 실행한다. git 폴더 이동은 Claude 샌드박스가 막으므로 사용자에게 `! powershell -NoProfile -ExecutionPolicy Bypass -File <경로>\workspace.ps1` 로 실행해 달라고 한다.

## 새 PC
```
git clone https://github.com/rhrh6363-droid/stock-desk.git <루트>\stock\stock-desk
powershell -NoProfile -ExecutionPolicy Bypass -File <루트>\stock\stock-desk\scripts\workspace.ps1   # 나머지 저장소를 제자리에 받는다
powershell -NoProfile -ExecutionPolicy Bypass -File <루트>\stock\stock-desk\scripts\bootstrap.ps1   # 패키지·pc-sync·스케줄러
```
