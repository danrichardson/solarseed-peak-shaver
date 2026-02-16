"""Constants for the Solarseed Peak Shaver integration."""

DOMAIN = "solarseed_peak_shaver"
NAME = "Solarseed Peak Shaver"
VERSION = "0.2.2"

# --- Config keys ---
CONF_BATTERY_CAPACITY = "battery_capacity"
CONF_BASE_LOAD = "base_load_kw"
CONF_MIN_SAFE_SOC = "min_safe_soc_kwh"
CONF_BATTERY_SOC_ENTITY = "battery_soc_entity"
CONF_SOLAR_FORECAST_ENTITY = "solar_forecast_entity"
CONF_MIDPEAK_START = "midpeak_start_hour"
CONF_PEAK_START = "peak_start_hour"
CONF_PEAK_END = "peak_end_hour"
CONF_SCHEDULE_HOURS = "schedule_hours"
CONF_WEEKDAYS_ONLY = "weekdays_only"
CONF_NOTIFICATIONS_ENABLED = "notifications_enabled"
CONF_NOTIFY_ENTITY = "notify_entity"
CONF_CHARGE_THRESHOLD = "charge_threshold"
CONF_SEASONAL_PRESERVATION = "seasonal_preservation"
CONF_SEASONAL_MONTHS = "seasonal_months"
CONF_VERBOSE_LOGGING = "verbose_logging"

# --- Defaults ---
DEFAULT_BATTERY_CAPACITY = 13.0
DEFAULT_BASE_LOAD = 0.5
DEFAULT_MIN_SAFE_SOC = 2.0
DEFAULT_MIDPEAK_START = 7
DEFAULT_PEAK_START = 17
DEFAULT_PEAK_END = 21
DEFAULT_SCHEDULE_HOURS = [3, 4, 5, 6]
DEFAULT_WEEKDAYS_ONLY = True
DEFAULT_SOLAR_FORECAST_ENTITY = "sensor.solcast_pv_forecast_forecast_today"
DEFAULT_NOTIFICATIONS_ENABLED = True
DEFAULT_NOTIFY_ENTITY = ""
DEFAULT_CHARGE_THRESHOLD = 0.5
DEFAULT_SEASONAL_PRESERVATION = True
DEFAULT_SEASONAL_MONTHS = [11, 12, 1, 2, 3]
DEFAULT_VERBOSE_LOGGING = False

# --- Sensor keys ---
SENSOR_TARGET_SOC = "target_soc_kwh"
SENSOR_CHARGE_NEEDED = "charge_needed_kwh"
SENSOR_PROJECTED_MIN = "projected_minimum_kwh"
SENSOR_BATTERY_AT_PEAK = "battery_at_peak_start_kwh"

# --- Events ---
EVENT_CHARGE_START = f"{DOMAIN}_charge_start"
EVENT_CHARGE_STOP = f"{DOMAIN}_charge_stop"
EVENT_PRESERVE_START = f"{DOMAIN}_preserve_start"

# --- Services ---
SERVICE_RECALCULATE = "recalculate"
