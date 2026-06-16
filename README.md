# Extraflame TotalControl 2.0

[![License](https://img.shields.io/github/license/Shad107/ha-extraflame-totalcontrol.svg)](LICENSE)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz/)

Python client, Docker webapi and Home Assistant integration for the
**Extraflame TotalControl 2.0** cloud API — the same backend the official
TotalControl app talks to. Works for any La Nordica / Extraflame pellet stove
registered to a TotalControl account, regardless of the Wi-Fi module color
(Black Label, White Label, integrated display).

This project does **not** require flashing the Wi-Fi module, opening the stove,
or installing any extra hardware. It uses the account credentials you already
have for the app.

## What this provides

Three layers, share the same code:

1. **`extraflame_totalcontrol`** — minimal async Python client (`httpx`-based).
2. **`docker/`** — FastAPI webapi that wraps the client behind a tidy local
   REST surface, with caching and a parameter polling loop. Drop-in for any
   automation tool that can hit HTTP.
3. **`custom_components/extraflame_totalcontrol/`** — Home Assistant
   custom component. Cloud-polling, native sensors + binary sensor per
   stove. Climate entity for full control is on the roadmap.

## How the API works

Reverse-engineered from the official Android APK
(`com.extraflame.smartstove`).

- Base: `https://appapi.extraflame.it/`
- Auth: `POST /auth` body `{username, password}` → returns `{token}`.
- All subsequent calls carry `X-AUTH-TOKEN: <token>` (note: not `Authorization: Bearer`).
- Reads: `GET /stoves`, `GET /stoves/{id}/isOnline`,
  `GET /stoves/{id}/lasts/parameters/{comma_list}`.
- Writes: `POST /stoves/{id}/sendCommand/{topic}` with a JSON map.
  Topics are `settings` (power, fans, on/off), `time`, `crono`.
- TLS: presented by `mqtt.extraflame.it` cert signed by Omnyvore CA
  (private). Doesn't affect API consumers — `appapi.extraflame.it`
  uses a normal public CA.

The Wi-Fi module on the stove keeps its own MQTTS tunnel to
`93.46.203.43:8883` (Omnyvore-hosted cloud). The phone app, the Docker proxy
and this HA integration all read/write through the **REST cloud relay** —
the module is never contacted directly.

### Endpoints in use

| Verb | Path | Returns / takes |
|---|---|---|
| `POST` | `/auth` | `{username, password}` → `{token}` |
| `GET`  | `/stoves` | list of stoves on the account |
| `GET`  | `/stoves/{id}/isOnline` | bool |
| `GET`  | `/stoves/{id}/lasts/parameters/{a,b,c,…}` | latest values |
| `POST` | `/stoves/{id}/sendCommand/settings` | targetPower, machineState, …fan modes |
| `POST` | `/stoves/{id}/sendCommand/time` | day/month/year/hour/minute/weekday |
| `POST` | `/stoves/{id}/sendCommand/crono` | weekly schedule |
| `PUT`  | `/stoves/{id}/setThresholds` | min/max thresholds |
| `GET`  | `/authenticated/user` | profile |

### Parameters

Reads from `/stoves/{id}/lasts/parameters/{…}` accept any comma-separated
subset of these keys (the names come from the app's source):

```
roomTemp, waterTemp, smokeTemp, power, machineState,
targetRoomTemp, targetWaterTemp, targetPower, weekChronoEnabled,
mainFanMode, can1FanMode, can2FanMode, mainFanSpeed,
timeSettings, cronoSettings, alarmCode
```

Each entry in the response is shaped like:

```json
{
  "parameter": "smokeTemp",
  "doubleVal": 32.0,
  "when": 1781619634970,
  "valType": null
}
```

`doubleVal` / `intVal` / `stringVal` is set depending on the type. NaN
shows up as Python `float('nan')`; the HA integration filters those out.

## Python client

```bash
pip install -e .
```

```python
import asyncio
from extraflame_totalcontrol import ExtraflameClient

async def main():
    async with ExtraflameClient("you@example.com", "secret") as c:
        await c.login()
        for s in await c.list_stoves():
            params = await c.get_parameters(s.id)
            print(s.name, params["roomTemp"].value, params["smokeTemp"].value)
        # await c.set_power(s.id, 3)

asyncio.run(main())
```

## Docker proxy

```bash
cd docker/
EXTRAFLAME_USERNAME=you@example.com \
EXTRAFLAME_PASSWORD=secret \
  docker compose up -d
```

The proxy polls Extraflame every `EXTRAFLAME_POLL_SEC` seconds (default
30) and serves a JSON view at `http://localhost:8080/stoves/{id}/parameters`.
Useful as a generic REST sensor source for Home Assistant, Node-RED, or
anything else.

Endpoints:

```
GET  /health
GET  /stoves
GET  /stoves/{id}
GET  /stoves/{id}/parameters
POST /stoves/{id}/power/{level}
POST /stoves/{id}/state/{state}
POST /stoves/{id}/target_room_temp/{temp}
```

## Home Assistant integration

### Install via HACS

1. HACS → Integrations → ⋮ → *Custom repositories*.
2. Add `https://github.com/Shad107/ha-extraflame-totalcontrol` as
   category *Integration*.
3. Search for **Extraflame TotalControl 2.0**, download.
4. Restart Home Assistant.
5. Settings → Devices & Services → *Add Integration* → Extraflame
   TotalControl 2.0. Enter the email + password you use for the app.

### What v0.1 ships

- `binary_sensor.<stove>_online`
- `sensor.<stove>_room_temperature`
- `sensor.<stove>_water_temperature`
- `sensor.<stove>_smoke_temperature`
- `sensor.<stove>_current_power`
- `sensor.<stove>_target_power`
- `sensor.<stove>_target_room_temperature`
- `sensor.<stove>_machine_state`
- `sensor.<stove>_alarm_code`
- `sensor.<stove>_main_fan_speed`

### Roadmap

- `climate.<stove>` with on/off + target temp + presets
- `select.<stove>_power` (1..5)
- Service to send raw `sendCommand` payloads
- Per-stove `DeviceInfo` with the macAddress as identifier
- Translations (it, fr)

## Disclaimer

This project is not affiliated with La Nordica-Extraflame nor Omnyvore.
The endpoints described here can change without notice; if they do,
open an issue.

The original cloud platform belongs to its owners. Use this only with
accounts and stoves you legitimately own / are entitled to control.

## License

Apache-2.0 — see [LICENSE](LICENSE).
