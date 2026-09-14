# Release validation — 2026-09-06

These checks validate the assembled workflow. They do not establish full-PVT circuit compliance, production yield, foundry reliability, or post-layout signoff.

## Uploaded work preserved

The following delivered files are byte-identical to the latest uploaded versions, after removing the upload suffix `(1)` from filenames:

| File | SHA-256 |
|---|---|
| Bandgap_Core.sch | 58f6f9b341b831a4b92e24ad496f512d9509ae768cd42937b235b96d72a117d1 |
| Bandgap_Core.sym | 0e1fa99cd49055dc72c617cf8603be1b4795edabdbc4ae00c70c1d05236c4662 |
| Bandgap_Core_LoopProbe.sch | b95d435565e23b058a55d17d81d102e583d4ecbdc26f903db0796afe5d4e4f8b |
| Bandgap_Core_LoopProbe.sym | d7161a4b7e5ae2040b77ea77d9c6b55dccde9e6dd132d1fd7de00af9301cb176 |

The uploaded `validation.json` described structural/software verification of the connected loop probe, with electrical execution still pending in that upload. This release preserves the seven-pin symbol, e/f orientation, M3/N2 gate cuts, C1 connection, disconnected-probe rejection, and OP acceptance gate. That earlier metadata was not treated as a new simulation result or copied into runtime configuration.

## Software checks

`python3 verify_suite.py` passes 12 checks covering:

- exactly one shipped JSON and all nine control entries;
- full-profile case counts and unique case identifiers;
- preserved TB05 smoke default;
- consistent Monte Carlo seeds across V/T;
- exact white-noise and 1/f PSD integration on analytical fixtures;
- readiness requiring the reference to remain inside its target band;
- ordered supply-event points and complete recovery observation windows;
- missing completion/nonfinite waveform rejection;
- disconnected loop-probe rejection;
- MOS terminal mapping using the actual top-level instance name;
- recursive model-dependency discovery;
- rejection of invalid configuration settings.

Python syntax compilation passes for runner, plotter, and checks. All nine schematic path launchers were exercised with `--configure`. The generated schematics and symbols were checked for balanced Tcl syntax. The ZIP excludes caches and contains only one JSON file.

## Representative local simulator execution

Local ngspice runs used private SPICE equivalents parsed from the supplied schematic geometry, with hierarchy and the user's loop-probe orientation preserved. This was **not a full Xschem GUI/netlisting run**. The local public GF180 models were adapted to the uploaded installed-PDK names and this workspace's ngspice compatibility requirements. The adaptations include MOS multiplicity handling and a poly-resistor geometry-argument workaround. Consequently, especially for noise, these runs are workflow checks rather than validation of absolute numbers on the user's installed PDK.

| Check | Executions completed and parsed |
|---|---:|
| TB01–TB05 at nominal 5 V / 25 °C (TC still sweeps temperature) | 5 |
| TB06 three combined-mode seeds | 3 |
| TB07 nominal output noise | 1 |
| TB08 nominal OP/startup, including 63 MOS devices | 1 |
| TB09 smoke ramp, two brownouts, three-cycle sequence, and supply step | 5 |
| TB07 FF/SS × −40/125 °C × 3.0/5.5 V, other corner families typical | 8 |
| TB08 same eight stress combinations | 8 |
| Repeat the three TB06 seeds in separate simulator processes | 3 |

The three repeated seeds produced exactly matching parsed metrics; different seeds produced different reference voltages. These are only three draws and do not support a yield estimate. The smoke and stress cases completed execution, but completion is not a performance pass. Model/simulator warnings were present and were retained in case metadata; they were not suppressed into a clean-PDK certification.

The final nominal dataset produced **43 PNG figures, nine metrics CSVs, one TB08 device CSV, and one combined PDF** through the delivered plotting workflow. Representative Monte Carlo, device-voltage, and repeated-cycle plots were visually inspected; the Monte Carlo seed-axis formatting was corrected. Additional noise/device plots were generated from the eight stress combinations.

## Still required on the actual project environment

Run the smoke profiles through actual Xschem netlisting first, then run the selected full profiles against the exact installed PDK. Full matrices were generated and counted, not all electrically executed here. Confirm noise model suitability and review warnings. Then evaluate performance targets, convergence/timestep sensitivity near failures, statistical sample count and supported mismatch models, device reliability/ERC, and extracted-layout behavior. No area allocation or physical trim implementation was changed or certified by this testbench package.
