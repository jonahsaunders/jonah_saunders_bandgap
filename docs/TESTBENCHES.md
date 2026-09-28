# Testbenches

[Overview](../README.md) · [Results](RESULTS.md) · **Testbenches** · [Simulation guide](SIMULATION_GUIDE.md) · [Measurement details](TESTBENCH_DETAILS.md)

Overview of the ten Xschem/ngspice benches, their configured coverage, and the existing runner criteria.

## Current testbench acceptance targets

The standard runner retains its existing **1.194 V** voltage-calibration criterion at **3.3 V / 25 °C** and the acceptance targets below. The revised project goal is **approximately 1.18 V with calibration for minimum temperature drift**. The [published temperature-trim results](RESULTS.md) come from a separate analysis; updating this goal does not change the runner's settings or reclassify historical results. Simply changing its voltage target to 1.18 V would not implement minimum-drift calibration.

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

**Current verification scope:** TB01-TB09 characterize the untrimmed core or its loop-probe variant. TB10 exercises the physical resistor-trim core. The [separate temperature-trim screen](RESULTS.md) adds dense fixed-corner DC coverage at the two nominal supply endpoints. Full trimmed-core qualification still needs mismatch, broader supply coverage, startup/restart at the selected codes, PSRR, noise, and stability checks. See [validation notes](../VALIDATION.md) for the checks completed so far.

## Testbench overview

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

[TB01_PSRR.sch](../TB01_PSRR.sch) measures supply-to-reference coupling with an AC sweep from 1 Hz to 100 MHz. It reports PSRR at selected frequencies and the worst rejection over the **1 Hz-1 MHz specification band**. Passing requires at least 60 dB throughout that band and a valid DC reference.

### TB02: Line regulation

[TB02_LINE_REGULATION.sch](../TB02_LINE_REGULATION.sch) sweeps AVDD from 3.0 to 5.5 V in 10 mV steps. It reports reference span, endpoint and local slopes, current, and absolute accuracy, with separate results for the **nominal 3.3-5 V range** and the full stress sweep.

### TB03: Startup and restart

[TB03_STARTUP_RESTART.sch](../TB03_STARTUP_RESTART.sch) checks cold start, supply shutdown, and analog restart using the core's real startup circuit. It records settling, overshoot, final reference, and supply current. Readiness uses the absolute reference tolerance and the **300 µs deadline after each ramp**.

### TB04: Temperature

[TB04_TEMPERATURE.sch](../TB04_TEMPERATURE.sch) sweeps **−40 to 125 °C in 1 °C steps** at each supply and process combination. It measures reference drift, box temperature coefficient, accuracy, and current. The TC target is 10 ppm/°C; this bench currently measures the untrimmed core.

### TB05: Loop stability

[TB05_LOOP_STABILITY.sch](../TB05_LOOP_STABILITY.sch) measures the MAIN and BIAS feedback loops through the repaired [loop-probe core](../Bandgap_Core_LoopProbe.sch). Each cut is measured with the other loop closed; outputs include return-ratio curves, crossing information, conditional margins, and DC continuity checks. Regenerate the netlist after the probe repair: old TB05 results do not describe the new core. This probe follows `Bandgap_Core.sch`, not the resistor-trim variant.

### TB06: Monte Carlo

[TB06_MONTE_CARLO.sch](../TB06_MONTE_CARLO.sch) uses the installed PDK's global, mismatch, and combined statistical models to measure DC reference accuracy and current. The full run reuses **100 seeds per mode across 21 supply/temperature points**. Required output correction is reported to help assess trim range; it does not simulate physical trim or establish post-trim yield.

### TB07: Noise

[TB07_NOISE.sch](../TB07_NOISE.sch) measures output noise density from 0.1 Hz to 100 MHz and integrates RMS noise over **0.1-10 Hz** and **1 Hz-1 MHz**. Operating points outside the accuracy target are marked separately. No numerical noise pass/fail budget is currently assigned.

### TB08: Power and device limits

[TB08_POWER_DEVICE_LIMITS.sch](../TB08_POWER_DEVICE_LIMITS.sch) measures quiescent current/power, MOS terminal voltages, and saturation headroom at DC and during startup. The current target is **60 µA**. Device voltage thresholds are configurable screens; nominal and stress results are separated, and the screens are not foundry reliability signoff.

### TB09: Supply disturbances

[TB09_SUPPLY_DISTURBANCE.sch](../TB09_SUPPLY_DISTURBANCE.sch) exercises slow/fast ramps, brownouts, repeated interruptions, and supply steps. Recovery must enter the absolute reference band within **300 µs** and remain there through the **2 ms observation window**. The bench records recovery time, excursions, and peak current without forcing the reference node to discharge.

### TB10: Resistor trim

[TB10_RESISTOR_TRIM.sch](../TB10_RESISTOR_TRIM.sch) sweeps all **128 physical trim codes** using `Bandgap_Core_Res.sch`. At each process corner it selects a code at **3.3 V / 25 °C**, holds it across supply and temperature, and checks cold start and analog restart with DVDD powered first and held at 3.3 V.

The full profile contains **405 process/temperature bundles**, covering 2,835 supply/temperature points, 362,880 code-sweep DC points, 51,840 calibration DC points, and 2,835 startup/restart transients. `trim_nominal` is the separate quick TT / 25 °C check at 3.3 V and 5 V. Full TB10 does not include trim Monte Carlo, a dense post-trim TC sweep, trimmed PSRR/noise/stability, or DVDD-loss sequencing.

The [published temperature-trim analysis](results/trim-temperature-2026-09-28/README.md) uses the saved all-code sweeps to choose minimum-drift codes and separately verifies their dense temperature behavior. It is not the standard runner's voltage-calibration mode.

For probe connections, statistical assumptions, trim criteria, and model limitations, see the [testbench reference](TESTBENCH_DETAILS.md). For recorded checks, see [VALIDATION.md](../VALIDATION.md).
