# 구현 및 검증 기록

검증일: 2026-10-01. Windows 로컬 검증이며 서버 접속/배포는 수행하지 않았습니다.

## 생성된 프로젝트

- `vehicle_black_box/`: Kotlin 앱, Camera2 WebRTC capture, signaling, 카메라 lifecycle, Gradle 설정/wrapper, 주소 검증 테스트, 사용 안내.
- `vehicle_web_view/backend/`: FastAPI, WebRTC, 최신 입력, runtime adapter, frame/result pairing,
  mask overlay, 세션 종료/idle timeout, 상태/계측, uv 설정 및 lock, 환경 확인/실행 스크립트, 테스트.
- `vehicle_web_view/frontend/`: React/Vite 시청 화면, WebRTC 연결, 상태/성능 표시, Node 테스트, npm lock.

## 기존 파일 보호

`vehicle_perception_runtime_fix`의 기존 파일 13개를 작업 전후 SHA256으로 비교했고 모두 동일합니다.
기존 runtime, 기존 모델, 기존 데이터, 기존 산출물, AGENTS.md를 수정하거나 삭제하지 않았습니다.
모델을 다운로드하지 않았고 기존 cp-model/.venv도 변경하지 않았습니다.
새 Python 환경은 `vehicle_web_view/backend/.venv`에만 만들었습니다(GPU extra 미설치).
새 npm 환경은 `vehicle_web_view/frontend/node_modules`입니다.

## 실행한 검증

Backend:

```text
PYTHONDONTWRITEBYTECODE=1 .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider
21 passed
```

- 최신 프레임 유지/교체, 차단된 입력의 종료 wakeup.
- 불안정한 source index 대신 admitted runtime frame_id로 원본과 결과 연결.
- 입력 과부하 10,000회에서도 새 adapter의 pending/history 크기 제한 유지.
- 폰 식별/카메라/해상도/줌 보정 gate와 실제 프레임 크기 불일치 차단.
- mask packed bits 복원과 overlay가 원본 프레임을 변경하지 않는지 확인.
- 여러 viewer의 latest fan-out 독립성, thread/event-loop 출력 coalescing.
- 재연결에서 모델 재사용 및 새 stream 호출, 종료 시 worker join.
- 보정 대기 상태에서 모델 factory 미호출.
- 두 번째 세션 거부, 종료 token 검증, WebSocket 상태, 잘못된 촬영 옵션 거부.
- **실제 aiortc peer 두 개**를 통한 합성 1280×720 영상의 phone→server→viewer 송수신.
- 동일 WebRTC 전송에서 **fake inference engine**을 통한 추론 adapter 경로와 encode 계측 검증.
- 실제 uvicorn TCP server의 HTTP health 및 WebSocket metrics 연결.

추론 경로 자동 테스트는 fake engine을 사용합니다. 실제 YOLO/UniDepth GPU 결과가 통과했다고 의미하지 않습니다.
FastAPI/Starlette TestClient에서 httpx 관련 deprecation warning 1건이 있으나 테스트 실패는 없었습니다.

Frontend:

```text
npm ci --ignore-scripts
npm test       → 4 passed
npm run build  → success
npm audit     → 0 vulnerabilities
```

same-origin API, HTTP 오류 전달, ICE 수집 완료 대기, ICE timeout을 확인했습니다.
React 실제 브라우저 화면/영상 표시 FPS의 실기기 검증은 별도입니다.

Python src/scripts/tests 15개는 AST parsing을 통과했습니다.
`uv.lock` 및 `package-lock.json`을 생성했습니다. GPU extra 설치/실행은 수행하지 않았습니다.

## Android 검증 한계

`gradlew.bat --version`을 실행했지만 JDK가 없어 java.exe 실행에 실패했습니다.
Android Studio/Android SDK도 현재 환경에서 확인되지 않았습니다.
따라서 APK 빌드, Kotlin/JUnit 실행, 실제 스마트폰 촬영은 **미검증**입니다.
Gradle lockfile도 실제 dependency resolution 환경이 없어서 아직 생성하지 않았습니다.
SDK 준비 후 README의 첫 빌드 명령으로 생성해야 합니다.

공식 Gradle wrapper JAR만 다운로드했고 공식 SHA256과 일치했습니다.
wrapper 및 Gradle 배포본 checksum은 프로젝트에 기록/고정했습니다.
앱의 직접 의존성 버전은 고정했으며 wrapper 외에 SDK/JDK를 자동 설치하지 않았습니다.

## 운영 전 반드시 확인할 항목

1. Android 프로젝트 빌드 및 카메라 권한/백그라운드 즉시 종료.
2. 실제 LAN/VPN에서 ICE/UDP 연결, 한 폰 + 여러 브라우저 재생.
3. 실제 전송 프레임 기준 보정 K 등록 후 GPU 추론/거리/track overlay.
4. 30분 연속 실행: 입력/추론/표시 FPS, 수신→overlay latency, encode, RTT, CPU/RAM/VRAM/발열.
5. 실제 기존 runtime 결과와 동일 입력의 거리/추적 회귀 비교.

30FPS 달성 여부는 아직 판정할 수 없습니다. codec encode는 CPU/PyAV 경로이며 NVENC 적용을 주장하지 않습니다.
기존 runtime 내부의 통계 목록/track history는 장시간 증가할 수 있으므로 30분 전체 메모리 안정성은 미검증입니다.
모델·임계값·BoT-SORT/GMC/ReID·거리 계산·lifecycle 정책은 변경하지 않았습니다.
내부망 시험용이며 공개 서비스 인증/HTTPS/NAT 운영 설정은 별도 준비가 필요합니다.

현재 상태: **IMPLEMENTED_LOCAL_TESTS_PASSED / ANDROID_GPU_INTEGRATION_PENDING**.
