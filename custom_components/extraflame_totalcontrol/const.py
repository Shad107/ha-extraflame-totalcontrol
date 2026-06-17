DOMAIN = "extraflame_totalcontrol"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_POLL_INTERVAL = "poll_interval"
DEFAULT_POLL_INTERVAL = 30

VERSION = "0.5.0"

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
# - the default floor is P2.
CONF_AUTO_MIN_POWER = "auto_min_power"
CONF_AUTO_MAX_POWER = "auto_max_power"
CONF_AUTO_DEADBAND = "auto_deadband"
DEFAULT_AUTO_MIN_POWER = 2
DEFAULT_AUTO_MAX_POWER = 5
DEFAULT_AUTO_DEADBAND = 0.3  # °C, avoids oscillation around thresholds

# Multi-source sensor aggregation. Lets the integration pull temperature
# and humidity readings from any sensor HA already knows about (Tado TRV
# heads, Aqara, Z-Wave probes, ESPHome custom - anything with
# device_class temperature or humidity). The aggregate becomes the input
# to the auto-modulation algorithm instead of the stove's lone embedded
# probe, which sits next to the appliance and is biased upward by
# proximity to the fire.
CONF_TEMP_SENSORS = "temp_sensors"
CONF_HUMIDITY_SENSORS = "humidity_sensors"
CONF_AGGREGATION_MODE = "aggregation_mode"
AGGREGATION_MODES = ("weighted_avg", "min", "max", "stove_only")
DEFAULT_AGGREGATION_MODE = "weighted_avg"

# Outdoor temperature - single source. Used to compute the
# indoor/outdoor delta that drives thermal-loss estimates and
# anticipatory heating logic (v0.3.0+).
CONF_OUTDOOR_TEMP_SENSOR = "outdoor_temp_sensor"

# Pellet level tracking. The cloud API does not expose a hopper level
# reading and the Teodora Evo lacks a physical level sensor. We
# estimate by integrating consumption rate (kg/h, interpolated between
# P1 and P5 per the manual) over time since the last user-confirmed
# refill. The user presses button.<stove>_refill_pellet whenever they
# fill the hopper, which resets the counter to the configured capacity.
CONF_PELLET_HOPPER_CAPACITY_KG = "pellet_hopper_capacity_kg"
CONF_PELLET_CONSUMPTION_P1_KG_H = "pellet_conso_p1"
CONF_PELLET_CONSUMPTION_P2_KG_H = "pellet_conso_p2"
CONF_PELLET_CONSUMPTION_P3_KG_H = "pellet_conso_p3"
CONF_PELLET_CONSUMPTION_P4_KG_H = "pellet_conso_p4"
CONF_PELLET_CONSUMPTION_P5_KG_H = "pellet_conso_p5"
# Defaults per the Teodora Evo datasheet (0.5 .. 1.8 kg/h end-to-end,
# linear interpolation in between).
DEFAULT_PELLET_HOPPER_CAPACITY_KG = 14.0
DEFAULT_PELLET_CONSUMPTION_P1_KG_H = 0.5
DEFAULT_PELLET_CONSUMPTION_P2_KG_H = 0.83
DEFAULT_PELLET_CONSUMPTION_P3_KG_H = 1.15
DEFAULT_PELLET_CONSUMPTION_P4_KG_H = 1.48
DEFAULT_PELLET_CONSUMPTION_P5_KG_H = 1.8
PELLET_LOW_WARNING_PCT = 15.0
PELLET_CRITICAL_WARNING_PCT = 5.0
PELLET_STORE_VERSION = 1

# v0.2.7 - per-room humidity scoring. ASHRAE comfort range is 30..60% RH
# in winter; below 30% triggers dry-air symptoms (dry skin, static, more
# viral transmission), above 65% accelerates mould risk on cold walls.
# Defaults match comfort guidance and can be tuned per-home.
CONF_HUMIDITY_COMFORT_LOW_PCT = "humidity_comfort_low_pct"
CONF_HUMIDITY_COMFORT_HIGH_PCT = "humidity_comfort_high_pct"
DEFAULT_HUMIDITY_COMFORT_LOW_PCT = 30.0
DEFAULT_HUMIDITY_COMFORT_HIGH_PCT = 65.0

