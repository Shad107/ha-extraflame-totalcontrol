DOMAIN = "extraflame_totalcontrol"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_POLL_INTERVAL = "poll_interval"
DEFAULT_POLL_INTERVAL = 30

VERSION = "0.1.7"

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
