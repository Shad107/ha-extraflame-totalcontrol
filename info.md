# Extraflame TotalControl 2.0

Cloud-polling Home Assistant integration for La Nordica-Extraflame
pellet stoves using the same backend the official TotalControl 2.0 app
talks to (`appapi.extraflame.it`). No hardware modification, no firmware
flashing, no Wi-Fi module reverse-engineering — uses your existing
TotalControl account credentials.

Works with any color of Wi-Fi module (Black Label, White Label, or
built-in display) since everything goes through the cloud REST relay.

## Features

- UI configuration via config flow (email + password)
- Cloud polling every 30 s (configurable)
- **`climate`** entity — on/off + target room temperature
- **`select`** entity — power level P1..P5
- **9 sensors** — room / water / smoke / target / current power /
  target power / fan speed / machine state / alarm code
- **3 binary sensors** — online, alarm, **smoke-temperature warning**
  (≥ 400 °C — flue red-glow risk, not surfaced in the official app)
- **Lovelace card with inline SVG** rendering of the stove, flames
  proportional to power, color shifting with state
- Same repo ships a **standalone Docker proxy** (FastAPI) for any
  consumer that prefers a generic REST source

See the [README](https://github.com/Shad107/ha-extraflame-totalcontrol#readme)
for full API documentation and the Lovelace card template.

## Roadmap

- Per-stove DeviceInfo with macAddress identifier
- Translations (it, fr)
- Workflow Crono editor as a service
- Time-set service for clock drift correction
- GHCR pre-built Docker image
