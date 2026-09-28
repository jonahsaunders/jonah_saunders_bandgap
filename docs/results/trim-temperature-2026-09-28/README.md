# Temperature-trim results — September 28, 2026

The reference goal is **approximately 1.18 V**. Calibration selects the physical resistor-trim code that minimizes temperature drift, allowing its final voltage to vary. The same code is held across all temperatures and both tested supplies for each process combination.

| Metric | Simulated result |
| --- | ---: |
| Typical process, worst of the two supplies | **2.54 ppm/°C** |
| Median across 45 process combinations | **2.99 ppm/°C** |
| Worst process/supply combination | **5.28 ppm/°C** |
| Previous 65.5 ppm/°C corner with its new code | **3.28 ppm/°C** |
| VREF at 25 °C / 3.3 V across process combinations | **1.173844-1.189266 V** |
| VREF across all selected temperature curves | **1.173776-1.189448 V** |
| Maximum analog supply current in those curves | **54.42 µA** |
| Selected trim codes | **65-98** |
| Dense candidate jobs completed | **135 / 135** |
| Selected-code DC operating points passing self-sustaining checks | **14,940 / 14,940** |

![Temperature drift and calibrated voltage across the 45 process combinations](temperature_drift_after_trim.png)

The left chart subtracts each curve's own 25 °C reference voltage. Solid curves use 3.3 V AVDD; dashed curves use 5 V. The right chart shows each process combination's 25 °C / 3.3 V voltage against its worst box TC across the two supplies. Typical and worst-TC process combinations are highlighted. Each process combination can need a different trim code; the chart does not imply one universal code.

## Scope and calibration method

The physical `Bandgap_Core_Res` was tested at 5 MOS × 3 BJT × 3 resistor corners, with typical MIM and DVDD fixed at 3.3 V. The saved DC screen evaluated all 128 codes at −40, 25 and 125 °C and both 3.3 V and 5 V AVDD. Only codes satisfying the existing self-sustaining operating-point current checks were eligible.

For each process combination, the best code from that three-temperature screen and its immediate neighbors were then simulated from **−40 to 125 °C in 1 °C steps**, at both supplies. All **135 candidate jobs** completed, producing **44,820 DC samples**. The final code minimizes the larger of the two supply-specific box TCs. The published curves contain all **14,940** selected-code points, without downsampling.

The box temperature coefficient is:

```text
TC [ppm/°C] = (maximum VREF − minimum VREF) / mean VREF / 165 °C × 10⁶
```

The mean uses all 166 equally spaced temperatures at one fixed supply. This is a whole-range box metric, not the largest local derivative. The worst observed process/supply is FF MOS / FF BJT / FF resistor at 5 V, code 80: **5.28 ppm/°C**. The typical process uses code 77 and gives **1.184247 V** at 25 °C / 3.3 V, with a worst-of-supplies TC of **2.54 ppm/°C**.

The old 65.5 ppm/°C example was SF MOS / SS BJT / FF resistor, calibrated toward 1.200 V. It now selects code 97 and gives **1.174742 V** at 25 °C / 3.3 V, with a worst-of-supplies TC of **3.28 ppm/°C**. The old figure used three temperatures and a fixed 1.200 V denominator; the new figure uses the dense sweep and mean voltage. The substantial improvement comes from the code choice, rather than the small normalization difference.

### Check of the remaining codes

The untested dense candidates were checked against a lower bound from their saved three-temperature spans. For positive VREF, the dense mean cannot exceed the dense maximum, and adding temperatures cannot shrink the sampled voltage span. Consequently, sampled span / sampled maximum / 165 °C is a lower bound on dense box TC. An allowance of 2 µV on each sampled endpoint was included for numerical differences.

Every remaining code either failed a sampled self-sustaining check or had a lower bound above the selected dense result. No alternative candidate remained unresolved under that screen. Independent saved operating points and the selected dense sweeps agreed within **0.356 µV**. This supports the code selection in these numerical models; it does not establish behavior at every continuous temperature or on every physical chip. The [audit summary](selection_audit.json) records the candidate counts for each process combination.

## Goals supported by these results

- **Approximately 1.18 V nominal**, with a provisional **±1%** output budget: 1.1682-1.1918 V. All published points are inside that band; mismatch and intermediate supply coverage remain pending.
- **≤10 ppm/°C after calibration for minimum drift**. The 5.28 ppm/°C simulated worst case leaves margin to this design target, without establishing a silicon guarantee.
- **≤60 µA analog supply current**. The selected curves reach 54.42 µA maximum; DVDD current is separate.

Calibration on silicon requires measurements at multiple temperatures for each chip. A single room-temperature voltage measurement cannot establish its minimum-drift code. The approximate 1.18 V goal must not be substituted as a new single-temperature calibration target and assumed to reproduce these results.

This fixed-corner, DC-only screen does not qualify random mismatch, post-trim statistical yield, MIM corners, intermediate or stress supplies, startup/restart, trimmed-core stability, PSRR, noise, loading, or extracted layout. It does not resolve the known ngspice transient-abort issue. The existing charge-form MIM compatibility model was retained; no PDK file or circuit was changed for this analysis.

## Data and chart reproduction

- [Selected codes and per-supply metrics](selected_codes.csv): 45 process combinations.
- [Complete selected temperature curves](selected_curves.csv): 14,940 rows, with process, code, supply, temperature, VREF and analog current.
- [Machine-readable summary](summary.json) and [source/data provenance](provenance.json).
- [Chart generator](plot_results.py), using only the checked-in curve CSV and Matplotlib.

From the repository root, regenerate the chart without running SPICE:

```bash
python3 docs/results/trim-temperature-2026-09-28/plot_results.py
```

The original reports, candidate decks, logs, and full traces remain in the local `results/trim_screen_2026-09-28/` and `results/trim_tc_2026-09-28/` folders. The ordinary TB10 runner still uses its documented legacy 1.194 V voltage-calibration criterion; this publication records the separate temperature-first analysis. No historical pass/fail results were relabeled.

[Return to project specifications](../../../README.md#projected-post-trim-specifications)
