# 2026-10-14 — 자체 HAOS 차량 수신기로 전환

사용자는 D1 용량/일일 쓰기 제한을 피하기 위해 Cloudflare 중계·저장을 자체 서버로
이전하도록 요청했고, 기존 기능 전체 보존과 수정 전 이유·검증 기록을 요구했다.
사전 계획은 carrot-ha `docs/direct-vehicle-receiver-plan-2026-10-14.md`, 3c9e4f0로
실행 코드 수정 전에 원격 게시됐다. companion 실행 코드는 8303aae부터 준비됐다.

## 변경과 보존

- direct_connection.py: 검증된 HTTPS 설정을 runtime /data/carrot_ha에 원자 저장,
  JSON stdin setup와 명시적 rollback. 기존 connection.json·Git 소스·outbox는 수정하지 않음.
- direct_receiver.json: 기존 Worker URL → 사용자가 알려준 DuckDNS 직접 수신 경로의
  공개 매핑만 포함. 토큰·장치 ID는 Git에 없음. load_config가 기존 장치 인증으로
  자체 서버 /api/provision에서 새 설정을 받고 영구 저장. 실패 시 cloud 복귀 없이 대기.
- collector.py: telemetry/trip 경로·샘플/계산·독립 lane·재전송·성공 후 삭제 유지.
- param_sync.py: 기존 15/3초·backoff·검증/readback·명시적 실패/ACK 재시도 유지.
  수신기 identity별 별도 처리 DB로 기존 숫자 queue ID 충돌 방지. 레거시 DB 유지.
- terminal.py: 직접 수신기 prefix를 허용, 원래 HA 직접 WSS/권한 취소/주차 차단 유지.
  원본 영상/rlog는 기존 HA 직접 전송; 카메라와 CAN decoder 코드 변경 없음.

## 검증과 배포

- 직접 설정·프로비저닝 실패/성공·ID 충돌/재전송 4, 기존 param polling 4 통과.
- 기존 데몬 69 중 Windows fcntl 2, symlink 권한 1, bash 경로 1 환경 실패.
  나머지 65 통과. Windows 오류를 Comma 장애로 해석하지 않는다.
- 자체 서버 수신기 및 외부 HTTPS health 200 확인. HA 수신 코드·설정은 사용자
  재시작 이후 적용하도록 준비하며 companion changelog에 상세 상태를 기록한다.
- 이 저장소 source는 Git 커밋/푸시 후 사용자 Pull/재부팅으로만 설치한다.
  기기 SSH/SCP 소스 수정, 에이전트 기기 Pull·재부팅 없음.
- 사용자는 기기가 켜져 있고 인터넷 정상이라고 확인했지만 실제 데몬의 신규
  직접 수신·HA 재시작 중 기록·명령·카메라·로그 검증은 미완료다.
- 기존 Cloudflare DB는 rollback과 미이관 자료를 위해 삭제하지 않는다.
