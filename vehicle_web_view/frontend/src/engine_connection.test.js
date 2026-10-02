import { describe, it, afterEach, mock } from 'node:test';
import assert from 'node:assert/strict';
import { api, gatherIce, videoQualityStats } from './engine_connection.js';

it('reports actual resolution and interval receive bitrate', () => {
  const row = { timestamp: 2000, bytesReceived: 600000, frameWidth: 1280, frameHeight: 720 };
  assert.deepEqual(videoQualityStats(row, { time: 1000, bytes: 100000 }),
    { width: 1280, height: 720, bitrateMbps: 4 });
  assert.equal(videoQualityStats(row).bitrateMbps, null);
  assert.equal(videoQualityStats(row, { time: 1000, bytes: 700000 }).bitrateMbps, null);
});

describe('signaling', () => {
  afterEach(() => mock.restoreAll());
  it('uses the same-origin API', async () => {
    const fetchMock = mock.method(globalThis, 'fetch', async () => ({ ok: true, json: async () => ({ state: 'NO_CAMERA' }) }));
    assert.equal((await api('/api/state')).state, 'NO_CAMERA');
    assert.deepEqual(fetchMock.mock.calls[0].arguments, ['/api/state', {}]);
  });
  it('propagates HTTP errors', async () => {
    mock.method(globalThis, 'fetch', async () => ({ ok: false, status: 409, text: async () => 'busy' }));
    await assert.rejects(api('/api/sessions'), /409: busy/);
  });
  it('does not signal before ICE gathering completes', async () => {
    const peer = new EventTarget(); peer.iceGatheringState = 'gathering';
    const waiting = gatherIce(peer, 1000);
    peer.iceGatheringState = 'complete'; peer.dispatchEvent(new Event('icegatheringstatechange'));
    await waiting;
  });
  it('fails rather than hang on ICE timeout', async () => {
    const peer = new EventTarget(); peer.iceGatheringState = 'gathering';
    await assert.rejects(gatherIce(peer, 1), /timeout/);
  });
});
