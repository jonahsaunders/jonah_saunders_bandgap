# Jonah Saunders Bandgap

A GF180 bandgap reference project with Xschem schematics, ten independent ngspice testbenches, a Python simulation runner, and plotting tools. All benches share **one configuration file: `bandgap_config.json`**.

This branch contains the cleaned startup-repaired core and the physical resistor-trim variant. TB10 uses the same runner, configuration, reports and plotter as TB01–TB09; no separate trim package is required. Historical and current validation notes are in [VALIDATION.md](VALIDATION.md).

## Repository contents

| Files | Purpose |
|---|---|
| `Bandgap_Core.sch`, `Bandgap_Core.sym` | Functional bandgap core |
| `Bandgap_Core_LoopProbe.sch`, `Bandgap_Core_LoopProbe.sym` | Core with loop-probe connections |
| `Bandgap_Core_Res.sch`, `Bandgap_Core_Res.sym` | Physical seven-bit resistor-trim core and 12-pin symbol |
| `TB01_*.sch` through `TB10_*.sch` | Ten independent testbenches |
| `bandgap_config.json` | Sweep settings, profiles, and control templates |
| `run_bandgap.py` | Unified simulation runner and path configuration |
| `plot_bandgap.py` | Figures, combined PDF, and metrics CSVs |
| `verify_suite.py` | Software checks that require no simulator or PDK |

Keep these project files together: the schematic launchers and Python imports depend on this layout.

## First run

Clone this repository (or extract the repository ZIP), then open a terminal in its root folder in your Linux/FOSS/Xschem environment.

```bash
# Optional: isolate plotting dependencies in a virtual environment.
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 verify_suite.py
python3 run_bandgap.py --configure --netlist-dir "$HOME/.xschem/simulations"
```

Use your actual Xschem netlist directory; omit `--netlist-dir` to use `~/.xschem/simulations`. Some FOSS containers use `/headless/.xschem/simulations`. Configuration rewrites the ten launchers and binds their symbols to this repository folder. Run it after cloning or moving the folder. It does not modify any core schematic. Review the resulting local path changes before committing testbench schematics.

**TB01–TB09 default to `full`, including TB05. TB10 defaults separately to `trim_nominal`.** For a quick initial run, pass `--profile smoke` as below. To use smoke runs from Xschem, set `default_profile` and TB05's `test_profiles` entry to `smoke` before simulating.

Open a `TBxx_*.sch`, regenerate its netlist, and simulate that bench. Each schematic invokes only its own test. To smoke-test a generated netlist directly:

```bash
python3 run_bandgap.py --test TB07_NOISE --deck /headless/.xschem/simulations/TB07_NOISE.spice --profile smoke
python3 plot_bandgap.py --profile smoke
```

The simulator runner needs Python 3.9+ and ngspice on PATH. Plotting additionally needs NumPy and Matplotlib. The runner uses Linux/POSIX file locks, matching the FOSS environment. Your existing GF180 symbol library and model installation are still required; the PDK is not bundled. `--configure` adjusts project/netlist paths, not PDK model paths. If necessary, edit the MODELS block to point to your installation.

## One JSON file

`bandgap_config.json` replaces `pvt_config.json`, `pvt_config_loop_smoke.json`, and `pvt_controls.json`:

- `output_directory`: one results root, relative to the JSON's directory unless absolute. Default: `results` beside the project files.
- `defaults`: PVT axes, simulator settings, and shared measurement settings.
- `profiles`: `full`, `smoke`, `loop_smoke`, and `trim_nominal` overrides.
- `default_profile`: `full`.
- `test_profiles`: TB05 selects `full`; TB10 selects `trim_nominal`. Set TB05 to `loop_smoke` for a nominal loop check or `smoke` for the shared smoke profile.
- `test_overrides`: settings by full test name, including TB10's fixed DVDD, transient step, assistance/bias limits and optional startup.
- `controls`: the existing TB01–TB03 ngspice control templates, now embedded in this file. TB04–TB10 controls are generated in Python and their template slots are empty strings.

Settings apply in this order: defaults → per-test overrides → selected profile. A command-line `--profile` overrides the default/per-test profile selection. Full and smoke results live in separate subdirectories, so they cannot overwrite each other.

For example, change the `test_profiles` entry to `"TB05_LOOP_STABILITY": "loop_smoke"` to make the GUI run a nominal TB05 check. `--configure` preserves the JSON selection. To make TB01–TB09 GUI runs quick smoke tests, set `default_profile` to `smoke` and TB05's entry to `smoke` too; leave TB10's entry at `trim_nominal`.

