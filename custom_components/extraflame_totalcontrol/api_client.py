"""Async Python client for the Extraflame TotalControl 2.0 cloud API.

Reverse-engineered from the official Android app (`com.extraflame.smartstove`).
Targets `https://appapi.extraflame.it/`. The same backend powers La Nordica
TotalControl 2.0 - works for any Extraflame / La Nordica pellet stove
registered to a TotalControl account.

Example:

    import asyncio
    from extraflame_totalcontrol import ExtraflameClient

    async def main():
        async with ExtraflameClient("you@example.com", "secret") as c:
            await c.login()
            stoves = await c.list_stoves()
            for s in stoves:
                params = await c.get_parameters(s.id)
                print(s.name, params["roomTemp"], params["smokeTemp"])
                await c.set_power(s.id, 3)

    asyncio.run(main())
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://appapi.extraflame.it"
DEFAULT_TIMEOUT = 20.0
PARAMETER_KEYS = (
    "roomTemp",
    "waterTemp",
    "smokeTemp",
    "power",
    "machineState",
    "targetRoomTemp",
    "targetWaterTemp",
    "targetPower",
    "weekChronoEnabled",
    "mainFanMode",
    "can1FanMode",
    "can2FanMode",
    "mainFanSpeed",
    "timeSettings",
    "cronoSettings",
    "alarmCode",
)


class ExtraflameError(Exception):
    """Base class for client errors."""


class ExtraflameAuthError(ExtraflameError):
    """Login failed or token expired."""


class ExtraflameAPIError(ExtraflameError):
    """Non-2xx response from the API."""

    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body[:200]}")
        self.status = status
        self.body = body


@dataclass(frozen=True)
class Stove:
    """A stove registered to the account."""

    id: str
    name: str
    mac_address: str
    resource_id: str | None
    type: str | None
    owner: bool
    permission: str | None
    position: str | None
    latitude: float | None
    longitude: float | None
    country: str | None
    locality: str | None
    raw: dict[str, Any]

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Stove":
        return cls(
            id=data["id"],
            name=data.get("name") or "",
            mac_address=data.get("macAddress") or "",
            resource_id=data.get("resourceId"),
            type=data.get("type"),
            owner=bool(data.get("owner", False)),
            permission=data.get("permission"),
            position=data.get("position"),
            latitude=data.get("latitude"),
            longitude=data.get("longitude"),
            country=data.get("country"),
            locality=data.get("locality"),
            raw=data,
        )


@dataclass(frozen=True)
class StoveParameter:
    """A single parameter sample returned by the API."""

    parameter: str
    value: float | int | str | None
    when_ms: int | None
    raw: dict[str, Any]

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "StoveParameter":
        v: float | int | str | None
        if data.get("doubleVal") is not None:
            v = data["doubleVal"]
        elif data.get("intVal") is not None:
            v = data["intVal"]
        elif data.get("stringVal") is not None:
            v = data["stringVal"]
        else:
            v = None
        return cls(
            parameter=data["parameter"],
            value=v,
            when_ms=data.get("when"),
            raw=data,
        )


class ExtraflameClient:
    """Async client. Use as an async context manager.

    Auth is via ``X-AUTH-TOKEN`` header. Token is obtained from
    ``POST /auth`` and stored on the instance until :meth:`logout` or
    until a 401 forces a re-login.
    """

    def __init__(
        self,
        username: str,
        password: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._username = username
        self._password = password
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._token: str | None = None
        self._http_owned = http is None
        self._http = http or httpx.AsyncClient(timeout=timeout)

    async def __aenter__(self) -> "ExtraflameClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._http_owned:
            await self._http.aclose()

    @property
    def token(self) -> str | None:
        return self._token

    async def login(self) -> str:
        """Authenticate and store the bearer token. Returns the token."""
        r = await self._http.post(
            f"{self._base_url}/auth",
            json={"username": self._username, "password": self._password},
            headers={"Content-Type": "application/json"},
        )
        if r.status_code == 401:
            raise ExtraflameAuthError("Invalid credentials")
        if not r.is_success:
            raise ExtraflameAPIError(r.status_code, r.text)
        data = r.json()
        token = data.get("token")
        if not token:
            raise ExtraflameAuthError("No token in response")
        self._token = token
        return token

    def logout(self) -> None:
        """Drop the in-memory token. Does not call the server."""
        self._token = None

    async def _get(self, path: str) -> Any:
        if not self._token:
            await self.login()
        r = await self._http.get(
            f"{self._base_url}{path}",
            headers={"X-AUTH-TOKEN": self._token or ""},
        )
        if r.status_code == 401:
            await self.login()
            r = await self._http.get(
                f"{self._base_url}{path}",
                headers={"X-AUTH-TOKEN": self._token or ""},
            )
        if not r.is_success:
            raise ExtraflameAPIError(r.status_code, r.text)
        return r.json()

    async def _post(self, path: str, body: Any = None) -> Any:
        if not self._token:
            await self.login()
        r = await self._http.post(
            f"{self._base_url}{path}",
            headers={"X-AUTH-TOKEN": self._token or "", "Content-Type": "application/json"},
            json=body if body is not None else {},
        )
        if r.status_code == 401:
            await self.login()
            r = await self._http.post(
                f"{self._base_url}{path}",
                headers={"X-AUTH-TOKEN": self._token or "", "Content-Type": "application/json"},
                json=body if body is not None else {},
            )
        if not r.is_success:
            raise ExtraflameAPIError(r.status_code, r.text)
        if not r.content:
            return None
        try:
            return r.json()
        except ValueError:
            return r.text

    async def list_stoves(self) -> list[Stove]:
        """Return all stoves the account has access to."""
        data = await self._get("/stoves")
        items = data.get("data") if isinstance(data, dict) else data
        return [Stove.from_api(x) for x in (items or [])]

    async def is_online(self, stove_id: str) -> bool:
        data = await self._get(f"/stoves/{stove_id}/isOnline")
        if isinstance(data, dict):
            return bool(data.get("data"))
        return bool(data)

    async def get_parameters(
        self, stove_id: str, parameters: tuple[str, ...] = PARAMETER_KEYS
    ) -> dict[str, StoveParameter]:
        """Get the latest value for each requested parameter.

        Returns a dict keyed by parameter name.
        """
        params = ",".join(parameters)
        data = await self._get(f"/stoves/{stove_id}/lasts/parameters/{params}")
        items = data.get("data") if isinstance(data, dict) else data
        out: dict[str, StoveParameter] = {}
        for raw in items or []:
            sp = StoveParameter.from_api(raw)
            out[sp.parameter] = sp
        return out

    async def user_details(self) -> dict[str, Any]:
        return await self._get("/authenticated/user")

    async def send_command(
        self, stove_id: str, topic: str, command: dict[str, Any]
    ) -> Any:
        """Send a sendCommand to the stove. Topic is one of: settings, time, crono."""
        return await self._post(f"/stoves/{stove_id}/sendCommand/{topic}", command)

    async def set_power(self, stove_id: str, target_power: int) -> Any:
        """Set target power level (1-5 typical). Sends to 'settings' topic."""
        return await self.send_command(stove_id, "settings", {"targetPower": int(target_power)})

    async def set_machine_state(self, stove_id: str, state: int) -> Any:
        """Turn the stove on/off via the machineState enum (device-specific)."""
        return await self.send_command(stove_id, "settings", {"machineState": int(state)})

    async def set_room_temp(self, stove_id: str, target_room_temp: float) -> Any:
        """Set the target ambient temperature."""
        return await self.send_command(
            stove_id, "settings", {"targetRoomTemp": float(target_room_temp)}
        )

    async def set_thresholds(
        self, stove_id: str, min_threshold: float, max_threshold: float
    ) -> Any:
        return await self._post(
            f"/stoves/{stove_id}/setThresholds",
            {"minThreshold": min_threshold, "maxThreshold": max_threshold},
        )
