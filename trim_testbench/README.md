# Resistor-trim testbench (TB10)

[TB10_RESISTOR_TRIM.sch](../TB10_RESISTOR_TRIM.sch) uses the custom
[Bandgap_Core_Res.sym](../Bandgap_Core_Res.sym) and the existing transistor-level
[Bandgap_Core_Res.sch](../Bandgap_Core_Res.sch). The symbol is a 12-pin wrapper,
not a behavioral replacement or a PDK device. Neither core schematic is changed.

## Run

From the repository root, with Xschem, ngspice, Python 3, NumPy, Matplotlib and
the installed GF180MCUD PDK available:

```bash
python3 -m pip install -r trim_testbench/requirements.txt
python3 -B trim_testbench/run_trim.py
```

This exports the current core, sweeps all 128 codes at AVDD = 3.3 V and 5 V,
then runs cold-start and analog-restart tests at both supplies using one
calibration code selected at 3.3 V. DVDD and logic-high levels are always 3.3 V.
AVSS and DVSS connect to the same ideal ground; no external output load is added.

Use `--dc-only` to omit transients. Each ngspice invocation has a 180-second
timeout, adjustable with `--timeout`. Two startup cases run concurrently, with
one simulator thread each.

The PDK directory defaults to `GF180_PDK_PATH`, otherwise
`$PDK_ROOT/gf180mcuD`, otherwise `/foss/pdks/gf180mcuD`.
An unrelated shell `PDK` setting is deliberately ignored. To override:

```bash
python3 -B trim_testbench/run_trim.py --pdk-path /path/to/gf180mcuD
```

Use checkout/PDK paths without spaces or Tcl/SPICE metacharacters. This runner
expects the GF180MCUD `libs.tech/xschem` and `libs.tech/ngspice` directory layout.

## Open in Xschem

First generate this checkout's model paths and control block:

```bash
python3 -B trim_testbench/run_trim.py --prepare-only
```

Then open **TB10_RESISTOR_TRIM.sch** from the repository root using the GF180MCUD
Xschem configuration. The repository root must be in the Xschem library search
path; the runner configures this automatically for its own exports. One explicit
launch command with the default installation is:

```bash
xschem --rcfile /foss/pdks/gf180mcuD/libs.tech/xschem/xschemrc \
  --tcl 'append XSCHEM_LIBRARY_PATH :[pwd]' TB10_RESISTOR_TRIM.sch
```

Netlisting reads `trim_testbench/generated/manual_setup.spice` and inlines its
control block. It must not become a SPICE `.include` of a `.control` file:
that loses control-variable substitutions in the tested ngspice.

The graphical bench runs the 256-point DC sweep only. Its table is written to
the latest prepared snapshot's `manual_results/trim_sweep.txt`; repeated GUI
simulations replace that table. The exported `TB10_RESISTOR_TRIM.spice` can
also be run directly with `ngspice -n -b`. Use the Python runner for startup,
plots and reports.

Re-run preparation and re-netlist after modifying the core, symbol or bench,
moving the checkout, or changing PDK installations. `--run-only` reuses the
latest prepared snapshot and checks input/export hashes instead of exporting.

## Outputs and calibration

Each preparation creates a new `generated/prepare_<UTC>_<id>/` snapshot;
each automated run creates `runs/run_<UTC>_<id>/`. Old snapshots and runs are
preserved. Only generated setup/manifest pointers are replaced. Generated files
contain resolved local paths and are intentionally ignored by Git.

Important run files:

- `REPORT.md`, `summary.json`, `manifest.json`
- `trim_sweep.csv`, `trim_sweep.png`, `trim_sweep.svg`
- `startup.png`
- `startup_*V_code*/TB10_TRIM_STARTUP.spice`, `trace.txt`, `columns.json`,
  `result.json`, and simulator logs

The 12-pin subcircuit order is
`avdd avss vref b0 b1 b2 b3 b4 b5 b6 dvss dvdd`.
`b0` is the LSB; bit 1 bypasses its physical resistor and bit 0 includes it.
The displayed bit string is `b6 ... b0`. MOS on-resistance is included.
Calibration searches every code rather than assuming monotonicity.

The target is 1.194 V. The closest self-sustaining DC point at 3.3 V is retained
at 5 V; independently optimal codes are reported separately. Self-sustaining
means M7/M20/SUPINJ assistance <=1 nA and N1/M16/M18 bias magnitudes >10 nA.
Transient PASS additionally requires VREF within +/-0.5%, settled within 300 us
after the analog ramp and sustained through the remaining window, with at least
100 us of final observation. Maximum transient timestep is 100 ns.

## Model provenance and limits

MOS, BJT and resistor models come from the installed PDK. The native nwell
model is unchanged. No PDK files or model discontinuities are patched.

`preserved_mim.lib` is the **existing charge-form MIM compatibility block,
preserved verbatim from the preceding validation**. It is not a new model change,
but it is also not an untouched stock PDK MIM implementation. It is included
explicitly to reproduce the already-tested circuit; do not add the conflicting
`mimcap_typical` definition alongside it.

The inherited GF180-derived block retains its upstream attribution and is
covered by [Apache-2.0](LICENSE-GF180.txt).

This is deterministic TT / 25 C, not full PVT, Monte Carlo, post-layout, all-code
startup, PSRR, noise or reliability signoff. Completion alone is not an electrical
pass: inspect event status and voltage-screen results in the report/JSON.

DVDD ramps before AVDD and stays powered during analog shutdown/restart.
AVDD-first startup, DVDD loss, and DVDD shutdown with retained analog charge
remain unqualified. The trim-switch terminal-voltage screen is a diagnostic,
not foundry reliability approval.

See [VALIDATION.md](VALIDATION.md) for the nominal check of this package.

## Harness tests

```bash
python3 -B -m unittest discover -s trim_testbench -p 'test_*.py'
```