An earlier `validation.json`, referenced in the historical validation notes, described past verification; it is not runtime configuration and is not included here. That history is documented in `VALIDATION.md`. Only one JSON file is shipped. Generated per-case `result.json` caches remain simulation **outputs**, not additional configuration files.

The existing TB01–TB05 analysis targets and algorithms are retained: 1.194 V ±0.5%, TC ≤10 ppm/°C, and the existing PSRR/startup metrics. New TB06–TB09 use the corresponding defaults shown in JSON. If changing project targets, update both the legacy controls/math and the new settings; changing a new-bench threshold does not rewrite the legacy measurements.

## Test coverage

For TB01–TB09, the full fixed-corner grid is **5 MOS × 3 BJT × 3 resistor × 3 MIM = 135 combinations**. Unless swept continuously, temperatures are −40, 25, and 125 °C and supplies are 3.0, 3.3, 3.6, 4.0, 4.5, 5.0, and 5.5 V. The 3.0/5.5 V points are labeled stress; the nominal range remains 3.3–5 V. All grid points run when `full` is selected, even when the operating point misses the accuracy target; TB05 retains its explicit pre-AC acceptance gate.

| Bench | Measurement | Full-profile cases | Smoke cases |
|---|---|---:|---:|
| TB01_PSRR | PSRR spectrum and 1 Hz–1 MHz worst case | 2,835 | 1 |
| TB02_LINE_REGULATION | 3.0–5.5 V DC sweep; separate nominal/stress metrics | 405 | 1 |
| TB03_STARTUP_RESTART | Existing cold start and restart sequence | 2,835 | 1 |
| TB04_TEMPERATURE | −40 to 125 °C in 1 °C steps at each supply/corner | 945 | 1 |
| TB05_LOOP_STABILITY | MAIN and BIAS conditional loop measurements | 2,835 | 1 |
| TB06_MONTE_CARLO | DC statistical accuracy/current and required output correction | 6,300 | 3 |
| TB07_NOISE | Output noise spectrum and band-integrated RMS noise | 2,835 | 1 |
| TB08_POWER_DEVICE_LIMITS | Quiescent current/power; DC/startup MOS voltage screens | 2,835 | 1 |
| TB09_SUPPLY_DISTURBANCE | Ramps, brownouts, repeated cycles, supply steps | 33,210 | 5 |
| TB10_RESISTOR_TRIM | Physical trim sweep + held-code startup/restart | Use `trim_nominal` | Use `trim_nominal` |

TB10's `trim_nominal` profile schedules one calibration bundle: 256 DC operating points plus two startup/restart transients. It rejects other PVT axes instead of silently treating them as nominal.

Full coverage can take substantial time, especially TB03/TB09. Inspect the schedule without a simulator/netlist:

```bash
python3 run_bandgap.py --test TB09_SUPPLY_DISTURBANCE --profile full --list-cases
```

Run a full bench against its own freshly generated netlist:

```bash
python3 run_bandgap.py --test TB08_POWER_DEVICE_LIMITS --deck /headless/.xschem/simulations/TB08_POWER_DEVICE_LIMITS.spice --profile full
```

## TB06: Monte Carlo and correction assessment

The runner replaces the three deterministic model sections with the PDK's `statistical`, `bjt_statistical`, and `res_statistical` sections. It selects global-only, mismatch-only, and combined modes through `sw_stat_global`/`sw_stat_mismatch`. It checks that those sections exist before scheduling. It does not add an invented Gaussian voltage offset to the reference.

The full profile runs 100 deterministic seeds per mode at all 21 V/T points: 6,300 simulations, representing 100 model draws per mode, not 6,300 independent dies. `setseed` followed by `reset` reparses the circuit before OP analysis. The same seed and model ordering are used across V/T. Seed reproducibility assumes the same ngspice executable, model files, and deck ordering. Smoke uses only three combined-mode seeds at 5 V/25 °C to check the workflow.

Statistical global variation replaces the fixed ff/ss/fs/sf grid. Combining those shifts with deterministic extreme process corners would not represent ordinary population yield. Deterministic corner coverage is supplied by the other benches. The original MIM compatibility model remains nominal in this **DC-only** test; MIM random variation is not exercised. Device mismatch coverage is whatever the installed PDK statistical models implement.

