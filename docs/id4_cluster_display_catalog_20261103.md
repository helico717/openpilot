# ID.4 순정 클러스터 표시 전체 목록

- 조사일: 2026-11-03 (한국 시간)
- 기준: `helico717/openpilot`, `carrot-wip-model_selector-ha`, 실행 코드 `cd5bfae1aa068bdf5d39dae34d7a7e14df4b1385`.
- 대상: ID.4 MEB 순정 계기판. Comma 화면·별도 USB 클러스터·HA 대시보드와 구분한다.
- 코드로 확인한 송신 조건이다. 차량의 언어·소프트웨어·화면 구성에 따른 실제 문구/색/수락 여부까지 새로 실차 검증한 것은 아니다.
- 아래의 한국어 이름은 기능 설명이며, 따옴표로 적은 전방/인식됨 외에도 실제 차량 번역은 다를 수 있다.

## 적용 및 업데이트

HA 원격 터미널에서 연결 후 다음 명령으로 적용한다. 브랜치는 `carrot-wip-model_selector-ha`여야 한다.

```sh
cd /data/openpilot && git pull --ff-only && sudo reboot
```

`git fetch origin`의 Receiving objects/Resolving deltas는 정상 다운로드 과정이다. fetch만으로 실행 소스는 교체되지 않는다.
클린 설치 후 로컬에 없는 이력이 많으면 첫 다운로드가 커질 수 있다. fetch가 끝나 프롬프트가 돌아온 다음 pull을 실행한다.
pull 실패 시 `&&` 때문에 재부팅하지 않는다. 이 문서 추가만을 위한 별도의 기기 업데이트는 필요 없다.

## 표시 방식과 공통 조건

- 임의 문자열을 출력하는 기능이 아니다. CAN으로 차량에 내장된 그림/문구 번호와 속도·거리·상태를 보낸다.
- 내비/ACC 표시는 기존 `openpilotLongitudinalControl` MEB 경로에서 송신한다. 순정 종방향·passive/dashcam·Comma 전원 꺼짐은 별도 지원하지 않는다.
- 여기서 'ACC 활성'은 ACC 상태 3(활성) 또는 4(가속페달 개입)이다. 정차대기는 상태 3만 해당한다.
- 이번 수정으로 '전방'만 ACC 활성 조건에서 분리했다. 다른 제어 안내의 표시 조건은 유지한다.
- 내비 이벤트 배너는 동시에 하나다. 단속 정보가 가장 우선한다. 커브/회전/출구/로터리/병목은 진행 중이면 정차대기를 대체할 수도 있다.
- 커브·회전·출구·로터리·병목은 새 이벤트 번호가 선택되면 약 1.2초(20회, 약 16.7Hz) 큰 배너 후 작은 아이콘으로 유지한다.
  동일 종류에서 속도만 바뀌는 것은 새 배너 조건이 아니다. 이벤트가 종료되거나 다른 것으로 바뀌면 상태가 갱신된다.

## 1. 현재 자동 송신하는 내비/정차 배너

