# Nominal validation of the portable trim testbench

Verified 2026-09-18 with ngspice 46 and Xschem 3.4.8RC.
Installed GF180MCUD revision: `f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7`.
Models: TT MOS/BJT/resistors plus the verbatim inherited charge-form MIM;
25 C, DVDD = 3.3 V, no external output load.

## Results

The packaged runner reproduced the preceding local bench's full summary exactly.
All 256 DC points are self-sustaining under the assistance/bias screens.
The single code selected at 3.3 V is **70** (`1000110`, b6..b0); it is retained at 5 V.

| AVDD | VREF at code 70 | Error from 1.194 V | Cold start | Analog restart |
|---|---:|---:|---:|---:|
| 3.3 V | 1.194453588 V | +0.453588 mV | PASS, 213.411 us | PASS, 141.049 us |
| 5 V | 1.194605054 V | +0.605054 mV | PASS, 121.535 us | PASS, 80.780 us |

Times are measured after the analog supply ramp completes. All startup-assistance
currents fall below 1 nA; required bias branches remain above 10 nA.
Transient PASS uses the +/-0.5% VREF band, a 300 us deadline, a final observation
window of at least 100 us, and a 100 ns maximum timestep.

The 3.3 V sweep spans 1.112640–1.294099 V; the 5 V sweep spans
1.112780–1.294265 V. The largest sorted gaps are 1.745227 and 1.745492 mV.
Both sweeps have one upward step, **63 -> 64**, about 0.209 mV.
Do not assume a monotonic binary-search calibration.

The separately simulated Xschem-exported bench completes all 256 points and
agrees with the automated VREF sweep within **0.167170 microvolt**.
Its 124 DUT instances and parameters match the exported runner subcircuit
(after ignoring ordering, comments and line wrapping). All 10 harness tests pass.

The maximum measured trim-switch gate-to-terminal magnitude is 3.300118 V
(rounded upward); none exceeds the inherited 3.63 V diagnostic screen in these
two digital-first nominal tests. This does not qualify other supply sequences
or establish foundry reliability compliance.

## Reproduce

From the repository root:

```bash
python3 -B -m unittest discover -s trim_testbench -p 'test_*.py'
python3 -B trim_testbench/run_trim.py --prepare-only
python3 -B trim_testbench/run_trim.py --run-only
```

To check the graphical route separately, run the prepared
`TB10_RESISTOR_TRIM.spice` using `ngspice -n -b` and compare its
`manual_results/trim_sweep.txt` with the automated run's `trim_sweep.txt`.

Validation artifacts were retained locally in:
- prepared snapshot: `prepare_20260918T143552Z_b479ed`
- automated run: `run_20260918T143607Z_e27325`

Large generated traces and machine-specific paths are intentionally not committed.
A fresh invocation creates its own snapshot, results and source/model hash manifest.

## Provenance

SHA-256:

- `Bandgap_Core_Res.sch`: `d4be651bbb0c1c3641f7c1f7ac1f8d2a58e14ab587db74a17d58ef2e3bb38d38`
- `trim_testbench/run_trim.py`: `f9b9389014381c47ff2f4ae90ca77eee7537c45440e68404aa19adf21425d190`
- inherited `preserved_mim.lib`: `25e3c4827734c378240b14cad600ed6f329b2e4d5bf418e18e6aa46cbf59b15a`
- installed `design.ngspice`: `7e222f050318388f37543a64fbd0be55cc15e4b93f57501a09f7c159c4c9e561`
- installed `sm141064.ngspice`: `f6f4a96e18fc5ad11270ad3451aaecc7ac37fc81eb61e15b0d7d94c7bc594a24`

These are entry-file hashes, not a recursive hash of the entire PDK.
No installed PDK file or existing core schematic was edited.
The inherited MIM compatibility block is not the untouched stock MIM model;
see [model provenance](README.md#model-provenance-and-limits).

## Remaining qualification

No full PVT, Monte Carlo, extracted-layout, all-code startup, PSRR or noise
campaign is claimed here. DVDD powers up first and stays on throughout analog
restart; AVDD-first, DVDD-loss and retained-charge power-down cases remain open.
Nominal trimming does not resolve every specification or replace those checks.
