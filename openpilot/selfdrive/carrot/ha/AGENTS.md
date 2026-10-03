# Carrot HA daemon performance contract — 2026-10-01

This daemon belongs to helico717/openpilot, branch carrot-wip-model_selector-ha.
The user's two-repository instructions take precedence over unrelated top-level
branch-consolidation history. HA/Worker/card changes belong to helico717/carrot-ha.

- Commit-managed source only. Never patch or copy code into Comma through SSH/SCP
  or the reverse terminal. Deployment is a clean Git update and restart.
- Runtime state belongs outside the Git tree. Parameter queue ACK identities use
  /data/carrot_ha/param_sync.sqlite3; preserve old identities with the read-only
  legacy database migration. Do not erase them or reapply already handled IDs.
- Keep parameter polling at 15s idle, 3s during an expiring active-settings lease
  or pending work, with 15–120s failure backoff. Command handling precedes periodic
  catalog publication. Do not restore unconditional 3s polling to hide latency.
- Idle-to-active discovery is polling, not push: allow up to the idle interval plus
  network/processing time. Keep local validation, readback and failure ACKs; do not
  falsely report a command as applied from its requested value alone.
- CAN sampling/telemetry cadence, driving interlocks, and terminal revocation
  checks are separate correctness contracts. Do not slow them just to save requests.
- Any future optimization requires measured latency/usage evidence and relevant
  tests. The maintained design is a baseline, not proof of an absolute optimum.
- Run ha/tests/test_param_polling.py and the daemon test suite when touching this
  path. Full release validation also includes carrot-ha's incremental Worker and
  dashboard tests, D1 migration before Worker deployment, and operational 24-hour
  quota/freshness observation. Local results are not physical-device validation.

## Deployment ownership — 2026-10-03

- Carrot HA work includes preparing an installable update. Unless the user
  explicitly requests local-only work for the current task, the agent must
  implement, validate, commit and push daemon changes to
  `origin/carrot-wip-model_selector-ha`, then verify the remote commit.
  Never leave local source changes for the user to commit or push.
- The user only pulls the published commit on Comma and reboots:
  `cd /data/openpilot && git pull --ff-only && sudo reboot`.
  Do not add `git reset --hard` by default or reboot the device on the user's behalf.
- In the companion `helico717/carrot-ha` repository, the agent owns HA version
  bumps within 0.8.x, release notes, main/tag pushes and verification that the
  GitHub Release/Actions succeeded. The user only updates through HACS and
  restarts HA. Follow that repository's AGENTS.md for the complete workflow.
- The agent also owns required Worker/D1 changes and deployment, with migrations
  before the Worker. Do not deploy unchanged services. For instructions-only
  changes, commit and push without a new runtime release.
- If publication is blocked, report the actual remaining step and blocker;
  do not claim the device can install unpublished local changes.

## 자동 동기화 실패 대응 및 보고 기준 — 2026-10-03

- 실패 알림을 받으면 최신 실행의 링크·시각·실행 브랜치·실패 단계와 로그를 확인한다.
  과거 실패 이력과 수정 후 신규 실패를 구분한다. 로그 없이 같은 원인으로 단정하지 않는다.
- 원인을 워크플로 설정 충돌, 실제 소스 충돌, 인증·권한, 네트워크, 동시 푸시 등으로
  구분하고 증거를 기록한다. 재실행만 반복하지 말고 원인에 맞는 수정부터 수행한다.
- 예약 실행은 기본 `carrot-wip` 브랜치의 워크플로를 사용하고,
  `carrot-wip-model_selector-ha`를 checkout해 병합한다. CI 변경 시 두 경로에 필요한
  수정이 반영됐는지 확인한다. 기본 브랜치에는 관련 CI 수정만 반영한다.