| 항목 / 이벤트 번호 | 무슨 정보인가 | 언제 표시 요청하는가 | 어떻게 표시하는가 |
| --- | --- | --- | --- |
| 단속 '전방' / 4 | 단속카메라·구간단속 등 현재 활성화된 속도 경고 | carrotMan alive/valid, activeCarrot>=2, xSpdType>=0 및 !=22, xSpdLimit>0. ACC 활성 여부 무관 | 제한속도 표지 그림 + '전방' + 속도. 조건 유지 중 큰 배너 유지. 작은 아이콘으로 전환하지 않음 |
| 도로 제한속도 '인식됨' / 5 | 일반 도로 제한속도가 속도 제어 후보로 선택됨 | ACC 활성, desiredSource='road', 0<desiredSpeed<200, 더 높은 우선 이벤트 없음. 기억한 도로 제한속도 숫자가 달라짐 | 제한속도 표지 + '인식됨' + 도로 제한값. 약 1.2초 후 km/h 작은 아이콘. 같은 값으로 돌아오면 반복하지 않음(프로세스 재시작 시 기억 초기화) |
| 우커브 / 7 | 모델 기반 커브 감속 안내 | ACC 활성, 0<abs(vTurnSpeed)<120km/h이며 현재속도보다 3km/h 넘게 낮음, vTurnSpeed>0 | 오른쪽 커브 그림 + 커브 목표속도. 약 1.2초 후 오른쪽 커브 아이콘 |
| 좌커브 / 8 | 모델 기반 커브 감속 안내 | 위 조건에서 vTurnSpeed<0 | 왼쪽 커브 그림 + 커브 목표속도. 약 1.2초 후 왼쪽 커브 아이콘 |
| 교차로/회전 / 9 | ATC의 좌·우회전 안내 | ACC 활성, atcType이 turn left/right 또는 atc left/right. prepare는 제외. 설정 회전속도>0 | 교차로 그림 + AutoTurnControlSpeedTurn 값. 좌/우회전을 서로 다른 배너 그림으로 나누지는 않음. 약 1.2초 후 교차로 아이콘 |
| 고속도로 출구/분기 / 11 | ATC가 인식한 좌·우 분기/출구 | ACC 활성, atcType=fork left/right, nRoadLimitSpeed>0 | 출구 그림 + 도로 제한속도. 약 1.2초 후 출구 아이콘. 출구 방향을 별도 그림으로 구분하지 않음 |
| 로터리 / 10 | 내비 회전교차로 접근 | ACC 활성, xTurnInfo=5, 0<xDistToTurn<500m | 로터리 그림 + 설정 회전속도(값>0인 경우). 약 1.2초 후 로터리 아이콘 |
| 병목 / 13 | 티맵 SDI 병목 안내 | ACC 활성, szSdiDescr가 병목지점/Bottleneck point/瓶颈路段 | 병목 그림. 별도 목표속도는 지정하지 않음. 약 1.2초 후 병목 아이콘 |
| 정차대기/출발 가능 / 3 | ACC 활성 상태의 ESP 정차 홀드 | ACC 상태 3이고 esp_hold_confirmation=True. 상위 이벤트가 없을 때 | 순정 정차/출발대기 안내. 홀드 조건 유지 중 유지. 초록 신호 인식이나 앞차 출발 감지 문구와 같지 않음 |

단속 표시의 실제 조건은 '카메라만'으로 제한된 분류가 아니다. 상위 수집기가 xSpdType으로 내보낸 유효 속도 경고가 대상이고, 방지턱 22만 명시적으로 제외한다.
연결 해제는 기존 내비 소스 타임아웃을 따른다. 소켓이 끊긴 순간 즉시 사라진다고 보장하지 않는다.

도로 제한 표지는 실제 표지판 카메라 인식이라는 뜻이 아니다. 내비 데이터가 원천일 수 있다.
도로 제한 '인식됨'에는 오프셋을 더하기 전 nRoadLimitSpeed를 보내고, 제어 목표는 별도로 제한속도+오프셋을 사용할 수 있다.

## 2. 현재 송신하는 ACC 숫자·차량·차간거리·작은 아이콘

