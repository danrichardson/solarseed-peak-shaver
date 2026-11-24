"""Constants for the Solarseed Peak Shaver integration."""

DOMAIN = "solarseed_peak_shaver"
NAME = "Solarseed Peak Shaver"
VERSION = "0.9.1"

# --- Config keys ---
CONF_BATTERY_CAPACITY = "battery_capacity"
CONF_BASE_LOAD = "base_load_kw"
CONF_MIN_SAFE_SOC = "min_safe_soc_kwh"
CONF_BATTERY_SOC_ENTITY = "battery_soc_entity"
CONF_SOLAR_FORECAST_ENTITY = "solar_forecast_entity"
CONF_SOLAR_ACTUAL_ENTITY = "solar_actual_entity"
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

# --- Learned planner (0.7.0). All optional; the integration behaves as before without them.
CONF_PLANNER = "planner"
CONF_GAUGE_ENTITY = "gauge_entity"
CONF_LOAD_POWER_ENTITY = "load_power_entity"
CONF_GRID_POWER_ENTITY = "grid_power_entity"
CONF_PV_POWER_ENTITY = "pv_power_entity"
CONF_SOLAR_FORECAST_TOMORROW_ENTITY = "solar_forecast_tomorrow_entity"
CONF_FULL_CHARGE_MONTHS = "full_charge_months"
CONF_LOAD_QUANTILE = "load_quantile"
CONF_SOLAR_CONFIDENCE = "solar_confidence"
CONF_GAUGE_FLOOR = "gauge_floor_pct"

# --- 0.8.0: handover cost, staleness, third-party packs. All optional.
CONF_RECOVERY_PCT = "handover_recovery_pct"
CONF_PEAK_MARGIN_KWH = "peak_margin_kwh"
CONF_STALE_MINUTES = "stale_minutes"
CONF_PACK_CURRENT_ENTITIES = "pack_current_entities"
CONF_PACK_CURRENT_CHARGE_POSITIVE = "pack_current_charge_positive"
CONF_BUS_VOLTAGE_ENTITY = "bus_voltage_entity"
CONF_PACK_CAPACITY_AH = "pack_capacity_ah"
CONF_CAPACITY_V_HIGH = "capacity_v_high"
CONF_CAPACITY_V_LOW = "capacity_v_low"

# --- 0.8.2: utility holidays (off-peak all day). Absent key = PGE, like every other default.
CONF_HOLIDAY_PRESET = "holiday_preset"

# --- 0.9.1: the tariff as data. The three hour keys above stay the base windows; absent
# keys read as PGE Time of Day, so an entry saved before 0.9.1 behaves exactly as it did.
CONF_OFFPEAK_PRICE = "offpeak_price"
CONF_MIDPEAK_PRICE = "midpeak_price"
CONF_PEAK_PRICE = "peak_price"
CONF_TARIFF_SEASONS = "tariff_seasons"
CONF_HOLIDAY_RULES = "holiday_rules"
CONF_HOLIDAY_DATES = "holiday_dates"

PLANNER_CLASSIC = "classic"
PLANNER_LEARNED = "learned"

# --- Defaults ---
DEFAULT_BATTERY_CAPACITY = 23.5
DEFAULT_BASE_LOAD = 0.6
DEFAULT_MIN_SAFE_SOC = 1.5
DEFAULT_MIDPEAK_START = 7
DEFAULT_PEAK_START = 17
DEFAULT_PEAK_END = 21
DEFAULT_SCHEDULE_HOURS = [3, 4, 5, 6]
DEFAULT_WEEKDAYS_ONLY = True
DEFAULT_SOLAR_FORECAST_ENTITY = "sensor.solcast_pv_forecast_forecast_today"
DEFAULT_SOLAR_ACTUAL_ENTITY = ""
DEFAULT_NOTIFICATIONS_ENABLED = True
DEFAULT_NOTIFY_ENTITY = ""
DEFAULT_CHARGE_THRESHOLD = 0.5
DEFAULT_SEASONAL_PRESERVATION = True
DEFAULT_SEASONAL_MONTHS = [11, 12, 1, 2, 3]
DEFAULT_VERBOSE_LOGGING = False
DEFAULT_PLANNER = PLANNER_CLASSIC
DEFAULT_FULL_CHARGE_MONTHS = [11, 12, 1]
DEFAULT_LOAD_QUANTILE = 0.8
DEFAULT_SOLAR_CONFIDENCE = 0.7
DEFAULT_GAUGE_FLOOR = 3.0
DEFAULT_RECOVERY_PCT = 10.0
DEFAULT_PEAK_MARGIN_KWH = 0.5
DEFAULT_STALE_MINUTES = 20
DEFAULT_PACK_CURRENT_CHARGE_POSITIVE = True
DEFAULT_PACK_CAPACITY_AH = 100.0
DEFAULT_CAPACITY_V_HIGH = 53.0
DEFAULT_CAPACITY_V_LOW = 51.5
DEFAULT_HOLIDAY_PRESET = "pge"
DEFAULT_OFFPEAK_PRICE = None        # PGE's was never used: the daily cost is mid-peak and peak
DEFAULT_MIDPEAK_PRICE = 0.1670      # PGE Time of Day, USD per kWh
DEFAULT_PEAK_PRICE = 0.4313
DEFAULT_TARIFF_SEASONS = ""
DEFAULT_HOLIDAY_DATES = ""

# Seconds the classic planner waits before acting on the first calculation after a start
# that wants a charge. Sensors can report a wrong value for a moment while HA loads
# (2026-11-22: the battery sensor read a numeric 0.0 for 2 s), so the charge is only
# started by a second look.
STARTUP_CONFIRM_SECONDS = 60

# --- Sensor keys ---
SENSOR_TARGET_SOC = "target_soc_kwh"
SENSOR_CHARGE_NEEDED = "charge_needed_kwh"
SENSOR_PROJECTED_MIN = "projected_minimum_kwh"
SENSOR_BATTERY_AT_PEAK = "battery_at_peak_start_kwh"
SENSOR_CHARGE_BELOW = "charge_below_kwh"

# --- Performance tracking sensor keys ---
SENSOR_DAILY_GRADE = "daily_grade"
SENSOR_SOLAR_ACCURACY = "solar_forecast_accuracy"
SENSOR_EFFECTIVE_BASE_LOAD = "effective_base_load"
SENSOR_PREDICTION_ACCURACY = "prediction_accuracy"
SENSOR_ROLLING_SCORE = "rolling_score"

# --- Learned planner sensor keys ---
SENSOR_LEARNED_ENERGY = "learned_energy_remaining"
SENSOR_LEARNED_PLAN = "learned_plan"

# --- Health sensor key (0.8.1) ---
SENSOR_HEALTH = "health"

# --- Events ---
EVENT_CHARGE_START = f"{DOMAIN}_charge_start"
EVENT_CHARGE_STOP = f"{DOMAIN}_charge_stop"
EVENT_PRESERVE_START = f"{DOMAIN}_preserve_start"

# --- Services ---
SERVICE_RECALCULATE = "recalculate"
SERVICE_PERFORMANCE_REPORT = "performance_report"
SERVICE_EXPORT_HISTORY = "export_history"
SERVICE_BACKFILL_LEARNING = "backfill_learning"
