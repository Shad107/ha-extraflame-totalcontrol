DOMAIN = "extraflame_totalcontrol"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_POLL_INTERVAL = "poll_interval"
DEFAULT_POLL_INTERVAL = 30

VERSION = "0.2.1"

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

# HA-side auto-modulation: the stove itself never picks a power level
# between P1 and P5 on its own. The user-set targetPower stays put
# while WORK is active. This integration optionally drives targetPower
# from the room/setpoint delta so HA emulates the missing continuous
# modulation. Specialists discourage P1 (incomplete combustion, soot)
# — the default floor is P2.
CONF_AUTO_MIN_POWER = "auto_min_power"
CONF_AUTO_MAX_POWER = "auto_max_power"
CONF_AUTO_DEADBAND = "auto_deadband"
DEFAULT_AUTO_MIN_POWER = 2
DEFAULT_AUTO_MAX_POWER = 5
DEFAULT_AUTO_DEADBAND = 0.3  # °C, avoids oscillation around thresholds

# Multi-source sensor aggregation. Lets the integration pull temperature
# and humidity readings from any sensor HA already knows about (Tado TRV
# heads, Aqara, Z-Wave probes, ESPHome custom — anything with
# device_class temperature or humidity). The aggregate becomes the input
# to the auto-modulation algorithm instead of the stove's lone embedded
# probe, which sits next to the appliance and is biased upward by
# proximity to the fire.
CONF_TEMP_SENSORS = "temp_sensors"
CONF_HUMIDITY_SENSORS = "humidity_sensors"
CONF_AGGREGATION_MODE = "aggregation_mode"
AGGREGATION_MODES = ("weighted_avg", "min", "max", "stove_only")
DEFAULT_AGGREGATION_MODE = "weighted_avg"

# Outdoor temperature — single source. Used to compute the
# indoor/outdoor delta that drives thermal-loss estimates and
# anticipatory heating logic (v0.3.0+).
CONF_OUTDOOR_TEMP_SENSOR = "outdoor_temp_sensor"

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
