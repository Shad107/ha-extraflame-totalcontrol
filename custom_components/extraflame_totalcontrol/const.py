DOMAIN = "extraflame_totalcontrol"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_POLL_INTERVAL = "poll_interval"
DEFAULT_POLL_INTERVAL = 30

VERSION = "0.1.10"

# Default preset recipes. Each preset is editable via the options flow
# (Settings → Devices → Extraflame → Configure). "enabled" toggles its
# appearance in the climate.preset_modes list without losing the values.
PRESET_NAMES = ("eco", "silence", "confort", "boost")
DEFAULT_PRESETS: dict[str, dict] = {
    "eco":     {"enabled": True, "power": 1, "target_temp": 18, "fan_mode": 1, "fan_speed": 0},
    "silence": {"enabled": True, "power": 2, "target_temp": 20, "fan_mode": 1, "fan_speed": 0},
    "confort": {"enabled": True, "power": 3, "target_temp": 21, "fan_mode": 1, "fan_speed": 0},
    "boost":   {"enabled": True, "power": 5, "target_temp": 24, "fan_mode": 2, "fan_speed": 6},
}
CONF_PRESETS = "presets"

# Mapping inspired by the Micronova mainboard state codes commonly seen on
# Extraflame / La Nordica / MCZ / Ravelli pellet stoves. Verified on a
# Teodora Evo for the 0 = OFF code; the rest is the standard Micronova
# sequence — please open an issue with your stove model + observed codes
# if your machine reports something different.
MACHINE_STATE_LABELS: dict[int, str] = {
    0: "Off",
    1: "Check up",
    2: "Allumage",
    3: "Stabilisation",
    4: "Pré-chargement",
    5: "Modulation",
    6: "Running",
    7: "Nettoyage",
    8: "Refroidissement",
    9: "Standby",
    10: "Final cleaning",
    11: "Recovery / récupération",
    12: "Allumage final",
}
MACHINE_STATE_OFF = {0, 9}
MACHINE_STATE_PREHEAT = {1, 2, 3, 4}
MACHINE_STATE_RUNNING = {5, 6}
MACHINE_STATE_COOLDOWN = {7, 8, 10, 11, 12}
URL_BASE = "/extraflame_totalcontrol_assets"
JSMODULES = [
    {
        "name": "Extraflame Stove Card",
        "filename": "extraflame-stove-card.js",
        "version": VERSION,
    },
]