| 항목 | 의미/화면 형태 | 송신 기준 및 주의점 |
| --- | --- | --- |
| ACC 꺼짐 | 비활성 ACC 상태 | 메인 스위치 꺼짐, 비활성, 고장 없음: 상태 0. 세부 그림/색은 차량이 결정 |
| ACC 대기 | 설정 가능/대기 상태 | 메인 스위치 켜짐, 비활성, 고장 없음: 상태 2 |
| ACC 작동 | ACC 활성 그림/상태 | CC.enabled이고 override 없음: 상태 3 |
| 운전자 가속 개입 | ACC override 상태 | CC.enabled이고 override 또는 가속페달 입력: 상태 4 |
| ACC 오류 | 고장/사용 제한 상태 | CS.accFaulted: 상태 6 우선. 새 고장 원인을 만들어 표시하는 것이 아니라 감지된 상태 반영 |
| 설정/목표 속도 숫자 | ACC 속도 숫자 | 보통 min(운전자 설정속도, 내비 desiredSpeed). xState=3이면 계획속도 경로를 사용. 실제 차량 속도계 숫자와 다름. 250km/h 이상은 미표시 코드 사용 |
| 제한속도 표지 숫자 | 전방/인식됨 배너의 원형 제한속도 표시 | 고정 속도 열거형으로 변환. 지원값: 5,7,10,15,20,25,30,35,40,45,50,55,60,65,70,75,80,85,90,95,100,110,120,130,140,150,160,200,250km/h. 중간값은 반올림한 입력 이하의 표지값 선택 |
| 이벤트 목표속도 | 커브/교차로/출구/로터리 배너에 딸리는 속도 | 커브속도·설정 회전속도·도로 제한값 중 이벤트별 값. 작은 아이콘 전환 후 이벤트 속도는 0으로 보냄 |
| 내 차 그림 | ACC 화면의 자차 | ACC 상태 3에서 활성값 1, 그 외 0. 이 경로의 빨간 경고 자차값은 현재 사용하지 않음 |
| 도로 강조 | ACC 도로 영역 강조 | 상태 3/4에서 Street_Color=1, 그 외 0. 실제 색 이름은 차량 테마에 의존 |
| 앞차 그림 | 앞차 감지 | longitudinalPlan.hasLead에 따라 표시/숨김. 그림 종류는 항상 자동차(3); 트럭/오토바이/자전거 분류 표시를 하지 않음 |
| 앞차 위치/거리 | 계기판에서 앞차가 놓이는 거리 | radarState.leadOne.dRel 사용. 0이 아니면 최소8m로 제한해 송신. 반드시 '몇 m' 숫자 텍스트로 표시한다는 뜻은 아님 |
| 앞차 강조 | ACC 추종 화면의 앞차 밝기 | 작은 상태 아이콘을 보내지 않을 때 ACC 상태3은 Lead_Brightness=3. 상태4는 기본0 |
| 선택 차간거리 막대 | 선택된 추종 간격 | selfdriveState.personality.raw+1. DBC는1~5단계 지원하지만 현재 선택 범위는 personality 값에 따름 |
| 차간거리 단계별 위치 | 거리 막대의 기하학적 위치 | 선택 단계에 max(8m, 현재속도×1.45초), 다른 단계0. 실제 플래너의 동적 추종시간을 그대로 그린다는 뜻은 아님 |
| 차간거리 표시 색/노출 | 거리 막대 표시 요청 | 상태2/3/4에서 색값1. 상태0에서는 차간거리 노출 요청을 끔 |
| km/h 작은 아이콘 / 4 | 도로 제한속도 제어 안내 | 도로 제한 인식 배너 종료 후. 앞차가 실제 속도를 제한하는 상태에서는 이 아이콘을 양보. 앞차 지배 변경에32 HUD회(약1.9초) 지연 적용 |
| 좌커브 작은 아이콘 / 6 | 좌커브 안내 지속 | 이벤트8의 큰 배너 종료 후. 배너/아이콘의 좌우 번호가 서로 달라 특례 매핑 |
| 우커브 작은 아이콘 / 7 | 우커브 안내 지속 | 이벤트7의 큰 배너 종료 후 |
| 교차로 작은 아이콘 / 8 | 교차로/회전 안내 지속 | 이벤트9 큰 배너 종료 후 |
| 로터리 작은 아이콘 / 9 | 회전교차로 안내 지속 | 이벤트10 큰 배너 종료 후 |
| 출구 작은 아이콘 / 10 | 출구/분기 안내 지속 | 이벤트11 큰 배너 종료 후 |
| 병목 작은 아이콘 / 12 | 병목 안내 지속 | 이벤트13 큰 배너 종료 후 |

작은 상태 아이콘과 앞차 강조는 같은 Lead_Brightness 필드를 공유한다. 한 필드에 둘을 동시에 보낼 수 없다.

## 3. 차선·핸들·Travel Assist 표시

