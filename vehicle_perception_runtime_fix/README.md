# Vehicle Perception Runtime

Stage28에서 검증한 N2 production 경로만 추출한 독립 추론 패키지입니다. 렌더링,
AVI/CSV/JSON 저장, FastAPI, React, benchmark 및 Stage output 의존성이 없습니다.

## 구성

- YOLO26m-seg, confidence 0.25
- ReID-OFF BoT-SORT, shared sparseOptFlow GMC
- UniDepth V2 로컬 모델, YAML의 resolution level, `torch.compile(mode="default")`
- positive finite instance-mask exact median
- Stage21 one-frame lifecycle policy

YOLO instance mask는 torch bool tensor로 유지하며, CUDA 실행 시 마스크 resize,
면적 계산과 mask-depth median을 GPU에서 수행합니다. 거리 결과의 작은 scalar만
CPU로 전달합니다. `return_masks=True`를 요청한 경우에만 public mask의 최소 ROI를
CPU로 복사해 기존 packed bytes 형식으로 반환합니다. 직접 segmentation component를
주입하는 호출자를 위해 NumPy mask 입력도 계속 지원합니다.

## 설치와 모델

Python 3.12 및 CUDA용 PyTorch 환경에서 `uv sync`를 사용합니다. 런타임은 모델을
다운로드하지 않습니다. `config.yaml`의 `paths.model_root`가 가리키는 외부 폴더에
다음 파일을 준비해야 합니다.

```text
external_model_root/
├─ yolo26m-seg.pt
└─ unidepth-v2-vitb14/
   ├─ config.json
   └─ model.safetensors
```

`CUDA_VISIBLE_DEVICES`는 호출 프로세스가 관리합니다. YAML의 `gpu_id`는 노출된 GPU
목록 안의 논리 번호입니다. 모델 경로와 runtime 경로는 YAML 위치 기준 상대경로 또는
절대경로로 해석됩니다.

`models.depth`에서 사용할 UniDepth V2 모델 디렉터리를 선택하고,
`inference.resolution_level`에서 추론 해상도 수준(0~9 정수)을 설정합니다.
기본값은 3입니다. 설정은 `config.py`에서 검증한 `RuntimeConfig`를 통해
depth backend에 전달합니다. 모델 ID, 모델 revision, 설치 소스 revision 및
provenance 파일을 검사하지 않습니다. 선택한 모델은 설치된 UniDepth V2와
호환되는 `config.json`과 `model.safetensors`를 포함해야 합니다.

## 사용

```python
from vehicle_perception_runtime import PerceptionEngine

engine = PerceptionEngine("vehicle_perception_runtime/config.yaml")
try:
    result = engine.process(frame)
    for obj in result.objects:
        print(obj.track_id, obj.class_name, obj.distance_m, obj.distance_zone)
finally:
    engine.close()
```

연속 프레임은 bounded production streaming 경로로 처리합니다. 입력과 출력 순서는
동일하며 queue와 in-flight frame은 각각 3개로 제한됩니다.

```python
for result in engine.process_stream(frame_source):
    consume(result)
```

`process_stream()`을 다시 호출하면 segmentation/depth 모델은 재사용하고 tracker,
lifecycle 및 frame index만 새 stream 상태로 초기화합니다.

입력은 non-empty `uint8` OpenCV BGR `H x W x 3` 배열입니다. 한 엔진 인스턴스의
`process()`는 프레임 0부터 순차 호출해야 하며 thread-safe/reentrant하지 않습니다.
결과는 메모리 dataclass만 반환하고 source/config/static 파일이나 runtime output을
생성하지 않습니다. 기본 `artifacts.enabled`는 `false`이며 core에서는 다른 값을
거부합니다. `runtime_root`는 외부 애플리케이션 또는 별도 optional writer를 위한 예약
경로이고 이 core는 그 경로에도 파일을 쓰지 않습니다. FastAPI/DB/WebSocket 연동은
`InferenceResult`를 직접 받아 core 외부에서 처리합니다.

Mask 시각화가 필요한 consumer만 `PerceptionEngine(config_path, return_masks=True)`를
사용합니다. 기본값은 `False`이며 기존 객체 결과의 `mask`는 `None`입니다. 활성화하면
이미 추론된 YOLO binary mask에서 객체별 최소 ROI를 추출하고, 원본 프레임 좌표의
`MaskGeometry(x, y, width, height, packed_bits)`를 반환합니다. `packed_bits`는
row-major, bitorder=`big`인 immutable bytes입니다. 빈 mask는 `None`입니다.
`process()`와 `process_stream()`에서 같은 계약을 사용하며 거리·추적 계산은 바뀌지
않습니다. Mask 표시 옵션은 원본 frame-size NumPy mask를 public 결과에 그대로
중복 보관하지 않습니다.

## 의존성 추적

production import graph는 `engine → segmentation/tracking/depth/distance/lifecycle → result`
로 제한됩니다. `cp-model`, Stage 스크립트, Stage outputs, nuScenes, renderer, 웹/UI 및
원격 배포 모듈을 import하지 않습니다. mask는 거리 계산 내부에서만 사용되며 public
result에는 포함되지 않습니다.
