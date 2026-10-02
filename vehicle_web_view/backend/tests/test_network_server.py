import json
import socket
from threading import Thread
import time
from urllib.request import urlopen

import uvicorn
from websockets.sync.client import connect

from vehicle_web.api.engine_app import create_app


def test_real_uvicorn_http_and_metrics_websocket():
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(), log_level="critical", access_log=False))
    worker = Thread(target=server.run, kwargs={"sockets": [listener]})
    worker.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=5) as response:
            assert json.load(response)["status"] == "ok"
        with connect(f"ws://127.0.0.1:{port}/api/metrics", open_timeout=5, proxy=None) as websocket:
            assert json.loads(websocket.recv(timeout=5))["state"] == "NO_CAMERA"
    finally:
        server.should_exit = True
        worker.join(5)
        listener.close()
        assert not worker.is_alive()