| 항목 | 의미/화면 형태 | 현재 동작 |
| --- | --- | --- |
| 차선 보조 녹색 상태 | 조향 보조 활성 상태 | latActive이고 steeringPressed=False일 때 LDW 녹색 LED 요청 |
| 차선 보조 노란색 상태 | 조향 보조 중 운전자 핸들 개입 | latActive이고 steeringPressed=True일 때 LDW 노란색 LED 요청 |
| 좌/우 차선 그림 | 차선 보조 양쪽 경계 | left/rightLaneVisible과 latActive로 상태 결정. 현재 controlsd는 양쪽 Visible=True로 설정하므로 그림만으로 실제 모델의 양쪽 차선 인식을 보장하지 않음 |
| 좌/우 차선이탈 강조 | 어느 쪽 차선이탈인지 | 유효 driverAssistance의 left/rightLaneDeparture를 LDW 좌/우 상태에 반영. 실차 표현 색상은 별도 확인 필요 |
| '핸들을 잡으세요/조향을 인계하세요' 계열 | 일반 조향 인계 알림 | visualAlert가 steerRequired 또는 ldw이면 LDW_Texte=8. 코드 주석상 흰색 일반 인계. 현재 LDW_Gong=0으로 별도 차임 요청 없음 |
| Travel Assist 핸들/보조 상태 | 차량 내장 TA/핸들 상태 표시 | 순정 TA 가용성이 있을 때 TA_01 송신. CC.enabled이면4(enabled), 아니면2(ready). latActive와 완전히 같은 조건은 아님. 실제 핸들 아이콘 색은 새 실차 확인 필요 |
| 순정 핸즈오프 표시 | 순정 시스템이 판단한 손 놓음 표시 | EA_02의 ACF_Lampe_Hands_Off를 중계. 별도 OP DM 단계별 아이콘으로 직접 매핑하지 않음 |
| 좌/우 깜빡이 요청 | 순정 EA 경로의 방향지시 요청 | 순정 깜빡이가 꺼져 있고 EA_Blinken=0일 때 OP 좌1/우2를 삽입할 수 있음. 별도의 임의 텍스트가 아님 |

KLR 정전식 핸들 모듈이 있으면 latActive 중 '손 접촉' 데이터를 보낸다. 이것은 문구 표시 명령이 아니지만 순정 핸즈오프/비상정지 경고 판단에 영향을 준다.
OP DM의 driverMonitoringAlert는 공통 HUD에 존재해도 현재 MEB 표시 함수가 직접 소비하지 않는다. 현대/기아 전용 DM 단계별 표시와 혼동하지 않는다.

## 4. 순정 Emergency Assist 경고 중계 전체 목록

아래는 OP가 새로 감지해 만드는 메시지가 아니라, 순정 EA_02를 받아 복사하는 경고다.
STOCK_EA_PRESENT이고 순정 스냅샷이 있어야 한다. 조향 활성 중 EA_Funktionsstatus가0/1/7/8이면 EA_Texte를0으로 지우므로 모든 항목이 무조건 그대로 보이는 것은 아니다.
한국어는 DBC 독일어 의미 번역이며 실제 계기판 한국어 문구와 동일하다고 단정하지 않는다.

| EA_Texte | 정보 의미 | 표시 방식 |
| --- | --- | --- |
| 0 | 표시 없음 | EA 텍스트를 표시하지 않음 |
| 1 | 운전자 활동 부족 | 차량 내장 비상정지 보조 경고 문구 |
| 2 | 비상정지 보조 활성, 운전 인계 필요 | 차량 내장 인계 경고 |
| 3 | 자동 비상정지 수행 중 | 차량 내장 비상정지 진행 경고 |
| 4 | 자동 비상정지 완료 | 차량 내장 완료 안내 |
| 5 | 긴급통화 연결 중 | 차량 내장 긴급통화 안내 |
| 6 | 비상정지 보조 비활성 | 차량 내장 해제 안내 |
| 7 | 비상정지 개입 중단 | 차량 내장 중단 안내 |
| 8 | 운전자 활동 부족 2단계 | 차량 내장 추가 경고 |
| 9 | 순간 졸음 감지 | 차량 내장 졸음 경고; OP 운전자 카메라의 직접 감지 결과라는 뜻은 아님 |
| 10 | Lane Assist 조향 인계 | 차량 내장 조향 인계 안내 |
| 11 | ACA 운전 인계 | 차량 내장 주행보조 인계 안내 |
| 12 | 갓길 이동 | 차량 내장 비상보조 갓길 변경 안내 |
| 14 | 비상정지 보조 일시 사용 불가 | 차량 내장 일시 제한 안내 |
| 15 | 비상정지 보조 고장 | 차량 내장 고장 안내 |