# v0.3.0 - thermal RC model fit (inertia learner).
# Reads the last N days of indoor+outdoor temperatures from HA Recorder,
# filters out periods when the stove was burning (running/cooldown), and
# fits dT/dt = -(T_in - T_out)/tau on the natural drift. Tau (the time
# constant in hours) tells you "if the heating stops, how long before
# the room loses 1/e ~ 63% of its delta with the outdoors". Big tau =
# well-insulated home, small tau = leaky envelope.
#
# Why this works year-round: even in summer the indoor temperature
# tracks the outdoor diurnal cycle through the envelope. The decay
# constant of that tracking IS the thermal time constant. No stove
# needed - just patience and enough recorder history.
THERMAL_STORE_VERSION = 1
THERMAL_LEARN_DAYS = 14            # detailed-history fallback window
THERMAL_LEARN_STATS_DAYS = 365     # long-term-stats preferred window (1 year)
THERMAL_RESAMPLE_SECONDS = 300     # 5-minute resampling grid (history mode)
THERMAL_COOLDOWN_AFTER_STOVE_S = 3600  # skip 1h after stove last burned
THERMAL_MIN_SAMPLES = 50           # below this, fit is meaningless

# v0.4.0 - thermal prediction (steady-state + time to setpoint).
# The stove's heat output Q (kW) = pellet_consumption_rate * PCI. With a
# rough estimate of the home's thermal capacity C, we can predict the
# equilibrium temperature T_eq = T_out + Q*tau/C and the time it takes
# to ramp from current temp to setpoint via T(t) = T_eq + (T0-T_eq)*exp(-t/tau).
# Both numbers are sensitive to tau (still flagged low_confidence in
# summer); they get steadily more useful as the user re-presses
# "Learn inertia" through autumn.
CONF_PELLET_PCI_KWH_KG = "pellet_pci_kwh_kg"
CONF_HOME_HEAT_CAPACITY_MJ_PER_K = "home_heat_capacity_mj_per_k"
DEFAULT_PELLET_PCI_KWH_KG = 4.8       # typical wood pellet, 4.6..5.0 range
DEFAULT_HOME_HEAT_CAPACITY_MJ_PER_K = 5.0   # ~100 m2 average French home

# v0.5.0 - weather anticipation. Reads hourly forecast from any HA
# weather.* entity (Meteo-France, Met.no, OpenWeatherMap, etc.) and
# computes when to pre-heat the home so the room stays at setpoint
# even when a cold snap arrives. Uses the learned tau from v0.3.x
# and the steady-state model from v0.4.0.
CONF_WEATHER_ENTITY = "weather_entity"
CONF_COLD_SNAP_THRESHOLD_C = "cold_snap_threshold_c"
CONF_PREHEAT_TARGET_C = "preheat_target_c"
DEFAULT_COLD_SNAP_THRESHOLD_C = 5.0    # outdoor below this -> cold snap
DEFAULT_PREHEAT_TARGET_C = 20.0        # room temp to hold during cold
FORECAST_CACHE_SECONDS = 1800          # Meteo-France updates ~hourly

# Mapping inspired by the Micronova mainboard state codes commonly seen on
# Extraflame / La Nordica / MCZ / Ravelli pellet stoves. Verified on a
# Teodora Evo for the 0 = OFF code; the rest is the standard Micronova
# sequence - please open an issue with your stove model + observed codes
# if your machine reports something different.
# Labels track the exact phase terminology from the Teodora Evo
# manual ([PDF, La Nordica-Extraflame, p. WORK/MODULATION section]):
#   IGNITION    : allumage initial
#   PREPARATION : stabilisation de la combustion + start ventilation
#   WORK        : burn at user-set targetPower while delta > 0
#   MODULATION  : factory-default behaviour when setpoint reached -
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
    5: "Modulation",      # burning at minimum, NOT off - see note above
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
