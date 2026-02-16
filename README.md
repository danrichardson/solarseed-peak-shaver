# [Solarseed](https://johnnysolarseed.org) Peak Shaver

**A Home Assistant integration for solar + battery peak shaving.**

If you have solar panels, a battery, and time-of-use electricity rates, this integration figures out how much to charge your battery overnight so you can ride through the expensive hours on solar and stored energy - instead of paying peak rates to the grid.

## The problem it solves

You're on TOU rates. You have solar and a battery. Every night you face the same question: *how much should I charge from the grid while rates are cheap, so I don't get caught buying power at peak prices tomorrow?*

Charge too much and you wasted money on grid power you didn't need - the sun would have covered it. Charge too little and you're buying power at 3-5x the off-peak rate during the evening peak.

The Peak Shaver answers that question automatically, every night, using your solar forecast. It handles the calculations, monitors your battery, sends you notifications, and tells your inverter what to do - through automation blueprints you configure once.

## How it works

1. Runs at your scheduled hours (default: 3, 4, 5, 6 AM) and whenever the solar forecast updates
2. Reads your current battery level and the hourly solar production forecast
3. Projects your battery level at mid-peak start, accounting for overnight drain
4. Simulates hour-by-hour through mid-peak and peak: solar production minus your base load
5. Finds the lowest point - if the battery would drop below your safety floor, calculates exactly how much more charge you need
6. Fires an event to start grid charging (or confirms no charging is needed)
7. Monitors the battery and fires a stop event when the target is reached
8. Sends you notifications at each step (if enabled)

### Three-tier rate awareness

The shaver understands three rate periods: off-peak, mid-peak, and peak. This matters because if there's going to be a deficit during peak, it's better to charge during mid-peak at a moderate rate than to buy power at full peak pricing. The forecast recalculation window runs from your overnight schedule hours through peak start - so a forecast update during mid-peak can still trigger a charge decision before the most expensive hours hit.

For PGE's Time of Day plan as an example: off-peak is $0.09/kWh (overnight/weekends), mid-peak is $0.18/kWh (7 AM - 5 PM weekdays), and peak is $0.44/kWh (5 PM - 9 PM weekdays).

### Seasonal preservation

During low-solar months (configurable, default Nov-March), the integration fires a preservation event at the end of peak hours. The idea: in winter, your solar won't replenish the battery tomorrow, so it's better to hold what you have overnight and charge from cheap off-peak grid power in the early morning rather than letting the battery drain to nothing. The next morning's calculation run takes over from there.

## What you need

