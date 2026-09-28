# Jonah Saunders Bandgap

A GF180MCU bandgap voltage reference with a startup circuit, a seven-bit physical resistor-trim network, and ten Xschem/ngspice testbenches.

## Projected post-trim specifications

**Current pre-layout simulations support a reference near 1.18 V with a post-trim temperature-coefficient goal of ≤10 ppm/°C.** The calibration objective is minimum temperature drift: select one physical resistor-trim code for each chip using measurements at multiple temperatures, then hold it fixed across temperature and supply. **1.18 V is the nominal voltage goal, not an exact voltage that the calibration must force.**

The table distinguishes results from the physical trim core from earlier untrimmed-core measurements. Goals remain provisional until mismatch, remaining functional checks, and extracted-layout verification are complete.

| Parameter | Projected goal / operating condition | Simulation evidence available |
| --- | --- | --- |
| Reference voltage | **Approximately 1.18 V nominal** | **1.18425 V** at the typical process, 25 °C / 3.3 V, after selecting the code for minimum drift |
| Initial output accuracy | **±1% of 1.18 V** at 25 °C / 3.3 V; voltage is secondary to minimum drift | **1.17384-1.18927 V** across 45 fixed process combinations; mismatch coverage pending |
| Output accuracy across supply and temperature | **±1% of 1.18 V**: 1.1682-1.1918 V | **1.17378-1.18945 V** across the selected dense curves at 3.3 V and 5 V; intermediate supplies and mismatch pending |
| Analog supply, AVDD | **3.3-5.0 V**; 3.0 V remains a characterization goal | New trimmed-core temperature data covers the two nominal endpoints |
| Trim logic supply, DVDD | **3.3 V** | Held at 3.3 V throughout the trim screen |
| Temperature range | **−40 to 125 °C** | Verified at **1 °C steps** for the selected codes and neighboring candidates |
| Temperature coefficient | **≤10 ppm/°C** after calibration for minimum drift | **2.54 ppm/°C typical**, **2.99 ppm/°C median**, **5.28 ppm/°C worst** across the 45 process combinations and both supplies |
| Quiescent analog supply current | Approximately **30 µA typical**, **≤60 µA maximum**; DVDD current separate | **54.42 µA maximum** in the new selected-code temperature sweeps |
| Line regulation | **≤0.1% total VREF change** across 3.3-5.0 V at fixed temperature and code | **0.0616%** worst in the earlier untrimmed-core nominal-supply sweeps; a complete sweep at the new trim codes remains pending |
| Power-supply rejection | **≥55 dB at 1 kHz**, **≥45 dB throughout 1 Hz-1 MHz** | Earlier untrimmed-core minimum over the band: **47.8 dB**; trimmed-core verification pending |
| Output noise density | **≤3,000 nV/√Hz at 1 kHz** | Earlier untrimmed-core data informed this budget; trimmed-core verification pending |
| Integrated output noise | **≤100 µV RMS over 0.1-10 Hz** | Earlier untrimmed-core result: **52-77 µV RMS**; trimmed-core verification pending |
| Startup / restart readiness | Enter and remain within the reference tolerance **within 300 µs after the supply ramp** | New temperature screen is DC only; startup at the selected codes and unresolved transient cases remain pending |
| Trim control | **7 bits / 128 codes**, calibrated once and held fixed | Selected codes **65-98** in the new fixed-corner screen |

**Additional proposal goals without supporting measurements:** load regulation **≤1%** after an output-load range is defined, and a **220 nA nominal PTAT output current** after its measurement conditions are defined.

### Temperature-trim results — September 28, 2026

The new screen covers **45 process combinations** (5 MOS × 3 BJT × 3 resistor, with typical MIM), **−40 to 125 °C**, **3.3 V and 5 V AVDD**, and **3.3 V DVDD**. All 128 codes were first compared at −40, 25 and 125 °C. The best sampled code and its two neighbors were then checked at 1 °C steps: **135/135 candidate jobs completed**, producing **44,820 DC sample points**. The selected code is held across both supplies and all temperatures for each process combination. All **14,940 selected-code operating points** meet the existing self-sustaining DC current checks.

[![Temperature drift and resulting output voltage after calibration for minimum drift](docs/results/trim-temperature-2026-09-28/temperature_drift_after_trim.png)](docs/results/trim-temperature-2026-09-28/temperature_drift_after_trim.png)

