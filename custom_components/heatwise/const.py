"""Constants for HeatWise."""

from __future__ import annotations

DOMAIN = "heatwise"
PLATFORMS = ["climate", "sensor", "binary_sensor", "switch"]

HOUSE_ZONE_ID = "house"

# House settings (config entry data/options)
CONF_NAME = "name"
CONF_BOILER = "boiler_entity"
CONF_HOUSE_SENSOR = "house_temp_sensor"
CONF_OUTDOOR = "outdoor_sensor"
CONF_PERSONS = "persons"
CONF_AWAY_DELAY = "away_delay"
CONF_SCHEDULE = "schedule_entity"
CONF_WINDOWS = "window_sensors"
CONF_COMFORT = "comfort_temp"
CONF_ECO = "eco_temp"
CONF_AWAY = "away_temp"
CONF_FROST = "frost_temp"
CONF_WARM_OFF = "warm_off_threshold"
CONF_OVERRIDE_MINUTES = "override_minutes"

# Hybrid / prices
CONF_HYBRID_MODE = "hybrid_mode"
CONF_AC_THRESHOLD = "ac_threshold"
CONF_AC_MIN_OUTDOOR = "ac_min_outdoor"
CONF_AC_OFFSET = "ac_offset"
CONF_GAS_PRICE_ENTITY = "gas_price_entity"
CONF_GAS_PRICE = "gas_price"
CONF_EL_PRICE_ENTITY = "electricity_price_entity"
CONF_EL_PRICE = "electricity_price"
CONF_BOILER_EFFICIENCY = "boiler_efficiency"
CONF_COP_AT_7 = "cop_at_7"

# Boiler power plug
CONF_BOILER_POWER = "boiler_power_sensor"
CONF_BURNER_THRESHOLD = "burner_threshold"

# Zones
CONF_ZONES = "zones"
CONF_ZONE_ID = "zone_id"
CONF_ZONE_NAME = "zone_name"
CONF_ZONE_SENSOR = "temp_sensor"
CONF_ZONE_TRVS = "trvs"
CONF_ZONE_ACS = "acs"
CONF_ZONE_FOLLOW_BOILER = "trv_follow_boiler"

DEFAULT_COMFORT = 21.0
DEFAULT_ECO = 18.0
DEFAULT_AWAY = 16.0
DEFAULT_FROST = 7.0
DEFAULT_AWAY_DELAY = 10
DEFAULT_OVERRIDE_MINUTES = 120
DEFAULT_AC_THRESHOLD = 8.0
DEFAULT_AC_MIN_OUTDOOR = -15.0
DEFAULT_AC_OFFSET = 2.0
DEFAULT_BOILER_EFFICIENCY = 0.92
DEFAULT_COP_AT_7 = 3.5
DEFAULT_BURNER_THRESHOLD = 30.0

EVAL_INTERVAL_SECONDS = 60
DEBOUNCE_SECONDS = 2
OWN_COMMAND_GRACE_SECONDS = 45
WINDOW_DELAY_SECONDS = 60
STORAGE_VERSION = 1

SIGNAL_UPDATE = f"{DOMAIN}_update_{{}}"
