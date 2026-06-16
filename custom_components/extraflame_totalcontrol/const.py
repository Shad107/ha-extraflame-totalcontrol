DOMAIN = "extraflame_totalcontrol"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_POLL_INTERVAL = "poll_interval"
DEFAULT_POLL_INTERVAL = 30

VERSION = "0.1.12"

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
# Labels track the exact phase terminology from the Teodora Evo
# manual ([PDF, La Nordica-Extraflame, p. WORK/MODULATION section]):
#   IGNITION    : allumage initial
#   PREPARATION : stabilisation de la combustion + start ventilation
#   WORK        : burn at user-set targetPower while delta > 0
#   MODULATION  : factory-default behaviour when setpoint reached —
#                 stove keeps burning at MINIMUM power (~P1), not off
#   STAND BY    : only reached if the user has explicitly enabled the
#                 Stand By function in the stove menu; full shutdown
#                 after setpoint + DELTA T OFF reached, restarts
#                 automatically when room cools below setpoint - delta
#   COOLING     : forced cool-down before re-ignition
MACHINE_STATE_LABELS: dict[int, str] = {
    0: "Off",
    1: "Check up",
    2: "Ignition",
    3: "Preparation",
    4: "Préchargement",
    5: "Modulation",      # burning at minimum, NOT off — see note above
    6: "Work",            # burning at targetPower
    7: "Nettoyage",
    8: "Cooling",
    9: "Stand by",        # only if Stand By function is ON
    10: "Final cleaning",
    11: "Recovery",
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
