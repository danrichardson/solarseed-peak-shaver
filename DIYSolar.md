**Title:** Solarseed Peak Shaver - Home Assistant integration for automated overnight battery charging on TOU rates

I've been working on a Home Assistant integration that automates overnight battery charging for solar + battery setups on time-of-use electricity rates. Sharing it here since it grew out of discussions on this forum.

**The problem:** Every night you have to figure out how much to charge from the grid while rates are cheap. Charge too much and you wasted money on grid power the sun would have covered. Charge too little and you're buying at 3-5x the off-peak rate during peak.

**What it does:** Reads your solar forecast (Solcast or Forecast.Solar), looks at your current battery level, and simulates hour-by-hour through peak hours to find the lowest point. If the battery would drop below your safety floor, it calculates exactly how much overnight charging you need. No more, no less.

It runs at your scheduled hours (I run 3, 4, 5, 6 AM), recalculates whenever the forecast updates, and fires events that automation blueprints pick up to control your inverter. It also handles low-solar months - after peak ends in winter, it holds the battery and draws from the grid so your stored energy is there for the next peak window.

**Sensors it creates:**

- Target SOC - what your battery should be charged to
- Charge Needed - how much to add from the grid
- Projected Minimum Battery - the lowest your battery will get during peak
- Battery at Peak Start - where you'll be when mid-peak begins
- Charge Below - how low your battery would have to be right now before charging kicks in

**What you need:**

- A battery with a kWh sensor in Home Assistant (any brand - Bluetti, Tesla, Enphase, EG4, Victron, SolarEdge, server rack, whatever)
- A solar forecast integration (Solcast or Forecast.Solar)
- TOU rates

I'm running it on a Bluetti AC500 system in Oregon on PGE's Time of Day plan. Three blueprints are included that handle the inverter commands - they work with both select and switch entities so they should adapt to most setups.

Install via HACS (custom repository for now) or manual copy. Full setup instructions in the README.

GitHub: [https://github.com/danrichardson/solarseed-peak-shaver](vscode-file://vscode-app/c:/Users/fubar/AppData/Local/Programs/Microsoft VS Code/591199df40/resources/app/out/vs/code/electron-browser/workbench/workbench.html)

Part of the Johnny Solarseed project ([https://johnnysolarseed.org](vscode-file://vscode-app/c:/Users/fubar/AppData/Local/Programs/Microsoft VS Code/591199df40/resources/app/out/vs/code/electron-browser/workbench/workbench.html)). Would love to hear if anyone tries it on a different inverter/battery combo.



HI!

I've been working on a relatively simple way to enable peak shaving for my system in Home Assistant. I created a Python script that required quite a few hoops to go through, and wasn't satisfied with it. So, I dove in an started working on my first HACS plugin - it automates overnight battery charging for solar + battery setups on time-of-use electricity rates.

Sharing it here since it grew out of discussions last year: https://diysolarforum.com/threads/using-homeassistant-for-peak-shaving.105312/

**What I was trying to solve**: Every night you have to figure out how much to charge from the grid while rates are cheap. If you charge too much and you wasted money on grid power the sun would have covered. If you charge too little and you're buying at 3-5x the off-peak rate during peak. I didn't see anything that was simple and did what I needed so I created it.

**What this does:** It reads in your solar forecast (Solcast or Forecast.Solar), looks at your current battery level, and simulates hour-by-hour through peak hours to find your battery bank's lowest SOC. If the battery would drop below your safety floor, it calculates exactly how much overnight charging you need.

It runs at your scheduled hours (I run 3, 4, 5, 6 AM), and recalculates whenever the forecast updates, and fires events that automation blueprints pick up to control your inverter. It also handles low-solar months - after peak periods (nights & weekends) any solar you get, it holds, and uses it for mid-peak and peak hours. This way you don't lose round-trip efficiency when power is cheap.

**Sensors it creates**:

\- Target SOC - what your battery should be charged to that day/period
\- Charge Needed - how much to add from the grid (to get to that SOC)
\- Projected Minimum Battery - the lowest your battery will get during peak from the simulation
\- Battery at Peak Start - where you'll be when mid-peak begins
\- Charge Below - how low your battery would have to be right now before charging is triggered

**What you need**:

\- A battery with a kWh sensor in Home Assistant (any brand should work if you can send it the signals via HA, but I've only tested my Bluetti)
\- A solar forecast integration (Solcast or Forecast.Solar)
\- TOU rates - I have 3 rates weekdays, and uniform on the weekends.

I've been running this on my Bluetti AC500 system in Oregon on PGE's Time of Day plan. Three blueprints are included that handle the inverter commands - they work with both select and switch entities and I believe they'll work for most setups. ![🫣](https://cdn.jsdelivr.net/joypixels/assets/8.0/png/unicode/64/1fae3.png)

Install via HACS (custom repository for now) or manual copy. Full setup instructions in the README. It's not officially in HACS yet because I'd like to get some testers to run it through its paces.

GitHub: https://github.com/danrichardson/solarseed-peak-shaver/tree/main

Part of the [Johnny Solarseed](https://johnnysolarseed.org/) project. Would love to hear if anyone tries it on a different inverter/battery combo!