> 과거 Cloudflare 서버 설명은 폐기된 기록입니다. 현재 설치/복구는 companion carrot-ha의 docs/CLEAN_INSTALL_RECOVERY.md를 따릅니다.

# HA 클라우드 상태/주행 송신 분리 — 2026-10-14

- 원인: ~~Cloudflare~~ ~~D1~~ DB 용량 초과로 오래된 텔레메트리 HTTP 500이 반복됐다.
  최신 상태 우선 송신은 갱신되지만 동일 FIFO 뒤의 16:06~17:50 주행이 지연됐다.
- collector.py에 상태/주행 전용 송신 스레드를 두고 Store.first_for로 독립 FIFO를
  조회한다. 실패 자료와 기존 SQLite state/outbox는 보존하며 명시적 서버 ACK 뒤에만
  삭제한다. 상태 최신/과거 번갈아 송신, 재시도 상한 120초와 수집 주기는 유지한다.
- 기존 delivery.json은 상태 송신 결과, delivery-trips.json은 주행 송신 결과로 분리해
  같은 임시 파일을 두 스레드가 동시에 쓰지 않게 한다.
- lane/created 인덱스를 추가해 대기열이 클 때 idle 주행 조회와 상태 FIFO/최신 조회가
  모든 본문을 반복 스캔하지 않게 한다. 기존 대기열 내용·순서·ACK는 유지한다.
- 영상/rlog는 기존 terminal.py의 별도 HA 직접 전송 작업을 유지한다. 파일 송신 실패나
  완료를 일반 주행 업로드 조건으로 사용하지 않는다.
- 신규 outbox lane·param polling 5건 통과. 전체 Windows 데몬 69건 중 fcntl 모듈
  2건·symlink 권한 1건·bash Windows 경로 1건의 환경 실패는 실기 장애가 아니다.
- companion carrot-ha의 driving-logs/CHANGELOG.md에 클라우드/HA 검증·배포 결과를
  함께 기록한다. 설치 전까지 실기 송신 분리 검증 완료로 보고하지 않는다.
- 사용자는 게시 후 `cd /data/openpilot && git pull --ff-only && sudo reboot`로 적용한다.
  기기 SSH/SCP 소스 수정과 에이전트 재부팅은 수행하지 않는다.
