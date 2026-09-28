# Simulation guide

[Overview](../README.md) · [Results](RESULTS.md) · [Testbenches](TESTBENCHES.md) · [Measurement details](TESTBENCH_DETAILS.md) · [Validation notes](../VALIDATION.md)

Complete the README's installation and smoke check first. Run the commands below from the repository root in Bash inside the configured Linux/FOSS environment. In each new terminal, reactivate your Python environment if used and select the complete GF180 tool setup:

```bash
source /foss/tools/sak/sak-pdk-script.sh gf180mcuD
```

This updates PDK paths and ngspice startup settings together. The interactive equivalent is `sak-pdk gf180mcuD`. Relaunch any Xschem window opened under another PDK.

## Profiles and configuration

All ten benches use [bandgap_config.json](../bandgap_config.json).

| Profile | Use |
| --- | --- |
| `full` | Complete configured corner coverage; the supplied default for every bench, including TB10 |
| `smoke` | Short TT / 25 °C / 5 V workflow check; TB10 also calibrates at 3.3 V |
| `loop_smoke` | Nominal TB05 check with retained waveforms |
| `trim_nominal` | TB10 TT / 25 °C check at 3.3 V and 5 V |

Settings apply in order: `defaults`, `test_overrides`, then the selected profile. A command-line `--profile` overrides the JSON's `default_profile` / `test_profiles` selection. For GUI smoke runs, set `default_profile` and both TB05/TB10 entries in `test_profiles` to `smoke`; restore all three to `full` afterward.

`output_directory` defaults to `results` relative to the JSON file. `--results-root PATH` overrides that root and appends the profile. Other settings include PVT axes, `parallel_jobs`, timeout, waveform retention, and measurement thresholds. TB01-TB03 retain legacy control templates in `controls`; changing a target requires updating its applicable controls/math as well as shared defaults.

Preview a schedule without netlisting or running ngspice:

```bash
python3 run_bandgap.py --test TB10_RESISTOR_TRIM --profile full --list-cases
```

## Run a full suite in a separate folder

Choose a new `RUN_ROOT` when the circuit, runner, configuration, or model inputs change. Reuse that same path when resuming the same version. Keep the previous results directory as your baseline.

This block regenerates all ten netlists, runs each bench, and plots the results. Benches run sequentially; each runner uses the profile's `parallel_jobs` setting. A runner failure is reported and the remaining benches continue.

```bash
(
  set -e
  source /foss/tools/sak/sak-pdk-script.sh gf180mcuD
  SUITE_PROFILE=full
  RUN_ROOT="results/my_full_run"
  NETLIST_DIR="/headless/.xschem/simulations"
  mkdir -p "$NETLIST_DIR"

  for sch in TB[0-9][0-9]_*.sch; do
    bench="${sch%.sch}"
    xschem -n -x -q -r -s -o "$NETLIST_DIR" \
      -N "$bench.spice" "$sch"
    test -s "$NETLIST_DIR/$bench.spice"
  done

  failed=0
  for sch in TB[0-9][0-9]_*.sch; do
    bench="${sch%.sch}"
    python3 run_bandgap.py --test "$bench" \
      --deck "$NETLIST_DIR/$bench.spice" \
      --profile "$SUITE_PROFILE" --results-root "$RUN_ROOT" \
      --retry-failed || {
        echo "CHECK ERRORS: $bench"
        failed=1
      }
  done

  python3 plot_bandgap.py --results "$RUN_ROOT/$SUITE_PROFILE"
  exit "$failed"
)
```

Set `SUITE_PROFILE=smoke` for a short all-bench workflow check. A full run can take substantial time, especially TB03, TB09, and TB10. Keep the terminal/container running. `--max-cases` is a debug limit and intentionally leaves incomplete coverage.

To run one bench, netlist its schematic and use the same runner command with its full test name. TB10 can run independently to fill missing trim coverage; TB01-TB09 do not need to run again for that reason alone.

## Preserve old data and rerun selected issues

Every run rewrites its consolidated report. For TB01-TB09, an incompatible cache can replace old case artifacts. **`--retry-failed` is not a backup:** it retries execution failures, not completed simulations that miss specifications.

Prepare a separate folder containing frozen source/config files, baseline report hashes, and exact TB03/TB09 selections:

```bash
python3 prepare_reruns.py --from-results results/full --to results/my_recheck
bash results/my_recheck/run_selected.sh plan
```

Preparation starts no simulation and refuses an existing destination. `plan` only prints coverage. Once prepared, run one command at a time:

```bash
bash results/my_recheck/run_selected.sh TB05
bash results/my_recheck/run_selected.sh TB03
bash results/my_recheck/run_selected.sh TB09
# Full held-code trim sweep; run separately when ready:
bash results/my_recheck/run_selected.sh TB10
```

