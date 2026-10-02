# Vehicle Perception Docker

**이 폴더 전체를 Ubuntu GPU 서버에 업로드한 뒤, 이 폴더에서 `docker compose up`을 실행합니다.**
웹·추론 runtime·모델을 포함하며 `cp-model`이나 서버의 다른 프로젝트 폴더가 필요하지 않습니다.
Android 앱은 폰에 별도로 설치해야 합니다. 서버에는 Android 프로젝트를 올릴 필요가 없습니다.

## 포함 구조

```text
vehicle_perception_docker/
├─ compose.yaml / Dockerfile / .dockerignore / .env
├─ manifest.json
├─ vehicle_web_view/                 # React + FastAPI
├─ vehicle_perception_runtime_fix/   # 기존 runtime 사본, 원본과 동일
├─ models/
│  ├─ yolo26m-seg.pt
│  └─ unidepth-v2-vitb14/
│     ├─ config.json
│     └─ model.safetensors
├─ scripts/deployment/extract_verify_bundle.py
└─ docs/validation.md
```

모델은 3개 파일, 총 **512,480,016 bytes (약 489MiB)**입니다.
모델과 runtime은 컨테이너에 읽기 전용으로 마운트하며 이미지에는 복사하지 않습니다.
호스트 `.venv`, `node_modules`, 캐시, 예전 outputs, 영상 데이터는 포함하지 않습니다.

## 1. 서버에 미리 필요한 것

- Linux x86_64 Ubuntu GPU 서버(컨테이너 내부 Ubuntu 24.04).
- NVIDIA GPU 드라이버와 CUDA 12.8 계열 Torch wheel을 실행할 수 있는 호환성.
- Docker Engine, `docker compose` 플러그인, NVIDIA Container Toolkit.
- 최초 이미지 빌드에 사용할 인터넷 연결, 충분한 디스크 공간.
- 서버↔스마트폰/노트북 사이의 HTTP TCP와 WebRTC UDP 연결.

서버의 기존 Python/uv/Node 환경은 사용하지 않습니다. 컨테이너 안에 필요한 패키지를 설치합니다.
GPU 드라이버와 Container Toolkit은 호스트에 준비되어야 합니다. 자동 설치하거나 Docker daemon을 변경하지 않습니다.

사용자가 서버에서 확인:

```bash
nvidia-smi
docker --version
docker compose version
```

NVIDIA 설정은 [공식 Container Toolkit 안내](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)를 확인하세요.
서버 관리자와 조율 없이 공유 서버의 Docker daemon을 재시작하지 마세요.

## 2. 포트와 GPU 선택

업로드한 폴더의 `.env`:

```dotenv
HTTP_PORT=18000
GPU_DEVICE_ID=0
```

- 포트가 점유되어 있으면 `18001`, `19000` 등 비어 있는 포트로 바꿉니다.
- 물리 GPU 1을 사용하려면 `GPU_DEVICE_ID=1`로 바꿉니다.
- 컨테이너에 GPU 하나만 노출하며 프로그램 내부는 계속 logical `cuda:0`입니다.
- 자동 GPU 선택, GPU fallback, CPU fallback은 없습니다.
- 포트는 비루트 실행을 위해 `1024~65535`만 허용합니다. 잘못된 값은 실패합니다.
- 셸에 동일한 환경변수가 이미 설정되어 있으면 Compose가 `.env`보다 셸 값을 우선하므로 `docker compose config`로 확인합니다.

공유 서버에서 사용 전 확인(아래 숫자는 실제 선택에 맞게 바꿉니다):

```bash
ss -ltn | grep ':18000 '
nvidia-smi -i 0
docker compose config
```

`ss` 출력이 없으면 해당 TCP 포트에 listener가 없는 것입니다. GPU가 다른 작업으로 점유 중이면 강행하지 마세요.
앱, 웹, API, WebSocket은 HTTP 포트 하나를 공유합니다. 여러 TCP 포트를 추가로 열 필요는 없습니다.
단, 영상은 **WebRTC의 별도 UDP 포트**를 사용하므로 TCP 포트 확인만으로 영상 연결을 보장하지 않습니다.

## 3. 실행

```bash
cd vehicle_perception_docker
docker compose up
```

최초 실행은 이미지를 빌드합니다. Python 3.12, 컴파일러, uv, GPU Python 의존성과 React 빌드가 포함됩니다.
패키지 다운로드와 이미지 빌드에 시간이 걸릴 수 있습니다. **모델은 다운로드하지 않습니다.**
GPU 추가 패키지 설치는 컨테이너 안에서만 수행하며 서버의 기존 .venv나 시스템 Python을 건드리지 않습니다.

백그라운드 실행:

```bash
docker compose up -d
docker compose ps
docker compose logs -f perception
```

브라우저/스마트폰에서:

```text
http://서버의LAN또는VPN주소:18000
```

`.env`에서 포트를 바꿨다면 변경한 포트를 사용합니다. 서버와 별도인 노트북/폰에서 `127.0.0.1`을 입력하면 안 됩니다.

