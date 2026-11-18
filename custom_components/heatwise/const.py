"""Constants for HeatWise."""

from __future__ import annotations

DOMAIN = "heatwise"
PLATFORMS = ["climate", "sensor", "binary_sensor", "switch", "number"]

HOUSE_ZONE_ID = "house"

# House settings (config entry data/options)
CONF_NAME = "name"
CONF_BOILER = "boiler_entity"
CONF_HOUSE_SENSOR = "house_temp_sensor"
CONF_HOUSE_HUMIDITY = "house_humidity_sensor"
CONF_ZONE_HUMIDITY = "humidity_sensor"
CONF_MOULD = "mould_protection"
CONF_MOULD_RH = "mould_humidity"
CONF_MOULD_HOURS = "mould_hours"
CONF_MOULD_TEMP = "mould_min_temp"
DEFAULT_MOULD_RH = 65.0
DEFAULT_MOULD_HOURS = 2.0
DEFAULT_MOULD_TEMP = 19.0
MOULD_HYSTERESIS = 3.0
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
CONF_LANGUAGE = "language"

# Open window guessed from a fast temperature drop
CONF_WINDOW_DETECT = "window_detect"
CONF_WINDOW_DROP = "window_drop"
CONF_WINDOW_DROP_MINUTES = "window_drop_minutes"
CONF_WINDOW_HOLD = "window_hold_minutes"
LANG_AUTO = "auto"
LANGUAGES = (LANG_AUTO, "en", "ro")

# Smart start: preheat before the schedule, warm up when someone heads home
CONF_PREHEAT = "preheat"
CONF_PREHEAT_MAX = "preheat_max_minutes"
CONF_ARRIVAL_SENSORS = "arrival_sensors"
CONF_ARRIVAL_KM = "arrival_km"

# Notifications
CONF_NOTIFY = "notify_targets"
CONF_NOTIFY_WINDOW_TARGETS = "notify_window_targets"
CONF_NOTIFY_WINDOW = "notify_window"
CONF_NOTIFY_OFFLINE = "notify_offline"
CONF_WEEKLY_REPORT = "weekly_report"

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

# Equipment (from the datasheet / energy label, all optional)
CONF_BOILER_MODEL = "boiler_model"
CONF_BOILER_TYPE = "boiler_type"
CONF_BOILER_POWER_KW = "boiler_power_kw"
CONF_BOILER_EFFICIENCY_PCT = "boiler_efficiency_pct"
CONF_AC_MODEL = "ac_model"
CONF_AC_HEAT_W = "ac_heat_w"
CONF_AC_INPUT_W = "ac_input_w"
CONF_AC_ENERGY_CLASS = "ac_energy_class"

# Boiler power plug
CONF_BOILER_POWER = "boiler_power_sensor"
CONF_BURNER_THRESHOLD = "burner_threshold"
CONF_GAS_METER = "gas_meter_entity"
CONF_GAS_RATE = "gas_rate"
CONF_GAS_KWH_PER_M3 = "gas_kwh_per_m3"
CONF_GAS_BY_POWER = "gas_by_power"
CONF_SPLIT_HOT_WATER = "split_hot_water"

# Zones
CONF_ZONES = "zones"
CONF_ZONE_ID = "zone_id"
CONF_ZONE_NAME = "zone_name"
CONF_ZONE_SENSOR = "temp_sensor"
CONF_ZONE_TRVS = "trvs"
CONF_ZONE_ACS = "acs"
CONF_ZONE_FOLLOW_BOILER = "trv_follow_boiler"
CONF_ZONE_AC_POWER = "ac_power_sensors"

# Consumption periods
PERIODS = ("today", "month", "year")
STORED_PERIODS = ("today", "week", "month", "year")
AC_POWER_MAX_GAP_SECONDS = 900

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
DEFAULT_GAS_RATE = 1.5
DEFAULT_GAS_KWH_PER_M3 = 10.5
GAS_RATE_MIN = 0.2
GAS_RATE_MAX = 6.0
GAS_CALIBRATION_MIN_HOURS = 3.0
POWER_WEIGHT_MIN = 0.5
POWER_WEIGHT_MAX = 1.6
POWER_REF_HOURS = 10.0  # the reference burner power follows roughly the last 10 burner hours
HOT_WATER_GRACE_SECONDS = 90  # burner time right after a heat call still counts as heating
METER_SOURCE_SENSOR = "sensor"
METER_SOURCE_MANUAL = "manual"

DEFAULT_WINDOW_DROP = 0.8
DEFAULT_WINDOW_DROP_MINUTES = 10
DEFAULT_WINDOW_HOLD = 30
WINDOW_CLOSED_RISE = 0.3
WINDOW_MIN_OPEN_MINUTES = 3

DEFAULT_PREHEAT_MAX = 180
DEFAULT_ARRIVAL_KM = 15.0
DEFAULT_HEAT_RATE = 1.5  # °C per hour until HeatWise learns the house
HEAT_RATE_MIN = 0.2
HEAT_RATE_MAX = 6.0
HEAT_SESSION_MAX_HOURS = 6.0
ARRIVAL_MIN_PROGRESS_KM = 1.0
ARRIVAL_LATCH_MINUTES = 45
OFFLINE_MINUTES = 15
REPORT_WEEKDAY = 6  # Sunday
REPORT_HOUR = 19

EVAL_INTERVAL_SECONDS = 60
DEBOUNCE_SECONDS = 2
OWN_COMMAND_GRACE_SECONDS = 45
WINDOW_DELAY_SECONDS = 60
STORAGE_VERSION = 1

SIGNAL_UPDATE = f"{DOMAIN}_update_{{}}"