- **A battery system** with a Home Assistant sensor reporting available energy in kWh (any brand - Bluetti, Tesla, Enphase, EG4, Victron, SolarEdge, DIY server rack, whatever)
- **A solar forecast integration** - [Solcast](https://github.com/BJReplay/ha-solcast-solar) or [Forecast.Solar](https://www.home-assistant.io/integrations/forecast_solar/) with hourly data
- **Time-of-use electricity rates** where peak hours cost more than off-peak

## Installation

### HACS (recommended)

1. Open HACS in Home Assistant
2. Three-dot menu > **Custom repositories**
3. Add `https://github.com/danrichardson/solarseed-peak-shaver` as an **Integration**
4. Search for "Solarseed Peak Shaver" and install
5. Restart Home Assistant
6. **Settings > Devices & Services > Add Integration** > search "Solarseed"

### Manual

Copy `custom_components/solarseed_peak_shaver` into your Home Assistant `config/custom_components/` directory. Copy the `blueprints` folder into your Home Assistant `config/blueprints/` directory. Restart.

## Setup

### Step 1: Integration config (3 screens)

The config wizard walks you through three screens:

**Screen 1 - Battery & Solar**

| Setting | What it means | Example |
|---------|--------------|---------|
| Battery SOC sensor | Sensor reporting your available battery energy in kWh | `sensor.available_battery_kwh` |
| Solar forecast sensor | Your Solcast or Forecast.Solar entity | `sensor.solcast_pv_forecast_forecast_today` |
| Battery capacity | Total usable storage in your system | 13 kWh |
| Base load | Your average hourly draw during a normal day | 0.5 kW |
| Minimum safe SOC | The battery floor you never want to hit | 2.0 kWh |

**Screen 2 - Rate Schedule**

| Setting | What it means | Default |
|---------|--------------|---------|
| Mid-peak start | When mid-peak rates begin | 7 (7 AM) |
| Peak start | When the most expensive rates begin | 17 (5 PM) |
| Peak end | When peak rates end | 21 (9 PM) |
| Weekdays only | Most TOU plans are weekday-only | Yes |
| Calculation hours | When to run the overnight math | 3,4,5,6 |

**Screen 3 - Notifications & Seasonal**

| Setting | What it means | Default |
|---------|--------------|---------|
| Enable notifications | Send notifications when charging decisions are made | Yes |
| Notification service | Your notify target, e.g. `notify.mobile_app_yourphone` | (empty) |
| Minimum charge to act on | Ignore charge amounts below this | 0.5 kWh |
| Seasonal preservation | Preserve battery overnight during low-solar months | Yes |
| Preservation months | Which months to activate preservation | 11,12,1,2,3 |

All settings can be changed later through the integration's **Configure** button.

### Step 2: Import the blueprints

The integration tells your battery *what* to do. The blueprints tell your inverter *how* to do it. Go to **Settings > Automations & Scenes > Blueprints** and import the three blueprints from the repo. Each one asks for just two things: your inverter's mode entity and the value to set.

**Solarseed - Start Grid Charging**

Fires when charging is needed. Configure with:
- Your inverter mode entity (e.g. `select.ac500_ups_mode`)
- The grid charging value (e.g. `STANDARD`)

**Solarseed - Stop Charging / Solar Priority**

Fires when the battery reaches target or no charging is needed. Configure with:
- Your inverter mode entity
- The solar priority value (e.g. `PV_PRIORITY`)

**Solarseed - Seasonal Preservation**

Fires at end of peak during configured winter months. Configure with:
- Your inverter mode entity
- The preservation value (e.g. `TIME_CONTROL`)

The blueprints handle both `select` and `switch` entity types automatically.

## Sensors

The integration creates four sensors under a "Solarseed Peak Shaver" device:

| Sensor | What it tells you |
|--------|-------------------|
| **Target SOC** | How much energy your battery should have (kWh) |
| **Charge Needed** | How much to add from the grid overnight (kWh) |
| **Projected Minimum Battery** | The lowest your battery will get during the rate window |
| **Battery at Peak Start** | Where your battery will be when mid-peak rates begin |

## On-demand recalculation

You don't have to wait for the next scheduled run. There are two ways to trigger the calculation immediately:

**Button entity** - A "Recalculate" button is created under the Solarseed Peak Shaver device. Press it from the dashboard, an automation, or the entity page. You'll find it at `button.solarseed_peak_shaver_recalculate`.

**Service call** - Call `solarseed_peak_shaver.recalculate` from Developer Tools > Services, scripts, or automations. No parameters needed.

Both methods run the full calculation, update all sensors, and fire events exactly as a scheduled run would.

## Events

The integration fires these events on the Home Assistant event bus. The blueprints listen for them, but you can also use them in your own automations.

| Event | When | Data |
|-------|------|------|
| `solarseed_peak_shaver_charge_start` | Charging is needed | current_soc, target_soc, charge_needed, solar_forecast |
| `solarseed_peak_shaver_charge_stop` | Target reached or no charging needed | current_soc, target_soc |
| `solarseed_peak_shaver_preserve_start` | Seasonal preservation triggered | current_soc, month |

## Background

Discussion and development history on the [DIY Solar Power Forum](https://diysolarforum.com/threads/using-homeassistant-for-peak-shaving.105312/).

Part of the [Johnny Solarseed](https://johnnysolarseed.org) project - teaching Oregon homeowners to build and manage their own solar systems.

## License

MIT

## Contributing

Issues and PRs welcome. If you're running this on a different inverter/battery combo, I'd love to hear how it works for you.
