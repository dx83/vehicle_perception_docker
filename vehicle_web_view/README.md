# Vehicle Web View

스마트폰의 실시간 영상을 GPU 서버에서 추론하고 웹에서 보는 프로젝트입니다.
Android 앱은 형제 폴더 `vehicle_black_box`, 추론 코드는 기존 `vehicle_perception_runtime_fix`를 사용합니다.
기존 runtime을 수정하거나 새 프로젝트 안에 복사하지 않았습니다.

## 전체 흐름

HTTP/WebRTC 인터페이스는 [API 계약](docs/api.md)을 참조하세요.

Android 후면 카메라 → WebRTC → FastAPI 서버 → 최신 프레임 선택 → 기존 runtime의
`warmup()` / `process_stream()` → 해당 프레임에 mask·bbox·class·ID·raw distance 표시
→ WebRTC → React 화면.

WebSocket은 상태/계측만 전달합니다. 영상 프레임을 JSON이나 JPEG WebSocket으로 보내지 않습니다.
한 스마트폰과 기본 최대 4개 브라우저를 지원합니다. 처리되지 않은 오래된 입력과 느린 시청자의
오래된 출력은 건너뜁니다. 10FPS publish 제한은 없습니다. 실제 추론 FPS를 30FPS로 보장하지 않습니다.

## 서버에 둘 구조

서버의 임의 폴더 아래에 아래 상대 구조를 유지합니다. 모델과 runtime은 사용자가 직접 준비합니다.

```text
project/
├─ models/
│  ├─ yolo26m-seg.pt
│  └─ unidepth-v2-vitb14/
│     ├─ config.json
│     └─ model.safetensors
├─ vehicle_perception_runtime_fix/
└─ vehicle_web_view/
   ├─ backend/
   │  ├─ config.yaml
   │  ├─ runtime_config.yaml
   │  ├─ pyproject.toml
   │  ├─ uv.lock
   │  ├─ scripts/
   │  └─ src/vehicle_web/
   └─ frontend/
```

다른 배치를 사용할 때는 `backend/config.yaml`의 `runtime_root`, `runtime_config`,
`frontend_dist`와 `runtime_config.yaml`의 `paths.model_root`를 수정합니다.
모든 상대경로는 해당 설정 파일 위치 기준입니다. 실행하는 현재 디렉터리나 특정 서버 경로에 의존하지 않습니다.
`backend/runtime_config.yaml`은 스마트폰 전용의 새 설정입니다. 기존 runtime/config.yaml을 수정하지 않습니다.

## 1. 웹 빌드

Node.js 22.12 이상과 npm이 필요합니다. 서버에서 빌드하거나 로컬 빌드 결과 `frontend/dist`를 전달합니다.

```bash
cd vehicle_web_view/frontend
npm ci
npm test
npm run build
```

이후 FastAPI가 웹 빌드 결과를 함께 서비스합니다. 서버에서 Vite dev server를 띄울 필요가 없습니다.
개발용 `npm run dev`는 localhost에만 바인딩하며 `/api`를 localhost:8000으로 proxy합니다.

## 2. Python 환경

GPU 추론 배포 대상은 Linux + NVIDIA CUDA GPU입니다. `uv.lock`은 backend에서만 관리합니다.
프로젝트 전용 환경을 새로 만들며 기존 서버 .venv나 시스템 Python을 변경하지 않습니다.

```bash
cd vehicle_web_view/backend
uv sync --locked --extra gpu --no-dev
```

Python 3.12, 기존과 동일한 Torch 2.10.0 / Ultralytics 8.4.150 / UniDepth 소스 commit을 사용합니다.
UniDepth Python 패키지 설치에는 공식 Git 저장소 접근이 필요합니다. 모델은 다운로드하지 않습니다.
GPU extra에는 UniDepth가 선언한 전이 의존성도 포함됩니다. 설치 전 용량과 resolver 변경 내용을 확인하세요.
CUDA 드라이버와 `torch.compile`용 C 컴파일러는 시스템에 사용자가 별도로 준비해야 합니다.
설치 실패 시 다른 모델, CPU fallback, 자동 dependency downgrade를 적용하지 않습니다.

