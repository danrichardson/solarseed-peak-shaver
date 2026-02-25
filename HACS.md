## 1. HACS Default Repository Submission

To get into the HACS default list, you submit a PR to the [hacs/default](vscode-file://vscode-app/c:/Users/fubar/AppData/Local/Programs/Microsoft VS Code/591199df40/resources/app/out/vs/code/electron-browser/workbench/workbench.html) repo. You'd add your repo URL to the `integration` file alphabetically. But before you submit, there are two prerequisites:

- **HACS Action** must pass on your repo (a GitHub Action that validates HACS compatibility)
- **Your integration should be added to [home-assistant/brands](vscode-file://vscode-app/c:/Users/fubar/AppData/Local/Programs/Microsoft VS Code/591199df40/resources/app/out/vs/code/electron-browser/workbench/workbench.html)** - this is required for the icon/logo in the HA UI

The PR template will ask you to fill in details. Here's what you'd write:

**Repository:** `https://github.com/danrichardson/solarseed-peak-shaver`

**Description (for the PR):**

> Solarseed Peak Shaver calculates optimal overnight battery charging for solar + battery systems on time-of-use electricity rates. It reads the solar forecast, simulates battery levels through peak hours, and determines exactly how much grid charging is needed - so users don't overpay at peak rates or waste money charging more than necessary.
>
> Features: forecast-driven charging at scheduled hours, three-tier rate awareness (off-peak/mid-peak/peak), battery SOC monitoring with automatic stop, off-peak battery hold for low-solar months, on-demand recalculation, notifications, diagnostics, and three automation blueprints for inverter control.
>
> Works with any battery system reporting energy in kWh and any solar forecast integration (Solcast, Forecast.Solar). Developed and tested on a Bluetti AC500 system in Oregon.
>
> Part of the [Johnny Solarseed](vscode-file://vscode-app/c:/Users/fubar/AppData/Local/Programs/Microsoft VS Code/591199df40/resources/app/out/vs/code/electron-browser/workbench/workbench.html) project.