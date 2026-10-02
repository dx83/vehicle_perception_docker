# 웹 영상 화질 설정

720p 촬영, 추론 및 모델 설정은 그대로 유지합니다. 스마트폰 앱은 변경하지 않습니다.
서버에서 브라우저로 보내는 WebRTC VP8/H.264 인코더 정책을 다음으로 설정합니다.

```yaml
# vehicle_web_view/backend/config.yaml
viewer_bitrate_bps:
  min: 250000
  start: 4000000
  max: 8000000
```

단위는 bps입니다. 시작 4 Mbps, 최대 8 Mbps이며 네트워크 혼잡 피드백에 따라
250 kbps까지 낮아질 수 있습니다. 일정 비트레이트나 실제 화질을 보장하지 않습니다.
스마트폰에서 서버로 들어오는 영상이 이미 압축된 경우 이 설정으로 복원할 수 없습니다.

aiortc 1.15.0은 공개 인코더 비트레이트 설정 API가 없어, 버전을 검사하고
프로세스의 VP8/H.264 codec module 정책을 서버 초기화 시 설정합니다.
설치 패키지 파일을 수정하지 않으며, 프로세스 하나에서 하나의 정책을 사용합니다.
수신 디코더 설정 및 추론 로직은 변경하지 않습니다.

웹에 수신 해상도와 수신 비트레이트를 표시합니다. 비트레이트는 1초 간격
inbound-rtp bytesReceived 차이로 계산한 수신량이며 설정값이나 전체 통신량이 아닙니다.
첫 샘플 및 지원하지 않는 브라우저 통계는 '-'로 표시합니다.

## 기존 서버에 수동 적용

다음 8개 NEW/MODIFIED 파일만 동일 상대 경로로 업로드하세요.

- vehicle_web_view/backend/config.yaml (MODIFIED)
- vehicle_web_view/backend/src/vehicle_web/common/engine_paths.py (MODIFIED)
- vehicle_web_view/backend/src/vehicle_web/api/engine_app.py (MODIFIED)
- vehicle_web_view/backend/src/vehicle_web/streaming/engine_video_quality.py (NEW)
- vehicle_web_view/backend/tests/test_video_quality.py (NEW)
- vehicle_web_view/frontend/src/main.jsx (MODIFIED)
- vehicle_web_view/frontend/src/engine_connection.js (MODIFIED)
- vehicle_web_view/frontend/src/engine_connection.test.js (MODIFIED)

추가로 manifest.json과 이 문서를 반영하면 배포 폴더 checksum 검증도 가능합니다.
모델, 영상, runtime, dependency 파일과 Dockerfile은 재업로드할 필요가 없습니다.
서버 config.yaml에서 이미 카메라 보정/ICE 설정 등을 변경했다면 파일 전체를 덮어쓰지 말고
viewer_bitrate_bps 항목만 추가하세요. 사용자 설정을 변경한 경우 로컬 배포 manifest와
checksum이 다른 것은 정상이며, 서버 설정을 checksum에 맞추려고 되돌리지 마세요.

서버의 배포 루트에서 실행하세요 (기존 shell 포트 override 사용 시 동일하게 유지).

```bash
docker compose up --build
```

웹에서 강력 새로고침 후 앱 촬영을 다시 연결하세요. 촬영을 계속하면서 웹의
수신 해상도가 1280x720인지, 수신 비트레이트와 영상 선명도가 개선되는지 확인하세요.
UDP/ICE 경로 문제는 이 설정과 별개입니다.

## 로컬 검증

- 원본 웹 백엔드 26개 테스트 통과
- Docker 배포 웹 백엔드 45개 테스트 통과
- 프런트엔드 5개 테스트 및 Vite production build 통과
- 비트레이트 상한 및 혼잡 시 하향 조절, 잘못된 config 검증 포함
- 실제 스마트폰/Tailscale/서버 영상 화질은 로컬에서 검증하지 못함
- SSH 접속, 서버 설치 및 배포 수행하지 않음