The left chart shows drift relative to each curve's own 25 °C output. The right chart shows the voltage tradeoff: each dot is one process combination, with its worst temperature coefficient across the two supplies. The corner previously giving **65.5 ppm/°C** when calibrated toward 1.200 V now gives **3.28 ppm/°C** with a different code. That earlier figure used only three temperatures; the new results use the dense sweep.

**These results support the revised goals; they are not a silicon guarantee or complete layout signoff.** A real chip needs calibration at multiple temperatures to select its minimum-drift code. Random mismatch, trimmed-core startup/restart, PSRR, noise, stability, and extracted-layout behavior remain to be qualified. These DC checks do not resolve the known transient simulator aborts.

[Result details and method](docs/results/trim-temperature-2026-09-28/README.md) · [Selected codes and metrics (CSV)](docs/results/trim-temperature-2026-09-28/selected_codes.csv) · [Full selected temperature curves (CSV)](docs/results/trim-temperature-2026-09-28/selected_curves.csv)


## Current testbench acceptance targets

The standard runner retains its existing **1.194 V** voltage-calibration criterion at **3.3 V / 25 °C** and the acceptance targets below. The revised project goal is **approximately 1.18 V with calibration for minimum temperature drift**. The published temperature-trim results come from the separate analysis linked above; updating this goal does not change the runner's settings or reclassify historical results. Simply changing its voltage target to 1.18 V would not implement minimum-drift calibration.

| Parameter | Goal / operating condition |
| --- | --- |
| Reference voltage | **1.194 V ±0.5%** after trim |
| Analog supply, AVDD | **3.3-5.0 V** |
| Trim logic supply, DVDD | **3.3 V** |
| Temperature range | **−40 to 125 °C** |
| Temperature coefficient | **≤10 ppm/°C** across the temperature range |
| Power-supply rejection | **≥60 dB**, 1 Hz-1 MHz |
| Quiescent analog supply current | **≤60 µA** |
| Startup / restart readiness | Reach and remain within the reference tolerance **within 300 µs after the supply ramp** |
| Disturbance recovery | Return to the reference tolerance **within 300 µs**, staying in range through the 2 ms observation window |
| Trim control | **7 bits / 128 codes**; `b0` is the LSB; logic 1 bypasses a resistor segment |

The full test profile also includes **3.0 V and 5.5 V stress points**, reported separately from the nominal range. The runner characterizes line regulation and output noise without enforcing the projected line-regulation and noise budgets above.

**Current verification scope:** TB01-TB09 characterize the untrimmed core or its loop-probe variant. TB10 exercises the physical resistor-trim core. The separate temperature-trim screen above adds dense fixed-corner DC coverage at the two nominal supply endpoints. Full trimmed-core qualification still needs mismatch, broader supply coverage, startup/restart at the selected codes, PSRR, noise, and stability checks. See [validation notes](VALIDATION.md) for the checks completed so far.

## Schematics

### Bandgap core

The repaired core includes the reference, startup circuits, folded-cascode amplifier, bias network, and internal output capacitors.

[![Untrimmed bandgap core schematic](docs/images/bandgap-core.svg)](docs/images/bandgap-core.svg)

[View full-size image](docs/images/bandgap-core.svg) · [Open Xschem source](Bandgap_Core.sch)

### Core with resistor trim

The trim version adds the physical resistor segments, bypass switches, and seven-bit control circuitry. This is the intended core for the trimmed-reference layout.

[![Bandgap core with physical seven-bit resistor trim](docs/images/bandgap-core-resistor-trim.svg)](docs/images/bandgap-core-resistor-trim.svg)

[View full-size image](docs/images/bandgap-core-resistor-trim.svg) · [Open Xschem source](Bandgap_Core_Res.sch)

Both images are exported from the checked-in schematics. Click an image to inspect device labels and connections at full size.

## Installation and first run

### 1. Open the simulation environment

Use **Bash inside Linux/FOSS**, with Python 3.9+, Xschem, ngspice, and the GF180 symbol/model libraries installed. The runner uses POSIX file locks and does not run directly in Windows PowerShell. The PDK is installed separately.

In IIC-OSIC-TOOLS, use the full PDK selector in the same terminal before opening Xschem:

```bash
source /foss/tools/sak/sak-pdk-script.sh gf180mcuD
command -v python3 xschem ngspice
```

This sets `PDK`, `PDKPATH`, and ngspice startup settings together. The interactive alias is `sak-pdk gf180mcuD`; sourcing its script also works in Bash scripts. Repeat the selection in each new terminal.

