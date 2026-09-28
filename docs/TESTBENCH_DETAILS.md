# Testbench reference

[Back to the README](../README.md) · [Simulation guide](SIMULATION_GUIDE.md) · [Validation notes](../VALIDATION.md)

This reference keeps the detailed measurement assumptions and circuit connections. The README provides the ordered overview of all ten benches.

## TB05: Loop-probe connections

The loop-probe schematic now follows the repaired, **untrimmed**
`Bandgap_Core.sch`. It includes the current 5 V device choices, startup
connections, and device dimensions. The seven-pin interface and both
injections are preserved:

```spice
x1 avdd vref 0 lg_main_e lg_main_f lg_bias_e lg_bias_f Bandgap_Core_LoopProbe
```

MAIN e is the existing `vgn2` output with C1 attached; MAIN f goes to M3's gate. BIAS e is `vbn_i`; BIAS f goes to N2's gate. The other loop remains closed while each cut is measured. The OP acceptance gate remains 1.194 V ±0.5%. Conventional phase margin is reported only when the crossing pattern supports it. These are conditional loop measurements, not a blanket stability certificate for the coupled network.

After changing `Bandgap_Core.sch`, keep the probe synchronized and run
`python3 verify_xschem_symbols.py` in the configured Xschem environment. It
compares the generated core and probe netlists after closing the two cuts,
including every device parameter and connection, and rejects extra f-port
loads or a relocated C1. The probe does not contain the resistor-trim variant.

Regenerate the TB05 netlist before simulating this update. Existing TB05
reports measured the previous probe and must not be used as results for the
repaired core. A newly generated deck changes the runner fingerprint, so
old cached cases will not be reused for the updated circuit.

## TB06: Monte Carlo and correction assessment

The runner replaces the three deterministic model sections with the PDK's `statistical`, `bjt_statistical`, and `res_statistical` sections. It selects global-only, mismatch-only, and combined modes through `sw_stat_global`/`sw_stat_mismatch`. It checks that those sections exist before scheduling. It does not add an invented Gaussian voltage offset to the reference.

The full profile runs 100 deterministic seeds per mode at all 21 V/T points: 6,300 simulations, representing 100 model draws per mode, not 6,300 independent dies. `setseed` followed by `reset` reparses the circuit before OP analysis. The same seed and model ordering are used across V/T. Seed reproducibility assumes the same ngspice executable, model files, and deck ordering. Smoke uses only three combined-mode seeds at 5 V/25 °C to check the workflow.

Statistical global variation replaces the fixed ff/ss/fs/sf grid. Combining those shifts with deterministic extreme process corners would not represent ordinary population yield. Deterministic corner coverage is supplied by the other benches. The original MIM compatibility model remains nominal in this **DC-only** test; MIM random variation is not exercised. Device mismatch coverage is whatever the installed PDK statistical models implement.

The output correction is `1.194 V − simulated VREF`, reported in mV. **TB06 still uses the untrimmed `Bandgap_Core`; it does not exercise the separate physical trim network.** TB10 exercises `Bandgap_Core_Res` over configured fixed corners, but does not add trim yield qualification to TB06. This quantity helps estimate the correction range needed; it does not demonstrate realizable trim resolution, post-trim TC, or trim yield. MC startup/PSRR/noise and statistical layout effects are outside TB06's current scope. Histograms use one V/T point; they do not pool PVT points into a misleading yield histogram.

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

## TB10: Physical resistor trim and selected-code startup

**Calibration goals and the default runner:** the project now targets approximately
**1.18 V with minimum temperature drift**. The [September 28 temperature-trim results](results/trim-temperature-2026-09-28/README.md)
use a separate all-code reanalysis and dense temperature verification, selecting
one code across both supply endpoints and the full temperature range. The standard
TB10 procedure below still calibrates to 1.194 V at one temperature. Changing only
that voltage target would not reproduce temperature-first calibration. The new
DC screen does not qualify startup at its newly selected codes.


