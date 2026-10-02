# Docker 배포 폴더 검증

검증일: 2026-10-01.
상태: **BUNDLE_PREPARED_LOCAL_TESTS_PASSED / DOCKER_GPU_EXECUTION_UNVERIFIED**.

## 원본 보존 및 포함 범위

- 새 `vehicle_perception_docker` 폴더에 웹/runtime의 코드·설정·문서·테스트를 선별 복사했습니다.
- 모델은 yolo26m-seg.pt, UniDepth config.json/model.safetensors만 포함했습니다.
  합계 512,480,016 bytes입니다. 기존 provenance 파일과 전체 models 폴더는 복사하지 않았습니다.
- 기존 runtime 13개, AGENTS.md 1개, 모델 3개 등 보호 파일 17개의 작업 전후 SHA256이 모두 같습니다.
- 기존 `vehicle_web_view`의 소스도 수정하지 않았습니다. 포트 설정 변경은 배포 사본에만 적용했습니다.
- manifest에는 새 배포 폴더의 상대경로, 크기, SHA256, 원본 복사 여부를 기록합니다.
  배포 폴더 자체가 없던 상태에서 생성했으므로 포함 파일의 배포 분류는 NEW입니다.
- 사용자가 요청한 self-contained 폴더 방식이며 서버 증분 압축을 생성한 것이 아닙니다. 별도 .7z/.zip은 만들지 않았습니다.

## 확인한 검증

| 검증 | 결과 |
| --- | --- |
| 배포 사본 backend 테스트 | 40 passed |
| 기존 원본 backend 회귀 테스트 | 21 passed |
| 배포 사본 frontend 테스트 | 4 passed |
| 배포 사본 React/Vite build | 성공 |
| 배포 사본 uv.lock offline check | 성공, 145 packages |
| 배포 사본 backend Python AST | 18개 parsing 성공 |
| docker compose config --quiet | 성공 |
| HTTP_PORT=18123 / GPU_DEVICE_ID=1 환경변수 변경 | Compose 반영 확인 |
| 모델·runtime·설정 mount | 모두 읽기 전용, create_host_path=false |
| Docker build context의 모델/runtime/캐시 제외 | 설정/테스트 확인 |

테스트는 원본의 기존 가상환경을 **실행에만 재사용**했고 설치/갱신하지 않았습니다.
Python 테스트에는 FastAPI/Starlette의 TestClient httpx deprecation warning 1건이 있습니다.
웹 검증에 생성된 배포 폴더의 node_modules/dist는 검증 후 제거했습니다. Docker 빌드가 다시 생성합니다.
모델을 제외한 코드 테스트이며 실제 GPU 거리 추론 성공을 주장하지 않습니다.

## 신규 테스트 내용

- 포트 변경, 비루트 포트 범위 제한, 비정상 값 거부.
- 실제 실행 스크립트와 healthcheck가 같은 환경변수 포트를 사용함.
- 단일 GPU reservation / logical cuda:0 / Host network.
- 배포 폴더 내부에서 runtime/models가 해석되고 보정 기본값이 비활성임.
- 원본/모델을 이미지 레이어에 COPY하지 않고 uv/npm lock 기반으로 빌드함.
- manifest의 내용 변경/파일 누락 감지, 기존 manifest 자동 덮어쓰기 차단.
- 기존 WebRTC 왕복/프레임 pairing/최신 프레임/세션 종료 테스트도 재실행.

## 실제 Docker 실행 미검증

Docker Compose CLI는 사용 가능하지만 로컬 Docker daemon pipe가 존재하지 않아 연결에 실패했습니다.
Docker 사용자 config.json 접근 경고도 있습니다. 이 상태에서 Docker를 자동 실행하거나 사용자 설정을 수정하지 않았습니다.

따라서 아래는 아직 수행하지 못했습니다.

1. Linux 이미지 전체 빌드 및 GPU extra 패키지의 실제 이미지 설치.
2. NVIDIA Container Toolkit을 통한 실제 컨테이너 GPU 노출.
3. 읽기 전용 컨테이너에서 Torch/Triton CUDA 컴파일 및 추론.
4. 실제 Ubuntu 서버↔Android↔브라우저 WebRTC 연결.
5. 실제 스마트폰 K 등록 후 거리/추적 회귀, 30분 연속 실행, FPS/VRAM 측정.

Dockerfile의 Node builder는 공식 Node 이미지 목록에 있는 22.23.3-bookworm-slim을 고정했습니다.
로컬 npm 검증은 설치된 Node 22.23.1로 수행했습니다.
실제 이미지 빌드에는 이미지 registry/PyPI/npm/GitHub 연결과 충분한 디스크가 필요합니다.
실패 시 모델·임계값·GPU fallback·dependency downgrade를 자동 적용하지 않습니다.

서버 업로드·Docker 실행·드라이버/Container Toolkit 준비는 사용자가 수동 수행해야 합니다.

참고: [Docker GPU reservation](https://docs.docker.com/compose/how-tos/gpu-support/),
[Host network](https://docs.docker.com/engine/network/drivers/host/),
[Node 공식 이미지 목록](https://github.com/docker-library/official-images/blob/master/library/node).
