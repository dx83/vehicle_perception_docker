# 스마트폰 송신 화질 및 입력 해상도 검증

## 변경 사항

앱의 VideoQualitySettings.kt에서 촬영 1280x720 / 최대 30 FPS,
송신 최소 0.5 Mbps / 시작 4 Mbps / 최대 8 Mbps를 설정합니다.
VideoSource.adaptOutputFormat 및 송신 encoding scaleResolutionDownBy=1.0을 적용하고,
협상 완료 후 MAINTAIN_RESOLUTION으로 해상도 우선 정책을 적용합니다.
대역폭 제한 시 FPS를 낮추도록 선호하지만, 실제 720p나 일정 비트레이트를 보장하지 않습니다.
하드웨어 인코더/카메라 제약 또는 네트워크 손실로 화질이 떨어질 수 있습니다.
setBitrate/setParameters가 거절되면 명확한 오류로 표시하고 기존 앱 실패 처리로 종료합니다.
서버 해상도 검사 및 카메라 calibration 기준은 변경하지 않습니다.

웹의 서버 입력 해상도는 앱이 요청한 해상도가 아니라 서버에서 디코딩한 frame.shape입니다.
따라서 기존 '수신 해상도'(브라우저 디코더)와 함께 손실 구간을 구분할 수 있습니다.
송신 policy 값은 실제 전송량이 아닙니다. 실제 웹 수신 bitrate는 별도 계측값입니다.

## 사용자 수동 적용

1. Android Studio에서 vehicle_black_box 프로젝트를 다시 Run하여 앱을 재설치합니다.
   웹 서버만 업데이트하면 앱 송신 설정은 바뀌지 않습니다.
2. 서버에는 아래 변경 파일만 동일 상대 경로에 적용합니다.
   - vehicle_web_view/backend/src/vehicle_web/runtime/engine_session.py (MODIFIED)
   - vehicle_web_view/frontend/src/main.jsx (MODIFIED)
   - vehicle_web_view/backend/tests/test_received_geometry.py (NEW, 검증용)
   - docs/phone_video_quality.md (NEW)
   - manifest.json (MODIFIED, 사용자 서버 config 수정 시 checksum 차이는 예상됨)
3. 서버의 vehicle_perception_docker 루트에서 docker compose up --build를 실행합니다.
   기존 HTTP_PORT override가 있다면 동일하게 사용합니다. 모델/runtime 재업로드는 불필요합니다.
4. 웹 강력 새로고침 후 촬영을 다시 시작합니다.

## 판독 방법

- 서버 입력 1280x720 / 웹 수신 1280x720: 두 전송 구간의 해상도 정상
- 서버 입력 320x180 / 웹 수신 320x180: 앱/카메라/스마트폰 송신 구간 점검
- 서버 입력 1280x720 / 웹 수신 320x180: 서버 출력/웹 협상 구간 점검
- 둘 다 720p인데 흐림: 조명/초점/양쪽 압축 및 실제 bitrate/패킷 손실 점검

실제 스마트폰/Tailscale 화질은 이 작업 환경에서 검증하지 못합니다.
추론 모델·보정·tracking·lifecycle 및 카메라 프로필은 변경하지 않았습니다.
HTTP/ICE 설정이나 새 패키지/모델도 추가하지 않았습니다.

## 근거 API

- https://webrtc.googlesource.com/src/+/refs/heads/main/sdk/android/api/org/webrtc/RtpParameters.java
- https://webrtc.googlesource.com/src/+/refs/heads/main/sdk/android/api/org/webrtc/PeerConnection.java

의존성 버전은 기존 io.github.webrtc-sdk:android:150.7871.01을 유지합니다.

## 로컬 검증 결과

- 기존 JDK 17 / Gradle 캐시로 Android 단위 테스트 및 debug APK 빌드 성공 (offline)
- 원본 웹 backend 27개 / Docker backend 46개 테스트 통과
- frontend 5개 테스트 및 production build 통과
- 서버 입력 계측은 실제 320x180 및 1280x720 프레임으로 검증
- 스마트폰의 네이티브 setParameters 및 실제 Tailscale 송신은 재설치 후 사용자 확인 필요