The testbench model paths assume `/foss/pdks/gf180mcuD/libs.tech/ngspice/`. If your PDK is elsewhere, update each bench's `MODELS` paths before netlisting.

### 2. Get the project and Python dependencies

```bash
cd /foss/designs
git clone https://github.com/jonahsaunders/jonah_saunders_bandgap.git
cd jonah_saunders_bandgap

python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 verify_suite.py
```

For an existing checkout, start in its repository folder. When reviewing an unmerged branch, switch to that branch before installation. Keep the core `.sch`/`.sym` files, benches, scripts, and `bandgap_config.json` together. The virtual environment is optional if NumPy and Matplotlib are already installed. Software checks do not simulate the circuit.

### 3. Configure the Xschem launchers

Close open testbenches, then run:

```bash
NETLIST_DIR="/headless/.xschem/simulations"
mkdir -p "$NETLIST_DIR"
python3 run_bandgap.py --configure --netlist-dir "$NETLIST_DIR"
```

Use your actual Xschem netlist directory. Reopen the benches afterward. Repeat this step after moving the repository; it updates launcher paths, not core circuitry or PDK model paths.

### 4. Run a smoke check

Generate TB01's netlist, run its short profile, and plot the results:

```bash
source /foss/tools/sak/sak-pdk-script.sh gf180mcuD
NETLIST_DIR="${NETLIST_DIR:-/headless/.xschem/simulations}"
mkdir -p "$NETLIST_DIR"
xschem -n -x -q -r -s -o "$NETLIST_DIR" \
  -N TB01_PSRR.spice TB01_PSRR.sch

python3 run_bandgap.py --test TB01_PSRR \
  --deck "$NETLIST_DIR/TB01_PSRR.spice" --profile smoke

python3 plot_bandgap.py --profile smoke --test TB01_PSRR
```

Check for missing-symbol or netlisting errors before running the Python command. The report is `results/smoke/TB01_PSRR_UPLOAD_THIS.txt`; plots are in `results/smoke/plots/`. Regenerate the matching netlist whenever its schematic changes.

For GUI runs, select GF180 and open a bench from that same terminal. Relaunch any Xschem window that previously loaded another PDK. Then click **Netlist**, then **Simulate**. Each schematic runs only its own bench. GUI profiles come from `bandgap_config.json`; the supplied defaults select **full**, including TB10. A terminal `--profile smoke` command does not change those defaults.

For the full-suite command, profile settings, troubleshooting, and **rerunning selected cases without replacing old results**, use the [simulation guide](docs/SIMULATION_GUIDE.md).

## Testbenches

Each bench produces its own `TBxx_NAME_UPLOAD_THIS.txt` report, case data, and plots. Simulation completion and meeting the specification are reported separately.

The full deterministic grid uses **135 process combinations**: 5 MOS × 3 BJT × 3 resistor × 3 MIM corners. Discrete checks use −40, 25, and 125 °C at seven supplies from 3.0 to 5.5 V. TB06 uses statistical model draws instead of this fixed-corner grid.

