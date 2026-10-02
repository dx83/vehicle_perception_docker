"""Shared validation for server and container healthcheck port selection."""
import os


def read_server_port(default=8000, environ=None):
    environment = os.environ if environ is None else environ
    value = environment.get("VEHICLE_HTTP_PORT", str(default)).strip()
    if not value.isascii() or not value.isdecimal():
        raise ValueError("VEHICLE_HTTP_PORT must be a decimal integer in [1024, 65535]")
    port = int(value)
    if not 1024 <= port <= 65535:
        raise ValueError("VEHICLE_HTTP_PORT must be in [1024, 65535] for the non-root container")
    return port