GPU 없이 서버/전송 자동 테스트만 실행하려면:

```bash
uv sync --locked
uv run --locked pytest -q -p no:cacheprovider
```

GPU extra를 설치한 환경의 이후 uv 실행에서는 `--extra gpu`를 유지하세요.
그 옵션 없이 `uv run`하면 uv가 GPU extra를 환경에서 제거할 수 있습니다.

## 3. 먼저 원본 영상으로 연결 확인

기본값은 `camera_profile.verified: false`, `camera.intrinsic: null`입니다.
이 상태에서도 영상 연결은 되지만 모델을 로드하지 않으며 거리/추적은 실행하지 않습니다.

서버 실행:

```bash
cd vehicle_web_view/backend
CUDA_VISIBLE_DEVICES=0 PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra gpu --no-dev python scripts/server/extract_run_server.py
```

물리 GPU 선택은 셸의 `CUDA_VISIBLE_DEVICES`로 합니다. runtime 내부는 logical `cuda:0`입니다.
서버 옵션은 `scripts/server/extract_run_server.py` 상단 `host`, `port`, `config_file`에서 수정합니다.
worker는 반드시 1개입니다. reload와 다중 worker는 사용하지 않습니다.

GPU 패키지 없는 원본 영상 연결 테스트는 같은 명령에서 `--extra gpu`만 빼도 됩니다.
단, `verified: false` 상태를 유지해야 합니다.

스마트폰 앱에서 `http://서버의LAN또는VPN주소:8000`을 입력하고 촬영 시작을 누릅니다.
노트북 브라우저에서도 동일한 주소를 엽니다. `/api/state`에 실제 device_id / camera_id가 표시됩니다.
스마트폰 앱은 별도 `vehicle_black_box` 프로젝트에서 빌드하여 폰에 설치합니다. Docker 배포 폴더에는 Android 프로젝트를 포함하지 않습니다.

## 4. 스마트폰 카메라 보정 후 추론 활성화

1. 실제 앱이 보내는 후면 카메라·가로 1280×720·줌 1배 영상으로 카메라 내부 행렬 K를 보정합니다.
2. `backend/runtime_config.yaml`의 `camera.intrinsic`에 3×3 행렬을 넣습니다.
3. `backend/config.yaml`의 `camera_profile.device_id` / `camera_id`를 실제 앱 값으로 입력합니다.
4. 해상도·방향·줌이 보정 조건과 같은지 확인하고 `verified: true`로 바꿉니다.
5. 서버를 재시작하고 앱에서 새 세션을 시작합니다.

K의 모양은 다음과 같습니다. 아래 기호는 숫자로 직접 입력해야 하며 임의 예제 숫자를 실제 보정값으로 쓰면 안 됩니다.

```text
[[fx, 0, cx], [0, fy, cy], [0, 0, 1]]
```

해상도 scaling, crop, rotation, 영상 안정화에 따른 좌표계까지 반영한 **전송 프레임 기준** K가 필요합니다.
Android CameraCharacteristics의 sensor 행렬이나 기존 nuScenes 행렬을 그대로 넣으면 안 됩니다.
폰/카메라/해상도/방향/줌이 달라지면 다시 보정 확인이 필요합니다.
metadata가 다른 세션은 원본 영상만 표시합니다. 실제 수신 크기가 보정값과 다르면 추론을 중단합니다.
자동 보정, 보정값 자동 업로드, 모델 학습 기능은 구현 범위에 포함하지 않습니다.

## 연결과 네트워크

- 기본 ICE 서버 목록은 빈 값입니다. 같은 LAN 또는 직접 통신 가능한 VPN 환경을 먼저 사용합니다.
- HTTP TCP 8000뿐 아니라 WebRTC ICE가 선택하는 UDP 경로도 양방향으로 연결되어야 합니다.
- **SSH로 TCP 8000만 포워딩해도 영상 UDP 경로가 열리는 것은 아닙니다.**
- 다른 NAT를 넘을 때는 운영자가 준비한 STUN/TURN을 `config.yaml`의 `ice_servers`에 등록합니다.
  서버가 `/api/rtc-config`로 동일한 설정을 앱과 웹에 제공합니다.
