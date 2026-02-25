# SetTargetSOC - Battery Charge Optimization for TOU Rate Avoidance

*AppDaemon script for Home Assistant. Part of the Johnny Solarseed / Portland house solar system.*

------

## Purpose

Calculates how much battery charge is needed overnight (off-peak) to survive through the peak rate window (5-9pm) without drawing from the grid. Uses Solcast solar production forecasts to predict how much solar energy will be available during the day, then determines the minimum charge target.

## How It Works

1. **Runs automatically** at 3am, 4am, 5am, and 6am on weekdays, and whenever the Solcast forecast updates (between 3am-5pm).
2. **Fetches current battery level** from `sensor.available_battery_kwh`.
3. **Gets hourly solar forecast** from Solcast integration.
4. **Simulates the day in two phases:**
   - **Mid-peak (7am-5pm):** Solar production vs. base load (0.6 kW/hr). Battery charges from solar surplus, drains from deficit.
   - **Peak (5pm-9pm):** Continues simulation through the expensive window. Tracks the minimum battery level during this critical period.
5. **Calculates target SOC:** If the simulated minimum battery during peak would drop below the safe threshold (3.2 kWh + 1.0 kWh safety margin = 4.2 kWh effective), it calculates the deficit and sets a charge target.
6. **Outputs to Home Assistant** via `input_number.target_soc_kwh` and `input_number.charge_needed`.

## Key Parameters

| Parameter              | Value     | Notes                                 |
| ---------------------- | --------- | ------------------------------------- |
| Battery capacity       | 23.5 kWh  | Total usable capacity                 |
| Base load              | 0.6 kW/hr | Assumed constant household draw       |
| Min safe SOC           | 3.2 kWh   | ~15% threshold with safety buffer     |
| Forecast safety margin | 1.0 kWh   | Extra buffer for forecast uncertainty |
| Mid-peak start         | 7:00 AM   | PGE TOU mid-peak begins               |
| Peak start             | 5:00 PM   | PGE TOU peak begins                   |
| Peak end               | 9:00 PM   | PGE TOU peak ends                     |

## TOU Rate Periods (PGE Oregon)

- **Off-peak:** 9pm - 7am (cheapest - this is when charging happens)
- **Mid-peak:** 7am - 5pm (moderate - solar production offsets most usage)
- **Peak:** 5pm - 9pm (most expensive - goal is zero grid draw)

## Dependencies

- **Solcast integration** (`sensor.solcast_pv_forecast_forecast_today`) for hourly solar forecasts.
- **Battery sensor** (`sensor.available_battery_kwh`) for current charge level.
- **Input numbers** (`input_number.target_soc_kwh`, `input_number.charge_needed`) for output.
- Runs as an AppDaemon app (not a native HA integration).

## Weekday-Only Logic

The script only runs Monday-Friday. PGE TOU rates in Oregon only apply on weekdays - weekends and holidays are off-peak all day.

## Logging

Outputs detailed hourly simulation to the AppDaemon log, including a tab-separated solar forecast table that can be copy/pasted into Excel for analysis.

## Future Considerations

- This script is related to the "peak shaver vs. TOU metering" question from the 2/23 brain dump. Peak shaving (reducing demand spikes in kW) and TOU optimization (shifting consumption to cheaper time windows) are related but distinct - this script primarily does TOU optimization.
- Charging plan improvement: start logging actual vs. predicted values to refine the algorithm over time (action item from 2/23).
- Consider converting from AppDaemon to a native Home Assistant integration (part of the HACS plugin development work).
- Security sweep on all calculator code and dependencies is an outstanding action item.

## Source

```
File: set_target_soc.py
Platform: AppDaemon for Home Assistant
```

Full source code is attached in the original document.