13은 이 DBC에서 의미가 정의되지 않았다.
같은 중계 프레임의 STP_Primaeranz는0=없음,1=가용,2=활성,3=인계,4=활성 경고,5=사용 불가를 포함한다.
STP 약어의 실제 차량 기능명/화면 모양은 이 조사에서 확정하지 않았다.
비상등·제동등 점멸과 인포테인먼트 음량·실내등·도어 요청 필드도 원본을 복사하지만, 이들은 클러스터 텍스트 항목이 아니다.

## 5. 그림/코드는 알려져 있지만 현재 자동 표시하지 않는 항목

| 항목 | 알려진 표시 | 현재 사용하지 않는 이유/상태 |
| --- | --- | --- |
| 일반 S자 커브 / 이벤트6 | 일반 커브 그림 | helper에는 존재하지만 실제 호출은 예측 플래그False. 현재 커브는 좌7/우8로 전송 |
| 정체 / 이벤트12, 작은 아이콘11 | 정체 그림 | 실차 스캔 매핑은 주석에 있으나 현재 선택 분기가 없음. 앞차 정차를 이 그림으로 자동 변환하지 않음 |
| 내리막 / 이벤트14, 작은 아이콘13 | 내리막 그림 | 현재 선택 분기 없음 |
| 오르막 / 이벤트15, 작은 아이콘14 | 오르막 그림 | 현재 선택 분기 없음 |
| 빨간 긴급 조향 인계 / LDW_Texte4 | 긴급 인계 그림/문구 | MEB 상수에는 있으나 현재 controller는 일반8만 선택 |
| LDW 차임1/비프2 | 차량 경고음 | DBC에 있으나 현재 sound_alert=0으로 호출 |
| 빨간 앞차/제동 경고 + 비프 | 충돌경고 표시 조합 | 패커 분기는 있으나 MEB controller가 fcw_alert=False로 고정. Comma 자체 FCW 및 순정 레이더 AEB 경로와 구분 |
| 트럭2·오토바이4·자전거5 앞차 그림 | 차종별 앞차 아이콘 | DBC에는 있으나 현 코드는 앞차를 자동차3으로만 전송 |
| 신호등/신호 제어·기타 문자 | 아래 DBC 기본 문구 | 현재 MEB 패커에서 해당 주 텍스트/신호 제어 필드를 선택하지 않음. Comma 화면에 신호가 보여도 이 클러스터에 직접 신호등을 그린다는 뜻은 아님 |

ACC_Events 1/2 및 Lead_Brightness 1/2/15는 현재 코드/매핑 기록에서 표시 의미를 확정하지 않았다. 임의로 이름을 붙이지 않는다.

## 6. DBC 기본 텍스트 사전 — 현재 송신 목록과 구별

다음은 차량 프로토콜에 정의된 텍스트 선택지다. 표시 가능성의 자료이며 현재 OP가 호출하는 목록은 아니다.
`ACC_Texte_Primaeranz_02`는 현 패커가 지정하지 않아 기본0이다.
`ACC_Texte_Zusatzanz_02`도 현재 fcw_alert=False 때문에0이다. DBC 열거형과 기존 실차 주석이 불일치할 수 있어 새로 코드를 보내 확인하지 않았다.

### ACC_Texte_Primaeranz_02