확인/종료:

```bash
curl http://127.0.0.1:18000/api/health
curl http://127.0.0.1:18000/api/state
docker compose down
```

코드 변경 후 이미지 갱신:

```bash
docker compose up --build
```

`.env` 변경 후에도 `docker compose up`으로 컨테이너를 다시 생성하여 적용합니다.
카메라 설정 파일만 변경했다면 `docker compose restart perception` 후 앱에서 새 세션을 시작합니다.
이 설정 파일들은 읽기 전용 bind mount라 이미지를 다시 빌드할 필요는 없습니다.
첫 실행이 된다고 해서 30FPS나 거리 정확도가 검증된 것은 아닙니다.

## 4. 기본값은 원본 preview — 카메라 보정 필요

기본 `vehicle_web_view/backend/config.yaml`은 `camera_profile.verified: false`입니다.
이 상태에서는 원본 영상 연결만 수행하고 YOLO/Depth 모델을 로드하지 않습니다.
컨테이너를 실행한 뒤 Android 앱에서 같은 서버 주소로 연결하면 웹에서 원본 영상을 볼 수 있습니다.

실제 거리/추적/mask 표시 활성화:

1. 실제 스마트폰의 앱 전송 영상(후면, 가로 1280×720, 줌 1배) 기준 K를 보정합니다.
2. `vehicle_web_view/backend/runtime_config.yaml`의 `camera.intrinsic`에 그 K를 입력합니다.
3. `vehicle_web_view/backend/config.yaml`에 실제 `device_id`, `camera_id`를 입력합니다. `/api/state`에서 확인 가능합니다.
4. 조건을 확인한 뒤 `verified: true`로 바꿉니다.
5. 컨테이너를 재시작하고 앱에서 새 세션을 시작합니다.

K의 형태:

```text
[[fx, 0, cx], [0, fy, cy], [0, 0, 1]]
```

기호 대신 **실제 보정 숫자**가 필요합니다. 기존 nuScenes의 행렬을 그대로 적용하면 안 됩니다.
사본 runtime 안에 있는 예전 config.yaml은 Docker 실행에서 사용하지 않습니다.
실제 실행 설정은 웹 backend의 `runtime_config.yaml`입니다.
촬영 metadata 또는 실제 크기가 보정 조건과 다르면 추론을 시작하지 않거나 중단합니다.

## 5. 네트워크·권한·캐시

- Ubuntu Host network 사용: `ports:` mapping을 두지 않으며 설정 포트를 호스트에서 직접 사용합니다.
- 다른 사용자의 애플리케이션이 같은 HTTP 포트를 사용하면 실패합니다. 자동으로 다른 포트로 바꾸지 않습니다.
- HTTP 연결은 되지만 영상이 안 나오면 ICE/UDP 경로를 확인합니다. SSH TCP 포워딩만으로는 충분하지 않습니다.
- STUN/TURN이 필요하면 운영자가 준비한 값을 backend/config.yaml의 `ice_servers`에 넣습니다.
- 내부망/VPN 시험용입니다. 공개 인터넷 사용에는 HTTPS·인증·접근 제어가 별도로 필요합니다.
- 컨테이너 UID/GID는 `10001:10001`입니다. 업로드된 파일을 해당 사용자가 읽을 수 있어야 합니다.
  permission denied라면 이 폴더 안의 runtime/models/config 읽기 권한을 확인하세요.
- 루트 파일시스템과 원본 runtime/models/config는 읽기 전용입니다.
- `/tmp`만 임시 메모리 저장소로 사용합니다(최대 4GiB). Torch/Triton 컴파일 캐시와 라이브러리 설정 캐시는 여기에 둡니다.
  컨테이너 재시작 시 사라지므로 다시 warmup/compile할 수 있습니다. 영상·CSV·업무 JSON 저장이 아닙니다.
- healthcheck의 `healthy`는 HTTP 서비스 생존 상태입니다. GPU 추론 성공/30FPS/카메라 보정 통과를 의미하지 않습니다.

## 6. 업로드 무결성 검사

서버에 Python 3.11 이상이 있으면 Docker를 실행하기 전 다음을 수행할 수 있습니다(표준 라이브러리만 사용):

```bash
python3 scripts/deployment/extract_verify_bundle.py
```

manifest.json에 기록된 파일 목록, 용량, SHA256을 대조합니다.
서버에서 `.env`나 카메라 설정을 수정한 뒤에는 그 파일의 checksum 불일치가 **정상적인 변경 결과**입니다.
manifest를 자동으로 덮어쓰거나 변조를 무시하지 않습니다. 사용자 변경 전 업로드 상태를 먼저 검증하세요.

서버 준비가 끝나 있다면 **이 폴더만 업로드하여 `docker compose up`으로 실행**하는 구조입니다.
현재 로컬 Docker daemon이 실행되지 않아 이미지 빌드와 실제 Ubuntu GPU 실행은 아직 검증하지 못했습니다.
상세 검증은 [검증 기록](docs/validation.md)을 참조하세요.