The output correction is `1.194 V − simulated VREF`, reported in mV. **TB06 still uses the untrimmed `Bandgap_Core`; it does not exercise the separate physical trim network.** TB10 exercises `Bandgap_Core_Res` nominally, but does not add trim yield qualification to TB06. This quantity helps estimate the correction range needed; it does not demonstrate realizable trim resolution, post-trim TC, or trim yield. MC startup/PSRR/noise and statistical layout effects are outside TB06's current scope. Histograms use one V/T point; they do not pool PVT points into a misleading yield histogram.

## TB07: noise

TB07 runs small-signal output noise from 0.1 Hz to 100 MHz with 100 points/decade. It exports both output amplitude spectral density (V/√Hz) and power spectral density (V²/Hz). The input reference for ngspice's noise calculation is VDD; the metric used is **output** noise, not input-referred supply noise.

The default integration bands are 0.1–10 Hz and 1 Hz–1 MHz. Integration uses power-law interpolation of PSD on the logarithmic frequency grid, then takes the square root. It does not integrate ASD directly. Nonfinite, zero, or incomplete spectra fail execution. An OP outside the reference target is explicitly marked; its noise is not included in the qualified RMS distribution.

No numerical noise specification has been agreed, so `noise_requirement_pass` is null. Review the installed PDK's noise support and simulator warnings before accepting absolute numbers. Behavioral MIM leakage/capacitance does not establish dielectric-noise accuracy. This is not a transient random-noise simulation.

## TB08: power and MOS voltage/headroom checks

The runner discovers the actual top-level core instance and its MOS subcircuit instances from the generated netlist. It measures quiescent IDD/power, VDS, VGS, VGD, VGB, VDB, VSB, VDSAT, gm, and drain current. It also runs a zero-initial-state 100 µs supply ramp, followed through 2 ms, and records the peak absolute terminal voltages and supply current.

The defaults screen 03v3, 05v0, and 06v0 devices against 3.3, 5.0, and 6.0 V respectively. These are **conservative, user-editable screening thresholds, not foundry absolute-maximum ratings or reliability signoff**. For example, a 5.5 V supply stress case can intentionally raise a 5.0 V screen flag. Review terminal polarity, body-junction forward bias, PDK reliability rules, and intended device function separately.

The DC saturation margin is `|VDS| − |VDSAT|`; negative values on intentionally switching/off startup devices are not automatically circuit failures. The default intrinsic MOS element name is `m0`, matching the inspected GF180 models. Change `intrinsic_mos_name` if your PDK uses another name. Missing internal device quantities fail the case instead of silently omitting headroom results.

This check covers MOS devices in the present single-level core. BJT/passive operating limits, all ERC rules, layout parasitics, and maximum voltages during TB09 events remain separate checks. No artificial output load or extra DUT capacitor is added.

## TB09: supply disturbances

Each case starts with the DUT's real startup circuit, including its internal capacitors. No reference-node clamp or forced discharge is inserted.

- Supply ramp times: 1 µs, 100 µs, and 10 ms.
- Brownout levels: 0, 1, and 2.5 V; durations: 10 µs and 1 ms.
- Repeated interruptions: three full power-off/recovery cycles with 1 ms off time.
- Supply steps: pulses to 3.3 and 5.0 V, excluding a level equal to the case's starting voltage, with 500 µs hold and 1 µs edges.

The supply returns to each case's programmed voltage. A recovery is ready only if VREF enters the absolute ±0.5% target within 300 µs after the recovery edge **and remains there through the 2 ms observation window**. For disturbances, baseline startup must also meet its readiness check. A late departure from the band counts as failure; the first threshold crossing alone is insufficient.

Metrics include final reference, settling time or null when unsettled, overshoot, minimum reference during recovery, and peak supply current. Supply-step cases additionally report the maximum reference deviation during/after the disturbance. The 2 µs maximum transient step is an explicit simulation setting; tighten it and check convergence when examining very narrow spikes or close timing margins. These finite scenarios are not an exhaustive supply-event proof.

## TB10: physical resistor trim and selected-code startup

TB10 uses the existing **Bandgap_Core_Res.sch**, via its custom 12-pin symbol.
It includes the real resistor segments, MOS bypass switches and body ties—not
ideal replacements. No core dimensions or connections are changed by the runner.

After configuring the launchers, open **TB10_RESISTOR_TRIM.sch** in Xschem,
regenerate its netlist and simulate. It launches the unified runner just like
the other benches. Alternatively, run the freshly generated netlist directly:

```bash
python3 run_bandgap.py --test TB10_RESISTOR_TRIM \
  --deck /headless/.xschem/simulations/TB10_RESISTOR_TRIM.spice
python3 plot_bandgap.py --test TB10_RESISTOR_TRIM --profile trim_nominal
```

Use your actual netlist path. The default profile is `trim_nominal`;
`--profile full` and `--profile smoke` are not TB10 corner qualifications.
Preview the schedule without a simulator:

```bash
python3 run_bandgap.py --test TB10_RESISTOR_TRIM --list-cases
```

The bundle:

1. Sweeps every code 0–127 at AVDD = 3.3 V and 5 V, TT / 25 C.
2. Keeps DVDD and logic-high at 3.3 V; connects AVSS and DVSS to ground.
3. Chooses the closest healthy code to 1.194 V at 3.3 V and **holds that same code
   at 5 V**. Independently optimal codes are reported separately.
4. Checks cold start and analog restart at both supplies using that held code.
   DVDD starts first and remains powered during analog shutdown/restart.

`b0` is the LSB; a 1 bypasses its physical segment, while a 0 includes it.
Bit strings are shown as `b6 ... b0`. Code search is exhaustive because the
measured 63→64 transition is slightly nonmonotonic.

The common target/tolerance/recovery settings apply: 1.194 V +/-0.5% and 300 us
after the analog ramp. In addition, M7/M20/SUPINJ currents must be <=1 nA and
N1/M16/M18 bias magnitudes >10 nA, sustained through the event window with at
least 100 us final observation. TB10 uses a maximum 100 ns transient step and
the inherited tighter Gear settings. These remain explicit in the configuration
and schematic; no PDK patch or resistor-junction workaround is introduced.

Add `--dc-only` to omit transients; reports explicitly mark startup untested.
The `trim_startup` per-test setting controls the same choice for GUI runs.

Results use the existing hierarchy:

```text
results/trim_nominal/TB10_RESISTOR_TRIM_UPLOAD_THIS.txt
results/trim_nominal/TB10_RESISTOR_TRIM/cases/TT_T25_trim_3p3V_5V/
results/trim_nominal/plots/
```

The plotter produces case status, VREF/error/code-step curves, supply/VREF/startup
current waveforms, and cold/restart readiness bars. They also appear in the
normal combined `bandgap_plots.pdf`. CSVs include common metrics,
`TB10_RESISTOR_TRIM_trim_codes.csv` (all 256 code points), and
`TB10_RESISTOR_TRIM_startup_events.csv`.

Before replotting TB10, its previous generated PNGs/CSVs move to
`plots/previous/TB10_.../`. This preserves them without leaving stale startup
pictures beside a newer DC-only report.

Matching completed bundles resume using the same fingerprint/locking/report
mechanism. Changed inputs or retries create a new `attempts/run_.../` inside
the case folder, retaining its decks, logs, full terminal traces and DC CSV.
TB10 intentionally retains these attempt artifacts even if `retain_waveforms`
is false; its compact plotting traces also use the normal compressed cache.
This release changes runner/config fingerprints; older results are not assumed
compatible merely because they are present.

Nominal validation selects code 70 (`1000110`), giving approximately
1.194454 V at 3.3 V and 1.194605 V at 5 V; cold/restart checks pass at both.
This is **not** full PVT, trim yield, post-trim TC, PSRR/noise, extracted-layout or
foundry reliability qualification. AVDD-first startup, DVDD loss and retained
analog charge during DVDD shutdown remain unqualified. The trim gate-voltage
screen is diagnostic, not a foundry rating.

The earlier `trim_testbench/` source package has been consolidated into the
root scripts, schematic and this README. No new `run_trim.py` or preparation
folder is needed. Old locally generated results are not deleted or automatically
imported into the new cache.

## TB05 connections preserved

The seven-pin core and both injections are retained exactly as uploaded:

```spice
x1 avdd vref 0 lg_main_e lg_main_f lg_bias_e lg_bias_f Bandgap_Core_LoopProbe
```

MAIN e is the existing `vgn2` output with C1 attached; MAIN f goes to M3's gate. BIAS e is `vbn_i`; BIAS f goes to N2's gate. The other loop remains closed while each cut is measured. The OP acceptance gate remains 1.194 V ±0.5%. Conventional phase margin is reported only when the crossing pattern supports it. These are conditional loop measurements, not a blanket stability certificate for the coupled network.

## Plot all available results

```bash
python3 plot_bandgap.py
python3 plot_bandgap.py --profile full
python3 plot_bandgap.py --profile smoke --test TB07_NOISE --test TB09_SUPPLY_DISTURBANCE
```