| 번호 | 정보 의미 | DBC 원문 |
| --- | --- | --- |
| 0 | 표시 없음 | `keine Anzeige` |
| 1 | ACC 심볼+속도 | `VDA_ACC_Symbol_YYY_kmh_mph` |
| 2 | 커브 심볼+속도 | `Kurven_Symbol_YYY_kmh_mph` |
| 3 | 제한속도 심볼+속도 | `Tempolimit_Symbol_YYY_kmh_mph` |
| 4 | ACC 출발 준비 | `ACC_anfahrbereit` |
| 5 | 선택 차간거리 | `eingestellte_Zeitluecke` |
| 6 | 문 열림 | `Tuer offen !` |
| 7 | 전방 정지 물체 | `Stehendes Objekt voraus` |
| 8 | 점 3개 상태 | `o  o  o` |
| 9 | ACC 꺼짐 | `ACC aus` |
| 10 | ACC 출발 중 | `ACC startet` |
| 11 | ACC 센서 시야 확인 | `ACC Sensor Sicht !` |
| 12 | ACC 사용 불가 | `ACC nicht verfuegbar` |
| 13 | ACC 오류 | `ACC Fehler` |
| 14 | ESP 개입 | `ESP Eingriff` |
| 15 | ESP 비활성 | `ESP PASSIV !` |
| 16 | 주차브레이크 | `Parkbremse !` |
| 17 | 속도 한계 | `Geschwindigkeitsgrenze` |
| 18 | 변속 셀렉터 위치 | `Waehlhebelposition !` |
| 19 | 운전자 안전벨트 미착용 | `Fahrer Gurtschloss offen !` |
| 20 | 기어 위치 | `Schalthebelposition !` |
| 21 | 엔진 회전수 | `Drehzahl !` |
| 22 | 경사로 하강 제어 활성 | `HDC aktiv` |
| 23 | 클러치 작동 | `Kupplung betaetigt` |
| 24 | 기어 선택 필요 | `Gang einlegen !` |
| 25 | 브레이크 과열 | `Bremse ueberhitzt !` |
| 26 | 경사 너무 큼 | `Steigung_Gefaelle_zu_gross` |
| 27 | 차간거리 | `ABSTAND` |
| 28 | 우측 추월 방지 | `Rechtsueberholen_verhindert` |
| 29 | 좌측 추월 방지 | `Linksueberholen_verhindert` |
| 30 | 교차로 그림 | `Kreuzungs_Symbol` |
| 31 | 로터리 그림 | `Kreisverkehr_Symbol` |
| 32 | 내리막 그림 | `Gefaelle_Symbol` |
| 33 | 제한속도·커브 보조 켜짐 | `Tempolimit_Kurvenassistent_ein` |
| 34 | 커브 보조 켜짐 | `Kurvenassistent_ein` |
| 35 | 제한속도 보조 켜짐 | `Tempolimitassistent_ein` |
| 36 | 속도 초과 주의 | `Achtung_Geschwindigkeitsueberschreitung` |
| 37 | 제한속도·커브 보조 사용 불가 | `Tempolimit_und_Kurvenassistent_nicht_verfuegbar` |
| 38 | 제한속도 보조 사용 불가 | `Tempolimit_nicht_verfuegbar` |
| 39 | 커브 보조 사용 불가 | `Kurvenassistent_nicht_verfuegbar` |
| 40 | 고속도로 출구 그림 | `Autobahnausfahrt_Symbol` |
| 41 | 정체 끝 그림 | `Stauende_Symbol` |
| 42 | 병목 그림 | `Engstelle_Symbol` |
| 43 | STP 가용 | `STP_verfuegbar` |
| 44 | 세로 신호등 | `Ampel_vertikal` |
| 45 | 가로 신호등 | `Ampel_horizontal` |
| 46 | STA 가용 | `STA_verfuegbar` |

### ACC_Texte_Zusatzanz_02

