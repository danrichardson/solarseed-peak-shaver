**Title:** Built a Home Assistant integration that automates overnight battery charging using your solar forecast (TOU rates)

If you have solar panels, a battery, and time-of-use electricity rates, you know the nightly question: *how much should I charge from the grid while it's cheap?*

Charge too much = wasted money on power the sun would've covered. Charge too little = buying at peak rates tomorrow evening.

I built a Home Assistant integration that answers this automatically. It pulls your solar forecast, looks at your current battery level, and simulates through peak hours to figure out the minimum overnight charge needed. It handles the math, monitors the battery, sends notifications, and fires events that blueprint automations use to control the inverter.

**How it works:**

- Runs at scheduled hours (default 3-6 AM) + recalculates on forecast updates
- Three-tier rate awareness: off-peak, mid-peak, peak
- Calculates the exact kWh needed - no guessing
- Monitors battery and stops charging when target is hit
- Off-peak battery hold for winter months when solar won't refill the battery
- Works with any battery reporting kWh (Bluetti, Tesla, Enphase, EG4, Victron, etc.) and any forecast integration (Solcast, Forecast.Solar)

Three automation blueprints included - import them, point them at your inverter entity, done.

I'm running it on a Bluetti AC500 in Oregon. Install via HACS (custom repo for now).

GitHub: [https://github.com/danrichardson/solarseed-peak-shaver](vscode-file://vscode-app/c:/Users/fubar/AppData/Local/Programs/Microsoft VS Code/591199df40/resources/app/out/vs/code/electron-browser/workbench/workbench.html)

Part of the [Johnny Solarseed](vscode-file://vscode-app/c:/Users/fubar/AppData/Local/Programs/Microsoft VS Code/591199df40/resources/app/out/vs/code/electron-browser/workbench/workbench.html) project. Happy to answer questions or hear how it works on different setups.