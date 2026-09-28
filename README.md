# Jonah Saunders Bandgap

A GF180MCU bandgap voltage reference with a startup circuit, a seven-bit physical resistor-trim network, and ten Xschem/ngspice testbenches.

## Projected post-trim specifications

**Current pre-layout simulations suggest that the revised specifications below are achievable with the physical resistor-trim core.** These are conservative performance goals informed by the September 28, 2026 simulation review, not guaranteed silicon limits or a claim that every post-trim corner has passed. Final specifications will be established after the remaining trim-aware simulations and post-layout verification.

The intended reference is **1.200 V nominal**, matching the initial proposal. Select the trim code once at **3.3 V AVDD and 25 °C**, with **3.3 V DVDD**, then hold that code fixed as supply and temperature change.

| Parameter | Projected goal / operating condition |
| --- | --- |
| Reference voltage | **1.200 V nominal** |
| Initial accuracy after trim | **±0.25%** at the calibration condition; trim coverage under mismatch remains to be verified |
| Accuracy across supply and temperature | **±1%** with the calibration code held fixed; provisional full-range budget |
| Analog supply, AVDD | **3.3-5.0 V**; 3.0 V remains a characterization goal |
| Trim logic supply, DVDD | **3.3 V** |
| Temperature range | **−40 to 125 °C** |
| Quiescent analog supply current | Approximately **30 µA typical**, **≤60 µA maximum**; DVDD current is characterized separately |
| Line regulation | **≤0.1% total VREF change** across 3.3-5.0 V at fixed temperature and trim code |
| Temperature coefficient | **≤60 ppm/°C** across −40 to 125 °C; dense post-trim sweeps remain to be verified |
| Power-supply rejection | **≥55 dB at 1 kHz** and **≥45 dB throughout 1 Hz-1 MHz** |
| Output noise density | **≤3,000 nV/√Hz at 1 kHz** |
| Integrated output noise | **≤100 µV RMS over 0.1-10 Hz** |
| Startup / restart readiness | Reach and remain within the reference tolerance **within 300 µs after the supply ramp**; unresolved transient cases remain to be verified |
| Trim control | **7 bits / 128 codes**, calibrated once and held fixed |

The simulations supporting this projection include:

- **Physical trim:** reanalysis of the saved TB10 DC code sweeps, selecting codes for 1.200 V at 25 °C / 3.3 V, places all **135 available nominal-supply points between 1.19562 V and 1.20574 V**. Calibration error is at most **0.056%** in this subset. These points cover three temperatures, five supplies, and nine resistor/capacitor corner combinations, all with **typical MOS and BJT models**. This is a reanalysis of existing DC data, not a new transient run or full statistical qualification.
- **Temperature:** at those reselected codes, the three-temperature voltage spans correspond to approximately **38-50 ppm/°C**. These sampled values can underestimate the full temperature coefficient; they motivate a provisional 60 ppm/°C goal rather than establish a maximum.
- **Untrimmed baseline:** worst nominal-supply line variation is **0.0616%**, maximum current in the nominal-supply temperature sweeps is **54.4 µA**, minimum PSRR over 1 Hz-1 MHz is **47.8 dB**, and integrated noise over 0.1-10 Hz is **52-77 µV RMS**. These results support the proposed budgets, while trimmed-core PSRR and noise still require verification.

Trim is expected to improve initial voltage accuracy; improvement in temperature coefficient, PSRR, or noise is not assumed. Remaining checks include physical-trim mismatch coverage, dense held-code temperature sweeps, trimmed-core stability and loading, and resolution of transient simulator aborts. There are no extracted-layout or silicon results yet.

**Additional proposal goals not yet supported by measurements:** load regulation **≤1%** after an output-load range is defined, and a **220 nA nominal PTAT output current** after its measurement conditions are defined. These remain goals, not simulation-backed projections.

## Current testbench acceptance targets

The existing runner uses the following acceptance targets. Its trim calibration target remains **1.194 V**, while the projected specifications above use the proposal's **1.200 V** nominal reference. The projected goals do not change the testbench configuration or reclassify existing results. Trim is selected at **3.3 V and 25 °C**, then held fixed as supply and temperature change.

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

**Current verification scope:** TB01-TB09 characterize the untrimmed core or its loop-probe variant. TB10 exercises the physical resistor-trim core. Full trimmed-core qualification still needs trim-aware mismatch, temperature-coefficient, PSRR, noise, and stability coverage. See [validation notes](VALIDATION.md) for the checks completed so far.

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

For probe connections, statistical assumptions, trim criteria, and model limitations, see the [testbench reference](docs/TESTBENCH_DETAILS.md). For recorded checks, see [VALIDATION.md](VALIDATION.md).