TB05 and TB10 run their complete configured grids. TB03/TB09 select all execution failures plus nominal readiness misses with valid reference levels. Offset-only misses are excluded from these debug subsets, not resolved. The September 27-28 baseline produces 65 TB03 and 458 TB09 cases.

The launcher regenerates a matching netlist from the frozen source and writes to `results/my_recheck/full/`, with separate plot folders for each bench. Repeat the same command to resume. After circuit or test-method changes, prepare another folder: editing the main checkout does not update an existing snapshot.

For manual selections, `--case-ids-file PATH` accepts one exact case ID per line. Empty, duplicate, or unknown selections are rejected. A completed subset can return success while `full_grid_complete` remains false; its report includes `INCOMPLETE_FULL_GRID_SELECTED_CASES_ONLY`. Full regression remains necessary after relevant circuit changes.

## Reports, resume, and plots

The default output hierarchy is:

```text
results/<profile>/TBxx_NAME_UPLOAD_THIS.txt
results/<profile>/TBxx_NAME/cases/<case_id>/result.json
results/<profile>/TBxx_NAME/cases/<case_id>/waveforms.txt.gz
results/<profile>/plots/bandgap_plots.pdf
```

Reports contain coverage, configuration, per-case metrics, simulator warnings, and a summary. Share the relevant `UPLOAD_THIS.txt` file; include the plots or compressed waveforms for curve-level review. Failed cases retain available decks/logs. Successful waveforms remain compressed even when `retain_waveforms` is false; that flag controls other raw artifacts. TB10 retains separate attempt artifacts as described in the [testbench reference](TESTBENCH_DETAILS.md#tb10-physical-resistor-trim-and-selected-code-startup).

Resume requires a matching fingerprint of configuration, controls, deck, runner, simulator executable, and discovered model dependencies. A wrapper executable does not automatically fingerprint its external target/environment. Source updates can invalidate old caches, which is why revised runs should use new output folders.

| Exit code | Meaning |
| --- | --- |
| `0` | All requested simulations executed and parsed; performance may still fail, and a requested subset is still partial coverage |
| `1` | Configuration or preflight error |
| `2` | Execution failures or an incomplete debug-limited run |

A preflight failure may occur before a new report is written. Check the console and report fingerprint; an older report is not evidence that the latest attempt started.

Replotting uses saved data and does not run ngspice. To preserve the existing figures, choose a new destination:

```bash
python3 plot_bandgap.py --results results/full \
  --out results/full/plots_review --max-waveforms 6
```

Other useful commands:

```bash
python3 plot_bandgap.py                    # discover every profile
python3 plot_bandgap.py --profile full      # one profile
python3 plot_bandgap.py --profile smoke --test TB07_NOISE
```

Plots include per-bench PNGs, a combined PDF, and metrics CSVs. Detailed waveform panels normally show up to 24 evenly selected traces; that selection is not a worst-case guarantee. `--max-waveforms 0` displays every available waveform trace. TB05 separately displays up to 12 curves per cut, including the smallest observed margins/distances; distributions use all accepted records. Worst-case metrics use all reported cases.

The plotter checks fingerprints before loading cached waveforms. `--no-pdf`, `--no-csv`, and `--dpi` control output. Keep the plotter and runner together so loop reconstruction matches the measurement implementation.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Missing core symbol | Keep the corresponding `.sch` and `.sym` beside the bench; reopen the complete updated project. |
| Missing GF180 devices | Run the full GF180 selector above, relaunch Xschem, and regenerate the affected netlist. |
| Missing model file | Correct the paths in the bench's `MODELS` block and regenerate the netlist. |
| GUI cannot find the runner or deck | Close the bench, rerun `--configure` with the actual netlist directory, reopen, and netlist again. |
| `No module named fcntl` | Use Linux/FOSS rather than native Windows Python. |
| TB10 runs `trim_nominal` during a full suite | Update the runner, JSON, and suite command together; older instructions forced that profile. |
| Updated results replace earlier files | Use a new results root or prepared snapshot for the changed source version. |

Git ignores generated results. Fetching a branch does not back up those files, and simulation commands can still replace them. Preserve uncommitted schematic edits before switching branches; use complete matching project revisions rather than mixing individual old/new files.

## Software and symbol checks

```bash
python3 verify_suite.py
python3 verify_plotting.py
python3 verify_xschem_symbols.py
```

The suite checks use the Python standard library. Plot checks need NumPy and Matplotlib. Symbol checks need the configured GF180/Xschem environment and generate temporary netlists, including moved-folder and closed-probe equivalence checks. These commands do not run electrical simulations. Recorded results and model provenance are in [VALIDATION.md](../VALIDATION.md) and the [testbench reference](TESTBENCH_DETAILS.md#model-provenance).
