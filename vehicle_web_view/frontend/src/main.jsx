import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { api, connectViewer, videoQualityStats } from './engine_connection.js';
import './style.css';

const format = value => Number.isFinite(value) ? value.toFixed(1) : '-';

function App() {
  const video = useRef(null);
  const [status, setStatus] = useState({ state: 'CONNECTING' });
  const [connection, setConnection] = useState('waiting');
  const [error, setError] = useState('');
  const [displayFps, setDisplayFps] = useState(0);
  const [retry, setRetry] = useState(0);
  const [transportStats, setTransportStats] = useState({});
  useEffect(() => {
    let stopped = false, timer, socket;
    function open() {
      socket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/api/metrics`);
      socket.onmessage = event => { if (!stopped) setStatus(JSON.parse(event.data)); };
      socket.onclose = () => { if (!stopped) timer = setTimeout(open, 1500); };
      socket.onerror = () => socket.close();
    }
    api('/api/state').then(setStatus).catch(e => setError(e.message));
    open();
    return () => { stopped = true; clearTimeout(timer); socket?.close(); };
  }, []);
  useEffect(() => {
    if (!status.session_id) { video.current.srcObject = null; setConnection('waiting'); return; }
    let cancelled = false, peer, interval, previous;
    setError(''); setConnection('connecting');
    connectViewer(status.session_id,
      stream => { if (!cancelled) video.current.srcObject = stream; },
      state => { if (!cancelled) setConnection(state); },
    ).then(value => {
      if (cancelled) { value.close(); return; }
      peer = value;
      interval = setInterval(async () => {
        if (cancelled || peer.connectionState === 'closed') return;
        let stats;
        try { stats = await peer.getStats(); }
        catch (error) { if (!cancelled) setError(error.message); return; }
        for (const row of stats.values()) {
          if (row.type === 'inbound-rtp' && row.kind === 'video') {
            const decodeMs = row.framesDecoded ? row.totalDecodeTime * 1000 / row.framesDecoded : 0;
            const networkFps = previous ? (row.framesDecoded - previous.frames) * 1000 / (row.timestamp - previous.time) : 0;
            const quality = videoQualityStats(row, previous);
            previous = { frames: row.framesDecoded, time: row.timestamp, bytes: row.bytesReceived };
            if (!cancelled) setTransportStats({ decodeMs, networkFps, packetsLost: row.packetsLost, ...quality });
          }
        }
      }, 1000);
    }).catch(e => { if (!cancelled) { setError(e.message); setConnection('failed'); } });
    return () => { cancelled = true; clearInterval(interval); peer?.close(); video.current.srcObject = null; };
  }, [status.session_id, retry]);
  useEffect(() => {
    const element = video.current;
    let id, last, count = 0;
    const tick = now => {
      count++;
      if (last === undefined) last = now;
      if (now - last >= 1000) { setDisplayFps(count * 1000 / (now - last)); count = 0; last = now; }
      id = element.requestVideoFrameCallback(tick);
    };
    if (element.requestVideoFrameCallback) id = element.requestVideoFrameCallback(tick);
    const timer = setInterval(() => { if (last !== undefined && performance.now() - last > 2500) setDisplayFps(0); }, 1000);
    return () => { clearInterval(timer); if (id !== undefined) element.cancelVideoFrameCallback(id); };
  }, []);
  return <main>
    <header><div><small>LIVE PERCEPTION</small><h1>Vehicle Live</h1></div><span className="badge">{status.state} · {connection}</span></header>
    <video ref={video} autoPlay playsInline muted />
    {status.state === 'CALIBRATION_REQUIRED' && <p className="notice">카메라 보정 미확인: 원본 영상만 표시합니다. 거리 추론은 시작하지 않습니다.</p>}
    {status.state === 'NO_CAMERA' && <p className="notice">스마트폰 앱에서 연결을 시작하세요.</p>}
    {(error || status.error) && <p className="error">{error || status.error}</p>}
    <section className="metrics">
      <article>입력 FPS<strong>{format(status.input_fps)}</strong></article>
      <article>추론 FPS<strong>{format(status.inference_fps)}</strong></article>
      <article>화면 FPS<strong>{format(displayFps)}</strong></article>
      <article>수신 해상도<strong>{transportStats.width && transportStats.height ? `${transportStats.width}×${transportStats.height}` : '-'}</strong></article>
      <article>서버 입력 해상도<strong>{status.received_width && status.received_height ? `${status.received_width}×${status.received_height}` : '-'}</strong></article>
      <article>수신 비트레이트<strong>{format(transportStats.bitrateMbps)} Mbps</strong></article>
      <article>서버 수신→overlay<strong>{format(status.timings?.receive_to_overlay_ms)} ms</strong></article>
      <article>추론 전 건너뜀<strong>{status.dropped_before_inference ?? 0}</strong></article>
      <article>브라우저 decode<strong>{format(transportStats.decodeMs)} ms</strong></article>
    </section>
    <details><summary>세부 계측</summary><pre>{JSON.stringify({ camera: status.camera, timings: status.timings,
      receive_conversion_ms: status.receive_conversion_ms, viewer_transport: status.viewer_transport,
      last_frame_id: status.last_frame_id, last_source_index: status.last_source_index, transportStats }, null, 2)}</pre></details>
    <button onClick={() => setRetry(x => x + 1)} disabled={!status.session_id}>영상 다시 연결</button>
    <footer>영상 저장 없음 · 서버 지연은 스마트폰 전송 및 브라우저 재생 지연을 포함하지 않습니다.</footer>
  </main>;
}

createRoot(document.getElementById('root')).render(<App />);