The first command discovers all profile directories under `output_directory`. Each profile gets its own `plots` folder containing:

- PNG figures for every available bench, including failed-case status pages;
- one combined `bandgap_plots.pdf` per profile;
- per-bench metrics CSVs, a TB08 per-device CSV, and TB10 trim-code/startup-event CSVs.

All completed-case metrics are included. To keep large sweeps readable and limit memory, detailed waveform panels display up to 24 evenly selected case traces per bench by default. This sampling is stated in the console and figure case counts. It is not a worst-case waveform selection. Use `--max-waveforms 0` to display every available trace, or raise the limit to a manageable number. Worst-case metrics still use all reported cases.

`--results /path/to/results` overrides the config's results root; it can also point directly to one profile. `--out` selects a figure destination. `--no-pdf`, `--no-csv`, and `--dpi` are available. Keep `run_bandgap.py` beside the plotter so loop reconstruction uses the same implementation as the measurements.

The plotter only accepts waveform/cache files that match the report's run fingerprint. It can recover current-run cases from a header-only interrupted report without mixing older cached runs. A figure-generation error returns a nonzero exit code while retaining the other successfully generated figures.

## Results, resume, and what to upload

Each bench writes:

```text
results/<profile>/TBxx_NAME_UPLOAD_THIS.txt
results/<profile>/TBxx_NAME/cases/<case_id>/result.json
results/<profile>/TBxx_NAME/cases/<case_id>/waveforms.txt.gz
```

The text report contains coverage, profile, per-case metrics, simulator warnings, a summary, and an explicit complete/incomplete marker. Upload the relevant `TBxx_NAME_UPLOAD_THIS.txt`. For curve-level review, include the plots or compressed case waveforms. Successful waveforms remain compressed even when `retain_waveforms` is false; that flag controls retention of raw report/deck/log artifacts. Failed cases retain their available log/deck for diagnosis.

Re-running resumes matching results. The fingerprint covers configuration, controls, the generated deck, runner, selected executable, and discovered model-file dependencies. If a simulator is selected through a wrapper, the wrapper is fingerprinted; changes to its target executable/environment are not automatically detected—disable resume after such changes. `--retry-failed` retries cached execution failures; it does not rerun valid completed cases that miss a performance target. `--max-cases` is a debug limit and produces an incomplete-coverage report.

An error before scheduling may occur before a new report is created. Check the console and report fingerprint; a pre-existing report is not evidence that the attempted run started. Exit code 0 means all planned simulations executed and parsed, **not that performance passed**. Exit 2 means incomplete coverage or execution failures; configuration/preflight errors return 1. Review the actual metrics and stress/nominal labels.

## Model provenance and validation limits

The embedded MIM model is your existing charge-form compatibility implementation based on GF180's MIM coefficients. Do not also add `mimcap_typical`, which would redefine the same subcircuit. It is not an untouched foundry capacitor subcircuit, and the package does not establish post-layout capacitor parasitics or area compliance.

See `VALIDATION.md` for the software and representative local simulator checks performed on this release. The full corner matrix still needs to run in your actual PDK environment.

## Software checks

Run the integrated software checks:

```bash
python3 -m py_compile run_bandgap.py plot_bandgap.py verify_suite.py
python3 verify_suite.py
```

The 25 checks use only the Python standard library; they do not require ngspice,
Xschem or the PDK and are not electrical signoff. They cover the existing suite,
all ten launchers, trim polarity/code coverage, fixed-code calibration, failure
detection and startup readiness. Electrical and plotting checks are documented
in [VALIDATION.md](VALIDATION.md).

Generated simulation results and Python caches are excluded by `.gitignore`.
The inherited GF180-derived MIM block is embedded in TB10's MODELS section,
matching the existing benches; its attribution is retained and its Apache-2.0
license is included as [LICENSE-GF180.txt](LICENSE-GF180.txt). That file does not
select a license for the rest of the project. PDK files are installed separately.

## References

Primary references consulted for the test methods:

- [GF180 statistical model reference guide](https://gf180mcu-pdk.readthedocs.io/en/latest/analog/model_parameters/LV/LV_9.html)
- [GF180 primitive model source](https://github.com/google/globalfoundries-pdk-libs-gf180mcu_fd_pr)
- [ngspice manual](https://ngspice.sourceforge.io/docs/ngspice-44-manual.pdf)
- [ngspice control-language tutorial](https://ngspice.sourceforge.io/ngspice-control-language-tutorial.html)
