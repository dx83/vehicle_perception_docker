export function videoQualityStats(row, previous) {
  const elapsed = previous ? row.timestamp - previous.time : 0;
  const byteDelta = previous ? row.bytesReceived - previous.bytes : -1;
  return {
    width: row.frameWidth, height: row.frameHeight,
    bitrateMbps: elapsed > 0 && byteDelta >= 0 ? byteDelta * 8 / elapsed / 1000 : null,
  };
}

export async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) throw new Error(`${response.status}: ${await response.text()}`);
  return response.json();
}

export function gatherIce(peer, timeoutMs = 15000) {
  if (peer.iceGatheringState === 'complete') return Promise.resolve();
  return new Promise((resolve, reject) => {
    function cleanup() { clearTimeout(timer); peer.removeEventListener('icegatheringstatechange', changed); }
    function changed() {
      if (peer.iceGatheringState === 'complete') { cleanup(); resolve(); }
    }
    const timer = setTimeout(() => { cleanup(); reject(new Error('ICE gathering timeout')); }, timeoutMs);
    peer.addEventListener('icegatheringstatechange', changed);
    changed();
  });
}

export async function connectViewer(sessionId, onTrack, onState) {
  const config = await api('/api/rtc-config');
  const peer = new RTCPeerConnection(config);
  peer.addTransceiver('video', { direction: 'recvonly' });
  peer.ontrack = event => onTrack(event.streams[0] || new MediaStream([event.track]));
  peer.onconnectionstatechange = () => onState(peer.connectionState);
  try {
    await peer.setLocalDescription(await peer.createOffer());
    await gatherIce(peer);
    const answer = await api(`/api/sessions/${sessionId}/viewer/offer`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: peer.localDescription.type, sdp: peer.localDescription.sdp }),
    });
    await peer.setRemoteDescription(answer);
    return peer;
  } catch (error) { peer.close(); throw error; }
}
