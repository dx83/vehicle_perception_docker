# API 계약

FastAPI `/docs`에서 요청/응답을 확인할 수 있습니다. 아래 API는 내부망 시험용이며 사용자 계정 인증은 없습니다.
`X-Session-Token`은 해당 스마트폰의 signaling/종료 권한만 제한합니다.

| Method / 경로 | 역할 |
| --- | --- |
| GET `/api/health` | 서버 생존 상태, recording=false |
| GET `/api/state` | 현재 세션과 계측; 없으면 NO_CAMERA |
| GET `/api/rtc-config` | 앱/웹 공통 iceServers |
| POST `/api/sessions` | 스마트폰 세션 생성; session_id/token 반환 |
| GET `/api/sessions/{id}` | 세션 상태 |
| DELETE `/api/sessions/{id}` | token을 검증하고 세션 종료 |
| POST `/api/sessions/{id}/phone/offer` | 스마트폰 SDP offer→answer; token 필수 |
| POST `/api/sessions/{id}/viewer/offer` | 시청자 SDP offer→answer |
| WebSocket `/api/metrics` | 초당 상태/계측 JSON; 영상 데이터는 전달하지 않음 |

세션 생성 요청:

```json
{"device_id":"실제ANDROID_ID","camera_id":"실제후면카메라ID","width":1280,"height":720,"orientation":"landscape","zoom":1.0}
```

offer 요청은 `{"type":"offer","sdp":"..."}` 형식이며 ICE gathering 완료 후 전송합니다.
응답은 `{"type":"answer","sdp":"..."}`입니다. trickle ICE는 사용하지 않습니다.
두 번째 스마트폰이나 시청자 제한 초과는 HTTP 409, 세션 미존재는 404, 잘못된 token은 403입니다.

영상 전송은 WebRTC이며 한 스마트폰에 video track 하나를 사용합니다. 새 세션은 tracking 상태를 초기화합니다.
입력 및 출력에는 각각 최신 프레임 정책을 적용하지만 기존 runtime에 이미 들어간 프레임은 FIFO 순서로 처리합니다.
따라서 처리량 초과 시 입력 영상을 모든 프레임 추론하지 않습니다. 기존 알고리즘/임계값은 변경하지 않습니다.

`InferenceResult.frame_id`는 **추론에 투입된 프레임**의 순번입니다.
`last_source_index`는 수신 원본 프레임의 순번이며 건너뜀 때문에 두 값이 달라질 수 있습니다.
본 adapter는 bounded sidecar로 두 순번을 연결하여 overlay가 다른 영상에 적용되지 않게 합니다.
추론 결과 timestamp는 기존 runtime의 ingest 시각입니다. 스마트폰 capture timestamp로 가장하지 않습니다.

세션 오류는 상태의 `error`에 원래 예외 종류/메시지로 표시하며 임의 fallback을 수행하지 않습니다.
코어 결과에 대한 파일 저장/DB 적재는 이 구현에 포함하지 않습니다.
