from __future__ import annotations
import appdaemon.plugins.hass.hassapi as hass
from datetime import datetime, time
from typing import Any


class SetTargetSOC(hass.Hass):
    """AppDaemon app to calculate target SOC based on TOU rates and forecast."""

    # ---------------------------------------------------------------------
    def initialize(self) -> None:
        """Set up scheduled and event-based triggers."""
        self.log("SetTargetSOC initialized.")

        # Run hourly at 03:00, 04:00, 05:00, 06:00 (Mon–Fri)
        for hour in [3, 4, 5, 6]:
            self.run_daily(self.calculate_target_soc_if_weekday, time(hour, 0, 0))

        # Trigger when Solcast forecast updates
        self.listen_state(
            self.on_solcast_update,
            "sensor.solcast_pv_forecast_forecast_today",
        )

        # Run once after startup (comment out in production)
        # self.run_in(self.calculate_target_soc_if_weekday, 10)

    # ---------------------------------------------------------------------
    @staticmethod
    def safe_float(value: Any, default: float = 0.0) -> float:
        """Convert Home Assistant state or object to float safely."""
        try:
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                return float(value.strip())
        except (ValueError, TypeError):
            pass
        return float(default)

    # ---------------------------------------------------------------------
    def is_weekday(self) -> bool:
        """Return True if today is Monday–Friday."""
        return datetime.now().weekday() < 5  # Monday = 0, Sunday = 6

    # ---------------------------------------------------------------------
    def on_solcast_update(
        self,
        entity: str,
        attribute: str,
        old: Any,
        new: Any,
        **kwargs: Any,
    ) -> None:
        """Handle Solcast forecast updates."""
        now = datetime.now().time()
        start_time = time(3, 0)  # 3:00 AM
        end_time = time(17, 0)  # 5:00 PM

        """Handle Solcast forecast updates."""
        if not self.is_weekday():
            self.log("Solcast update ignored (weekend).")
            return

        if not (start_time <= now <= end_time):
            self.log("Solcast update ignored (outside 3AM–5PM window).")
            return

        self.log(f"Solcast forecast updated: {entity}")
        self.calculate_target_soc()

    # ---------------------------------------------------------------------
    def calculate_target_soc_if_weekday(self, **kwargs: Any) -> None:
        """Run the calculation only on weekdays."""
        # self.calculate_target_soc()
        if self.is_weekday():
            self.calculate_target_soc()
        else:
            self.log("Skipped SOC calculation (weekend).")

    # ---------------------------------------------------------------------
    def calculate_target_soc(self, **kwargs: Any) -> None:
        """Perform the target SOC calculation and update input_numbers."""
        # --- Configurable constants ---
        battery_capacity: float = 23.5
        load_kw: float = 0.6  # Base load per hour
        min_safe_soc: float = 3.2  # 15% threshold (includes safety buffer)

        # Rate periods (hours)
        mid_peak_start: int = 7  # Mid-peak starts at 7am
        peak_end: int = 21  # Peak ends at 9pm (21:00)

        # --- Fetch current state ---
        current_soc: float = self.safe_float(
            self.get_state("sensor.available_battery_kwh")
        )

        # --- Get Solcast hourly forecast ---
        forecast_entity = "sensor.solcast_pv_forecast_forecast_today"
        forecast_data = self.get_state(forecast_entity, attribute="detailedHourly")

        if not forecast_data:
            self.log("ERROR: Could not retrieve Solcast hourly forecast data")
            return

        # --- Current time ---
        now = datetime.now()
        current_hour: int = now.hour

        # --- Parse hourly forecast into dictionary ---
        hourly_solar = {}
        for entry in forecast_data:
            if not isinstance(entry, dict):
                continue
            period_start = entry.get("period_start", "")
            pv_estimate = self.safe_float(entry.get("pv_estimate", 0))

            # Extract hour from period_start (format: "2025-10-24T10:00:00-07:00")
            if isinstance(period_start, str):
                try:
                    dt = datetime.fromisoformat(period_start)
                    hourly_solar[dt.hour] = pv_estimate
                except (ValueError, AttributeError):
                    continue

        # --- Print solar forecast for Excel (tab-separated) ---
        self.log("=== SOLAR FORECAST FOR EXCEL (copy/paste) ===")
        self.log("Hour\tSolar_kWh")
        for hour in range(0, 24):
            solar = hourly_solar.get(hour, 0.0)
            self.log(f"{hour}\t{solar:.4f}")
        self.log("=== END SOLAR FORECAST ===")
        self.log("")

        # --- Calculate drain from now until 7am (if in off-peak period) ---
        battery_at_7am: float = current_soc
        simulation_start_hour: int = mid_peak_start  # Default to 7am

        if current_hour < mid_peak_start:
            # Before 7am - calculate drain until 7am
            hours_until_7am: float = mid_peak_start - current_hour
            overnight_drain: float = hours_until_7am * load_kw
            battery_at_7am = current_soc - overnight_drain
            self.log(f"Current hour: {current_hour}:00")
            self.log(f"Hours until 7am: {hours_until_7am}")
            self.log(f"Overnight drain: {overnight_drain:.2f} kWh")
            self.log(f"Projected battery at 7am: {battery_at_7am:.2f} kWh")
            simulation_start_hour = mid_peak_start
        elif current_hour >= peak_end:
            # After 9pm - calculate drain until 7am next day
            hours_until_midnight: float = 24 - current_hour
            hours_after_midnight: float = mid_peak_start
            hours_until_7am = hours_until_midnight + hours_after_midnight
            overnight_drain = hours_until_7am * load_kw
            battery_at_7am = current_soc - overnight_drain
            self.log(f"Current hour: {current_hour}:00")
            self.log(f"Hours until 7am (next day): {hours_until_7am}")
            self.log(f"Overnight drain: {overnight_drain:.2f} kWh")
            self.log(f"Projected battery at 7am: {battery_at_7am:.2f} kWh")
            simulation_start_hour = mid_peak_start
        else:
            # Between 7am-9pm, start simulation from current hour
            battery_at_7am = current_soc
            simulation_start_hour = current_hour
            self.log(f"Current hour: {current_hour}:00 (during rate period)")
            self.log(f"Current battery: {current_soc:.2f} kWh")
            self.log(f"Simulating from current hour to 9pm")

        self.log("")

        # --- Simulate battery levels from simulation start to 9pm ---
        self.log(f"--- Hourly Analysis ({simulation_start_hour}:00-9pm) ---")

        battery_level: float = battery_at_7am
        min_battery_seen: float = battery_level

        for hour in range(simulation_start_hour, peak_end):
            solar_kwh: float = hourly_solar.get(hour, 0.0)
            net_change: float = solar_kwh - load_kw
            battery_level += net_change

            if battery_level < min_battery_seen:
                min_battery_seen = battery_level

            period_name = "MID" if hour < 17 else "PEAK"
            self.log(
                f"  {hour:02d}:00 [{period_name}] - "
                f"Solar: {solar_kwh:.3f} kWh, Load: {load_kw:.3f} kWh, "
                f"Net: {net_change:+.3f} kWh, Battery: {battery_level:.2f} kWh"
            )

        # --- Calculate target SOC ---
        self.log("--- Target SOC Calculation ---")
        self.log(f"Current SOC: {current_soc:.2f} kWh")

        if simulation_start_hour == mid_peak_start:
            self.log(f"Battery at 7am: {battery_at_7am:.2f} kWh")

        self.log(f"Minimum battery during simulation: {min_battery_seen:.2f} kWh")
        self.log(f"Safe minimum threshold: {min_safe_soc:.2f} kWh")

        # If minimum battery level would drop below safe threshold, calculate deficit
        if min_battery_seen < min_safe_soc:
            deficit: float = min_safe_soc - min_battery_seen
            target_soc: float = current_soc + deficit
            self.log(f"DEFICIT DETECTED: Need {deficit:.2f} kWh more")
        else:
            target_soc = current_soc
            self.log(
                f"Battery remains safe through end of day - no additional charge needed"
            )

        # Cap at battery capacity
        target_soc = min(target_soc, battery_capacity)
        charge_needed: float = max(target_soc - current_soc, 0.0)

        self.log(f"Target SOC: {target_soc:.2f} kWh")
        self.log(f"Charge needed: {charge_needed:.2f} kWh")

        # --- Output results to Home Assistant ---
        self.call_service(
            "input_number/set_value",
            entity_id="input_number.target_soc_kwh",
            value=round(target_soc, 1),
        )
        self.call_service(
            "input_number/set_value",
            entity_id="input_number.charge_needed",
            value=round(charge_needed, 1),
        )

        self.log("Target SOC updated successfully.")
