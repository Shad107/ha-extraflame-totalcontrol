"""FastAPI webapi wrapping the Extraflame TotalControl 2.0 cloud client.

Designed to run alongside Home Assistant or any other consumer. Exposes the
TotalControl REST API on localhost with a single Extraflame credential set,
caches reads, and provides a tidy JSON surface that's easy to integrate
with generic REST sensors / commands.

Configuration via env:
    EXTRAFLAME_USERNAME   account email
    EXTRAFLAME_PASSWORD   account password
    EXTRAFLAME_POLL_SEC   polling interval for parameter cache (default 30)
"""
from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from extraflame_totalcontrol import (
    ExtraflameAPIError,
    ExtraflameAuthError,
    ExtraflameClient,
    Stove,
    StoveParameter,
)

USERNAME = os.environ.get("EXTRAFLAME_USERNAME", "")
PASSWORD = os.environ.get("EXTRAFLAME_PASSWORD", "")
POLL_SEC = int(os.environ.get("EXTRAFLAME_POLL_SEC", "30"))

_state: dict[str, dict] = {
    "stoves": {},
    "parameters": {},
    "online": {},
    "last_refresh": 0.0,
    "errors": [],
}
_client: ExtraflameClient | None = None
_poll_task: asyncio.Task | None = None


async def _refresh_once() -> None:
    assert _client is not None
    stoves = await _client.list_stoves()
    _state["stoves"] = {s.id: s for s in stoves}
    for s in stoves:
        try:
            _state["online"][s.id] = await _client.is_online(s.id)
            _state["parameters"][s.id] = await _client.get_parameters(s.id)
        except ExtraflameAPIError as e:
            _state["errors"].append(f"{s.id}: {e}")
    _state["last_refresh"] = time.time()


async def _poll_loop() -> None:
    while True:
        try:
            await _refresh_once()
            _state["errors"] = []
        except ExtraflameAuthError as e:
            _state["errors"].append(f"auth: {e}")
        except Exception as e:
            _state["errors"].append(str(e))
        await asyncio.sleep(POLL_SEC)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _client, _poll_task
    if not USERNAME or not PASSWORD:
        raise RuntimeError("EXTRAFLAME_USERNAME and EXTRAFLAME_PASSWORD must be set")
    _client = ExtraflameClient(USERNAME, PASSWORD)
    await _client.login()
    await _refresh_once()
    _poll_task = asyncio.create_task(_poll_loop())
    yield
    if _poll_task:
        _poll_task.cancel()
    if _client:
        await _client.close()


app = FastAPI(
    title="Extraflame TotalControl 2.0 proxy",
    version="0.1.0",
    lifespan=lifespan,
)


def _stove_dict(s: Stove) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "mac_address": s.mac_address,
        "resource_id": s.resource_id,
        "type": s.type,
        "owner": s.owner,
        "permission": s.permission,
        "country": s.country,
        "locality": s.locality,
        "latitude": s.latitude,
        "longitude": s.longitude,
    }


def _parameters_dict(params: dict[str, StoveParameter]) -> dict:
    return {k: {"value": p.value, "when_ms": p.when_ms} for k, p in params.items()}


@app.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "last_refresh": _state["last_refresh"],
        "stove_count": len(_state["stoves"]),
        "errors": _state["errors"][-5:],
    }


@app.get("/stoves")
async def list_stoves() -> dict:
    return {"stoves": [_stove_dict(s) for s in _state["stoves"].values()]}


@app.get("/stoves/{stove_id}")
async def get_stove(stove_id: str) -> dict:
    s = _state["stoves"].get(stove_id)
    if not s:
        raise HTTPException(404, "Stove not found")
    return _stove_dict(s)


@app.get("/stoves/{stove_id}/parameters")
async def get_parameters(stove_id: str) -> dict:
    if stove_id not in _state["stoves"]:
        raise HTTPException(404, "Stove not found")
    return {
        "parameters": _parameters_dict(_state["parameters"].get(stove_id, {})),
        "online": _state["online"].get(stove_id),
        "last_refresh": _state["last_refresh"],
    }


@app.post("/stoves/{stove_id}/power/{level}")
async def set_power(stove_id: str, level: int) -> dict:
    assert _client is not None
    await _client.set_power(stove_id, level)
    return {"ok": True}


@app.post("/stoves/{stove_id}/state/{state}")
async def set_state(stove_id: str, state: int) -> dict:
    assert _client is not None
    await _client.set_machine_state(stove_id, state)
    return {"ok": True}


@app.post("/stoves/{stove_id}/target_room_temp/{temp}")
async def set_target_temp(stove_id: str, temp: float) -> dict:
    assert _client is not None
    await _client.set_room_temp(stove_id, temp)
    return {"ok": True}