| Bench | Circuit under test | Full profile | Smoke profile |
| --- | --- | ---: | ---: |
| [TB01: PSRR](#tb01-psrr) | Untrimmed core | 2,835 cases | 1 case |
| [TB02: Line regulation](#tb02-line-regulation) | Untrimmed core | 405 sweeps | 1 sweep |
| [TB03: Startup and restart](#tb03-startup-and-restart) | Untrimmed core | 2,835 cases | 1 case |
| [TB04: Temperature](#tb04-temperature) | Untrimmed core | 945 sweeps | 1 sweep |
| [TB05: Loop stability](#tb05-loop-stability) | Repaired untrimmed probe core | 2,835 cases | 1 case |
| [TB06: Monte Carlo](#tb06-monte-carlo) | Untrimmed core | 6,300 cases | 3 cases |
| [TB07: Noise](#tb07-noise) | Untrimmed core | 2,835 cases | 1 case |
| [TB08: Power and device limits](#tb08-power-and-device-limits) | Untrimmed core | 2,835 cases | 1 case |
| [TB09: Supply disturbances](#tb09-supply-disturbances) | Untrimmed core | 33,210 cases | 5 cases |
| [TB10: Resistor trim](#tb10-resistor-trim) | Physical resistor-trim core | 405 bundles | 1 bundle |

### TB01: PSRR

[TB01_PSRR.sch](TB01_PSRR.sch) measures supply-to-reference coupling with an AC sweep from 1 Hz to 100 MHz. It reports PSRR at selected frequencies and the worst rejection over the **1 Hz-1 MHz specification band**. Passing requires at least 60 dB throughout that band and a valid DC reference.

### TB02: Line regulation

[TB02_LINE_REGULATION.sch](TB02_LINE_REGULATION.sch) sweeps AVDD from 3.0 to 5.5 V in 10 mV steps. It reports reference span, endpoint and local slopes, current, and absolute accuracy, with separate results for the **nominal 3.3-5 V range** and the full stress sweep.

### TB03: Startup and restart

[TB03_STARTUP_RESTART.sch](TB03_STARTUP_RESTART.sch) checks cold start, supply shutdown, and analog restart using the core's real startup circuit. It records settling, overshoot, final reference, and supply current. Readiness uses the absolute reference tolerance and the **300 µs deadline after each ramp**.

### TB04: Temperature

[TB04_TEMPERATURE.sch](TB04_TEMPERATURE.sch) sweeps **−40 to 125 °C in 1 °C steps** at each supply and process combination. It measures reference drift, box temperature coefficient, accuracy, and current. The TC target is 10 ppm/°C; this bench currently measures the untrimmed core.

### TB05: Loop stability

[TB05_LOOP_STABILITY.sch](TB05_LOOP_STABILITY.sch) measures the MAIN and BIAS feedback loops through the repaired [loop-probe core](Bandgap_Core_LoopProbe.sch). Each cut is measured with the other loop closed; outputs include return-ratio curves, crossing information, conditional margins, and DC continuity checks. Regenerate the netlist after the probe repair: old TB05 results do not describe the new core. This probe follows `Bandgap_Core.sch`, not the resistor-trim variant.

### TB06: Monte Carlo

[TB06_MONTE_CARLO.sch](TB06_MONTE_CARLO.sch) uses the installed PDK's global, mismatch, and combined statistical models to measure DC reference accuracy and current. The full run reuses **100 seeds per mode across 21 supply/temperature points**. Required output correction is reported to help assess trim range; it does not simulate physical trim or establish post-trim yield.

### TB07: Noise

[TB07_NOISE.sch](TB07_NOISE.sch) measures output noise density from 0.1 Hz to 100 MHz and integrates RMS noise over **0.1-10 Hz** and **1 Hz-1 MHz**. Operating points outside the accuracy target are marked separately. No numerical noise pass/fail budget is currently assigned.

### TB08: Power and device limits

[TB08_POWER_DEVICE_LIMITS.sch](TB08_POWER_DEVICE_LIMITS.sch) measures quiescent current/power, MOS terminal voltages, and saturation headroom at DC and during startup. The current target is **60 µA**. Device voltage thresholds are configurable screens; nominal and stress results are separated, and the screens are not foundry reliability signoff.

### TB09: Supply disturbances

[TB09_SUPPLY_DISTURBANCE.sch](TB09_SUPPLY_DISTURBANCE.sch) exercises slow/fast ramps, brownouts, repeated interruptions, and supply steps. Recovery must enter the absolute reference band within **300 µs** and remain there through the **2 ms observation window**. The bench records recovery time, excursions, and peak current without forcing the reference node to discharge.

### TB10: Resistor trim

[TB10_RESISTOR_TRIM.sch](TB10_RESISTOR_TRIM.sch) sweeps all **128 physical trim codes** using `Bandgap_Core_Res.sch`. At each process corner it selects a code at **3.3 V / 25 °C**, holds it across supply and temperature, and checks cold start and analog restart with DVDD powered first and held at 3.3 V.

The full profile contains **405 process/temperature bundles**, covering 2,835 supply/temperature points, 362,880 code-sweep DC points, 51,840 calibration DC points, and 2,835 startup/restart transients. `trim_nominal` is the separate quick TT / 25 °C check at 3.3 V and 5 V. Full TB10 does not include trim Monte Carlo, a dense post-trim TC sweep, trimmed PSRR/noise/stability, or DVDD-loss sequencing.

The [published temperature-trim analysis](docs/results/trim-temperature-2026-09-28/README.md) uses the saved all-code sweeps to choose minimum-drift codes and separately verifies their dense temperature behavior. It is not the standard runner's voltage-calibration mode.

For probe connections, statistical assumptions, trim criteria, and model limitations, see the [testbench reference](docs/TESTBENCH_DETAILS.md). For recorded checks, see [VALIDATION.md](VALIDATION.md).