TB10 uses the existing **Bandgap_Core_Res.sch**, via its custom 12-pin symbol.
It includes the real resistor segments, MOS bypass switches and body ties—not
ideal replacements. No core dimensions or connections are changed by the runner.

The bundle:

1. Sweeps every code 0–127 at each configured process, temperature and AVDD.
2. Keeps DVDD and logic-high at 3.3 V; connects AVSS and DVSS to ground.
3. Chooses the closest healthy code to 1.194 V at **25 C / 3.3 V for each
   process corner**, then **holds that code across all temperatures and supplies**.
   Independently optimal codes are reported separately and are not used for passing.
4. Checks cold start and analog restart at every configured V/T point using that held code.
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
results/full/TB10_RESISTOR_TRIM_UPLOAD_THIS.txt
results/full/TB10_RESISTOR_TRIM/cases/<process-and-temperature>_trim/
results/full/plots/
```

The quick profiles use their own `results/smoke/` or `results/trim_nominal/`
directories. Reports separate nominal supplies (3.3–5 V) from stress points
(3.0/5.5 V with the supplied full profile). `full_PVT_qualified` remains false:
this bench does not cover trim Monte Carlo, a dense temperature-coefficient
sweep, trimmed PSRR/noise, DVDD loss, AVDD-first sequencing, or extracted layout.

The plotter produces case status, held-code PVT summaries, VREF/error/code-step curves, supply/VREF/startup
current waveforms, and cold/restart readiness bars. They also appear in the
normal combined `bandgap_plots.pdf`. CSVs include common metrics,
`TB10_RESISTOR_TRIM_trim_codes.csv` (all completed sweep points, independent of the displayed trace limit), and
`TB10_RESISTOR_TRIM_startup_events.csv`.

Before replotting TB10, its previous generated PNGs/CSVs move to
`plots/previous/TB10_.../`. This preserves them without leaving stale startup
pictures beside a newer DC-only report.

Matching completed bundles resume using the same fingerprint/locking/report
mechanism. Changed inputs or retries create a new `attempts/run_.../` inside
the case folder, retaining its decks, logs, full terminal traces and DC CSV.
TB10 retains these attempt artifacts even if `retain_waveforms` is false;
in that mode, full terminal traces are losslessly compressed as `trace.txt.gz`.
Readiness metrics always use every adaptive timepoint; plotting traces are
reduced to roughly 12,000 samples and use the normal compressed cache.
Source and runner changes alter fingerprints; older results are not assumed
compatible merely because they are present.

See [VALIDATION.md](../VALIDATION.md) for representative nominal and full-profile checks; these are separate from completion of the configured grid.

## Model provenance

The embedded MIM model is your existing charge-form compatibility implementation based on GF180's MIM coefficients. Do not also add `mimcap_typical`, which would redefine the same subcircuit. It is not an untouched foundry capacitor subcircuit, and the package does not establish post-layout capacitor parasitics or area compliance.

See `VALIDATION.md` for the software and representative local simulator checks performed on this release. The full corner matrix still needs to run in your actual PDK environment.

The inherited GF180-derived MIM block retains its attribution and Apache-2.0 license in [LICENSE-GF180.txt](../LICENSE-GF180.txt). That file does not select a license for the rest of this project. The PDK is installed separately.

The README schematic images use [Xschem's native SVG export](https://xschem.sourceforge.io/stefan/xschem_man/developer_info.html), with a documentation palette and stroke weight. Exported device positions, labels and connections are preserved; each SVG records the source schematic hash. GF180 symbol geometry attribution is retained in each image.

## References

Primary references consulted for the test methods:

- [GF180 statistical model reference guide](https://gf180mcu-pdk.readthedocs.io/en/latest/analog/model_parameters/LV/LV_9.html)
- [GF180 primitive model source](https://github.com/google/globalfoundries-pdk-libs-gf180mcu_fd_pr)
- [ngspice manual](https://ngspice.sourceforge.io/docs/ngspice-44-manual.pdf)
- [ngspice control-language tutorial](https://ngspice.sourceforge.io/ngspice-control-language-tutorial.html)