- `SYNC_PAT` 없이 동기화할 때는 fork의 `.github/workflows/` 전체 트리를 유지한다.
  파일 추가·수정·삭제와 modify/delete 충돌을 모두 처리하고, 병합 커밋 전후 트리가
  동일함을 검사한다. 실제 소스 충돌은 자동으로 한쪽을 버리지 말고 병합을 중단해
  충돌 파일과 양쪽 변경 의도를 조사한 뒤 통합한다. 무조건 ours/theirs나 force push로
  실패를 숨기지 않는다.
- 관련 충돌을 재현하는 회귀 테스트와 코드 보존 검증을 수행하고 커밋·푸시한다.
  수정된 워크플로로 새 실행을 시작해 실제 성공과 원격 반영을 확인한다.
  이전 실행 재시도는 이전 워크플로를 사용할 수 있으므로 신규 실행과 구분한다.
- 보고 상태는 **원인 확인 중 / 원인 확인·수정 중 / 수정 푸시·실행 검증 중 /
  실제 실행 성공 / 차단됨**으로 구분한다. 로컬 테스트나 푸시만으로 해결 완료를
  주장하지 않는다. 진행 중 보고에는 확인된 증거와 다음 확인 항목을 제공하고,
  차단됐으면 이유와 필요한 최소 조치를 정확히 안내한다.
- 처리 기록은 기존 관련 문서에 발생·검증 시각, 실행 링크, 원인, 이전 수정의 한계,
  수정 방향·커밋, 테스트, 실제 실행 결과, 미확인 사항을 추가한다.
  특정 충돌 재발 방지를 모든 미래 충돌의 영구 해결로 설명하지 않는다.
- Mac 테스트 오류와 실제 Comma 장애를 구분한다. 실기 로그 없이 기기 장애로 보고하지
  않는다. 사용자는 HACS 업데이트·HA 재시작 및 원격 터미널의 연결·Git Pull·재부팅
  버튼만 조작하며, 분석·코드 통합·커밋·푸시·발행은 에이전트가 담당한다.
  감시 자동화는 별도 요청이 있을 때만 생성한다.

### 처리 기록: 2026-10-03 자동 동기화 반복 실패

- 실패 실행: https://github.com/helico717/openpilot/actions/runs/37118895430
  (한국 시간 20:12 실행). Fetch and Merge Upstream 단계에서
  `.github/workflows/native-cpu.yaml`의 modify/delete 충돌 발생.
  fork에서는 삭제됐지만 upstream에서는 수정된 파일이었다.
- 이전 방식은 성공한 merge 뒤에 워크플로를 복원했다. 충돌로 merge가 종료되면 복원
  단계에 도달하지 못하므로 추가·삭제 보존만으로 이 문제를 해결할 수 없었다.
- 수정: `.github/scripts/sync_upstream_model_selector.sh`에서 merge를 커밋 없이 수행하고,
  워크플로의 충돌 index를 정리한 뒤 fork 트리를 복원한다. 남은 소스 충돌은 abort하고,
  충돌이 없을 때만 커밋·푸시한다. 같은 동기화의 동시 실행도 직렬화한다.
- 수정 커밋: Comma 브랜치 `0a235b74`, 기본 브랜치 CI `2de2596c`.
  실제 upstream 병합 재현 및 워크플로 충돌 해결·소스 충돌 중단 테스트 통과.
- 한국 시간 20:59 신규 실행 성공 확인:
  https://github.com/helico717/openpilot/actions/runs/37121411043
  자동 병합 결과 `e309bf15`가 원격 Comma 브랜치에 반영됨.
  이는 당시 실행의 성공 기록이며, 미래 실행 상태는 새 로그로 확인해야 한다.
- 같은 시기 SOC 오표시의 별도 원인은 CAN 초기화 코드 `102350Wh`를 잔량으로
  수용한 것이었다. 수집기 무효값 제외 및 HA 방어 처리를 반영하고 `v0.8.10` 발행.
  로컬 전체 Comma 검사에 남은 카메라·터미널 4건은 기존 테스트 문제이며
  실제 기기 장애가 확인된 것은 아니다.