| 번호 | 정보 의미 | DBC 원문 |
| --- | --- | --- |
| 0 | 표시 없음 | `keine_Anzeige` |
| 1 | ACC 꺼짐 | `ACC_AUS` |
| 2 | 대기 | `Standby` |
| 3 | 운전자 오버라이드 | `UEBERTRETEN` |
| 4 | 차간거리 | `ABSTAND` |
| 5 | 차간거리 1단계 | `DISTANZ_1` |
| 6 | 차간거리 2단계 | `DISTANZ_2` |
| 7 | 차간거리 3단계 | `DISTANZ_3` |
| 8 | 차간거리 4단계 | `DISTANZ_4` |
| 9 | 차간거리 5단계 | `DISTANZ_5` |
| 10 | 차간거리 1단계(dynamic) | `DISTANZ_1__dyn` |
| 11 | 차간거리 2단계(dynamic) | `DISTANZ_2__dyn` |
| 12 | 차간거리 3단계(dynamic) | `DISTANZ_3__dyn` |
| 13 | 차간거리 4단계(dynamic) | `DISTANZ_4__dyn` |
| 14 | 차간거리 5단계(dynamic) | `DISTANZ_5__dyn` |
| 15 | 차간거리 1단계(comfort) | `DISTANZ_1__comf` |
| 16 | 차간거리 2단계(comfort) | `DISTANZ_2__comf` |
| 17 | 차간거리 3단계(comfort) | `DISTANZ_3__comf` |
| 18 | 차간거리 4단계(comfort) | `DISTANZ_4__comf` |
| 19 | 차간거리 5단계(comfort) | `DISTANZ_5__comf` |
| 20 | 차간거리 1단계(efficiency) | `DISTANZ_1__efficiency` |
| 21 | 차간거리 2단계(efficiency) | `DISTANZ_2__efficiency` |
| 22 | 차간거리 3단계(efficiency) | `DISTANZ_3__efficiency` |
| 23 | 차간거리 4단계(efficiency) | `DISTANZ_4__efficiency` |
| 24 | 차간거리 5단계(efficiency) | `DISTANZ_5__efficiency` |
| 25 | 차간거리 1단계(정체) | `DISTANZ_1__Stau` |
| 26 | 차간거리 2단계(정체) | `DISTANZ_2__Stau` |
| 27 | 차간거리 3단계(정체) | `DISTANZ_3__Stau` |
| 28 | 차간거리 4단계(정체) | `DISTANZ_4__Stau` |
| 29 | 차간거리 5단계(정체) | `DISTANZ_5__Stau` |
| 30 | 주의 | `ACHTUNG` |
| 31 | 차간거리 표시 | `Abstandsanzeige` |
| 32 | 차간거리 경고 활성 | `Abstandsanzeige_Warnung_aktiviert` |
| 33 | STA 가용 | `STA_verfuegbar` |
| 34 | 좁은 구간 | `Engstelle` |
| 35 | 우측통행 RUV 활성 | `RUV_aktiv_Rechtsverkehr` |
| 36 | 좌측통행 RUV 활성 | `RUV_aktiv_Linksverkehr` |
| 37 | STP 가용 | `STP_Verfuegbar` |
| 38 | AW 경고 임계1 | `AW_Warnschwelle_1` |
| 39 | AW 경고 임계2 | `AW_Warnschwelle_2` |
| 40 | AW 경고 임계3 | `AW_Warnschwelle_3` |
| 41 | AW 경고1 | `AW_Warnung_1` |
| 42 | AW 경고2 | `AW_Warnung_2` |
| 43 | AW 경고3 | `AW_Warnung_3` |

STA/STP/AW/RUV는 DBC 약어를 그대로 유지했다. 정확한 차량 기능명·실제 그림·음향까지 확인되지 않은 약어를 임의로 특정하지 않는다.
위 기본 문구는 엔진/클러치 등 다른 폭스바겐 차종용 공용 항목도 포함하므로 ID.4에서 실제 표시된다는 보장은 없다.

## 근거와 확인 상태

- `openpilot/selfdrive/controls/controlsd.py`: 내비 분류, 표시 속도, 앞차/차선/간격 데이터.
- `opendbc_repo/opendbc/car/volkswagen/carcontroller.py`: 이벤트 우선순위, 배너 시간, 아이콘, 표시 조건, 경고 비활성화.
- `opendbc_repo/opendbc/car/volkswagen/mebcan.py`: LDW/EA/TA/ACC 실제 송신 필드.
- `opendbc_repo/opendbc/car/volkswagen/values.py`: MEB 속도, LDW 경고 번호와 DBC 선택.
- `opendbc_repo/opendbc/car/volkswagen/mebutils.py`: 제한속도 표지 변환.
- `opendbc_repo/opendbc/dbc/vw_meb.dbc`: MK1 표준 열거형. MK2는 vw_meb_2024를 사용하므로 위 기본 문구 사전의 실차 적용을 동일하다고 보장하지 않는다.

소스와 DBC 대조 완료. 본 작업은 문서만 추가하며 실행 코드/버전/기기 파일을 바꾸거나 실차 CAN 스캔을 수행하지 않았다.