- 브라우저/앱 모두에서 접근 가능한 서버 주소를 사용합니다. 별도 컴퓨터의 localhost는 서버 주소가 아닙니다.
- 공개 인터넷 배포는 범위 밖입니다. 사용자 계정/로그인은 없으며 내부망에서 사용해야 합니다.
  외부 노출 전에 HTTPS, 접근 제어와 TURN 보안 설정을 따로 준비해야 합니다.

예시 ICE 항목 형식:

```yaml
ice_servers:
  - urls: ["turn:운영자가준비한주소:3478"]
    username: "운영자계정"
    credential: "운영자비밀번호"
```

해당 예시를 설정에 자동 적용하지 않으며, 비밀번호가 있는 설정을 Git에 올리지 마세요.

## 상태·계측 해석

- 입력 FPS: 서버가 실제 수신한 영상 프레임의 최근 FPS.
- 추론 FPS: 추론 후 overlay까지 처리한 결과의 최근 FPS. 원본 preview에서는 0입니다.
- 화면 FPS: 브라우저가 실제 표시한 프레임 callback 기준 FPS.
- 서버 수신→overlay: 수신 이후 대기·추론·mask packing·overlay 시간. 폰 전송/브라우저 지연은 제외합니다.
- `segmentation_ms`, `tracking_ms`, `depth_ms`, `fusion_ms`, `lifecycle_ms`: 기존 runtime 진단값.
  segmentation/depth가 겹쳐 실행되므로 이 숫자들의 합을 end-to-end latency로 해석하지 않습니다.
- `receive_conversion_ms`: 수신 decoded frame의 BGR 변환 시간. 네트워크 수신/codec decode 전체 시간이 아닙니다.
- `viewer_transport.encode_and_prepare_ms`: 시청자별 encode 및 준비 시간, 다음 프레임을 기다리는 시간 제외.
  aiortc 1.15.0의 제한된 내부 hook을 별도 모듈에 격리했고 버전을 고정했습니다. library 업그레이드 시 재검증해야 합니다.
- `packets_sent` / `bytes_sent` / `round_trip_ms`: 서버 RTP 통계. RTT는 일방향 영상 전송 지연이 아닙니다.
- 브라우저 decode ms는 수신 WebRTC 통계의 누적 평균입니다.
- warmup 프레임은 추론 결과에 포함하지 않고 별도 수치로 표시합니다.

영상/CSV/JSON/이미지/업무 로그 파일은 생성하지 않습니다. 상태와 계측은 메모리에만 있습니다.
추론 결과 `InferenceResult`는 `Session`의 adapter에서 그대로 받아 처리하므로 이후 FastAPI/DB 등 연계도 가능하며,
기존 runtime에 저장 기능을 추가하지 않았습니다.

## 종료와 재연결

앱 종료/백그라운드에서 카메라를 멈추고 서버 세션 종료를 요청합니다. 네트워크 단절은 기본 20초 idle timeout으로 정리합니다.
다시 연결하면 새 session_id를 사용하고 `process_stream()`이 tracking/lifecycle을 초기화합니다.
추론 모델은 같은 서버 프로세스에서 재사용합니다. 이전 GPU 작업이 끝나기 전 새 세션을 동시에 시작하지 않습니다.
브라우저의 영상 연결만 끊겼다면 '영상 다시 연결' 버튼을 사용합니다.

## 검증 상태와 남은 실기기 검증

자동 테스트와 제약은 [검증 기록](docs/validation.md)에 기록했습니다.
실제 Android APK 빌드/스마트폰 촬영, GPU 거리 회귀, 30분 실기기 연속 실행은 별도 검증이 필요합니다.
기존 runtime 내부의 스트림 통계 목록과 track history는 장시간 증가할 수 있으므로 전체 시스템의
30분 메모리 안정성을 아직 보장하지 않습니다. 기존 runtime을 변경하지 않는 조건으로 그대로 두었습니다.

참고 구현 계약: [aiortc API](https://aiortc.readthedocs.io/en/latest/api.html),
[WebRTC ICE 연결](https://webrtc.org/getting-started/peer-connections).
