#!/usr/bin/env python3
"""Plot every result the GF180 bandgap benches produce.

Reads the consolidated reports written by run_bandgap.py (and, where the run
retained them, the per-case waveform files) and writes figures, a per-test
metrics CSV, and one combined PDF into a "plots" folder inside the same single
output_directory.

    python3 plot_bandgap.py                      # everything that exists
    python3 plot_bandgap.py --test TB05_LOOP_STABILITY
    python3 plot_bandgap.py --out ~/bandgap_figs --dpi 200

Needs matplotlib and numpy. run_bandgap.py is imported when it sits alongside
this file, so the loop-gain reconstruction and waveform parsing stay in one
place; without it the loop plots fall back to the sampled curve in the report.
"""
import argparse
import gzip
import subprocess
import csv
import importlib.util
import json
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG_NAME = 'bandgap_config.json'
TESTS = ('TB01_PSRR', 'TB02_LINE_REGULATION', 'TB03_STARTUP_RESTART',
         'TB04_TEMPERATURE', 'TB05_LOOP_STABILITY', 'TB06_MONTE_CARLO',
         'TB07_NOISE', 'TB08_POWER_DEVICE_LIMITS', 'TB09_SUPPLY_DISTURBANCE')
VREF_TARGET = 1.194

try:
    import numpy as np
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.colors import LinearSegmentedColormap, Normalize
    from matplotlib.cm import ScalarMappable
    from matplotlib.lines import Line2D
    from matplotlib.ticker import FuncFormatter, MaxNLocator
except ImportError as exc:  # pragma: no cover - environment problem, not a data problem
    sys.exit('plot_bandgap.py needs matplotlib and numpy: pip install --user matplotlib\n'
             '(import failed: %s)' % exc)


# --------------------------------------------------------------------------
# Palette. Validated categorical slots, one sequential blue ramp, fixed status
# colours. Series identity is never carried by colour alone: every multi-series
# figure also carries a legend, and ordered quantities get a colourbar.
# --------------------------------------------------------------------------
SURFACE = '#fcfcfb'
INK = '#0b0b0b'
INK2 = '#52514e'
MUTED = '#898781'
GRID = '#e1e0d9'
AXIS = '#c3c2b7'
CAT = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#e34948']
BLUE_RAMP = ['#cde2fb', '#b7d3f6', '#9ec5f4', '#86b6ef', '#6da7ec', '#5598e7', '#3987e5',
             '#2a78d6', '#256abf', '#1c5cab', '#184f95', '#104281', '#0d366b']
SEQ = LinearSegmentedColormap.from_list('bg_blue', BLUE_RAMP[3:])   # from step 250, stays visible
GOOD, WARNING, CRITICAL = '#0ca30c', '#fab219', '#d03b3b'
TEMP_STEPS = ['#86b6ef', '#2a78d6', '#104281']   # ordinal: cold -> hot, validated

plt.rcParams.update({
    'figure.facecolor': SURFACE, 'axes.facecolor': SURFACE, 'savefig.facecolor': SURFACE,
    'axes.edgecolor': AXIS, 'axes.labelcolor': INK2, 'axes.titlecolor': INK,
    'axes.titlesize': 11, 'axes.titleweight': 'bold', 'axes.labelsize': 9.5,
    'axes.grid': True, 'axes.axisbelow': True, 'axes.spines.top': False, 'axes.spines.right': False,
    'grid.color': GRID, 'grid.linewidth': 0.8,
    'xtick.color': MUTED, 'ytick.color': MUTED, 'xtick.labelsize': 8.5, 'ytick.labelsize': 8.5,
    'text.color': INK, 'font.size': 9.5, 'font.family': 'sans-serif',
    'lines.linewidth': 2.0, 'legend.frameon': False, 'legend.fontsize': 8.5,
    'figure.dpi': 110, 'axes.formatter.useoffset': False,
})


def finite(values):
    return [v for v in values
            if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)]


def auto_fmt(values, digits=4):
    """Significant-digit formatting: readable for microvolts and for megahertz alike."""
    return '%.' + str(digits) + 'g'


def flat_range(vals, rel=1e-6):
    """True when a series is constant to within `rel` — a staircase would be a lie."""
    lo, hi = min(vals), max(vals)
    return (hi - lo) <= max(abs(hi), abs(lo), 1e-30) * rel


def ecdf(ax, values, xlabel, limit=None, limit_label='', worse='below', unit=''):
    """Cumulative distribution over completed cases, honest about a constant series."""
    vals = sorted(finite(values))
    if not vals:
        return False
    flat = flat_range(vals)
    if flat:
        ax.axvline(vals[0], color=CAT[0], linewidth=2.4)
        ax.annotate('all %d cases at %.6g%s' % (len(vals), vals[0], (' ' + unit) if unit else ''),
                    xy=(0.5, 0.55), xycoords='axes fraction', ha='center', fontsize=9, color=INK2)
    else:
        ax.plot(vals, np.arange(1, len(vals)+1)/len(vals)*100, color=CAT[0], linewidth=2.2)
    # Keep the threshold in view even when every case lands far from it, and never
    # let a constant series collapse the axis to zero width.
    edges = [vals[0], vals[-1]] + ([limit] if limit is not None else [])
    lo, hi = min(edges), max(edges)
    pad = (hi - lo) * 0.05 or max(abs(lo) * 0.05, 1e-9)
    ax.set_xlim(lo - pad, hi + pad)
    ax.set_ylim(0, 100)
    ax.set_xlabel(xlabel)
    ax.set_ylabel('Cases at or below (%)')
    ax.xaxis.set_major_locator(MaxNLocator(nbins=5))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _p: '%.4g' % v))
    if limit is not None:
        ax.axvline(limit, color=CRITICAL, linewidth=1.4, linestyle=(0, (5, 3)))
        ax.annotate(limit_label, xy=(limit, 0.04), xycoords=('data', 'axes fraction'),
                    xytext=(5, 0), textcoords='offset points', fontsize=8, color=CRITICAL)
        bad = sum(1 for v in vals if (v < limit if worse == 'below' else v > limit))
        ax.set_title('%d of %d cases %s the limit' % (bad, len(vals),
                                                      'below' if worse == 'below' else 'above'),
                     loc='left')
    return True


def temp_color(temp, all_temps):
    ordered = sorted(set(all_temps))
    if len(ordered) <= len(TEMP_STEPS):
        return TEMP_STEPS[ordered.index(temp) * max(1, len(TEMP_STEPS) // max(1, len(ordered)))
                          if len(ordered) > 1 else 1]
    lo, hi = min(ordered), max(ordered)
    return SEQ(0.15 + 0.85 * ((temp - lo) / (hi - lo) if hi > lo else 0.5))


def supply_color(v, all_v):
    lo, hi = min(all_v), max(all_v)
    return SEQ(0.15 + 0.85 * ((v - lo) / (hi - lo) if hi > lo else 0.5))


def supply_colorbar(fig, axes, supplies, label='Supply (V)'):
    if len(set(supplies)) < 2:
        return
    sm = ScalarMappable(norm=Normalize(min(supplies), max(supplies)), cmap=SEQ)
    cb = fig.colorbar(sm, ax=axes, pad=0.015, fraction=0.03)
    cb.set_label(label, color=INK2, fontsize=9)
    cb.ax.tick_params(colors=MUTED, labelsize=8)
    cb.outline.set_visible(False)


def note(ax, text):
    """A caption under an axes, for the caveats that belong with the numbers."""
    ax.annotate(text, xy=(0, -0.19), xycoords='axes fraction', fontsize=8,
                color=MUTED, va='top', ha='left', wrap=True)


def threshold(ax, y, label, color=CRITICAL, axis='y'):
    fn = ax.axhline if axis == 'y' else ax.axvline
    fn(y, color=color, linewidth=1.4, linestyle=(0, (5, 3)), zorder=1)
    if axis == 'y':
        ax.annotate(label, xy=(0.995, y), xycoords=('axes fraction', 'data'),
                    ha='right', va='bottom', fontsize=8, color=color)


# --------------------------------------------------------------------------
# Reading what a run produced
# --------------------------------------------------------------------------
def load_runner():
    """Reuse run_bandgap.py's parsers so the two files cannot drift apart."""
    path = HERE/'run_bandgap.py'
    if not path.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location('run_bandgap', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception as exc:
        print('  note: could not import run_bandgap.py (%s); using built-in parsers' % exc)
        return None


RB = load_runner()


def output_directory(config):
    """The single results folder, from the one settings file."""
    doc = json.loads(Path(config).read_text())
    if 'output_directory' not in doc:
        raise ValueError('No output_directory in ' + str(config))
    root=Path(doc['output_directory']).expanduser()
    return root if root.is_absolute() else Path(config).resolve().parent/root


def read_report(path):
    """Split a TBxx_UPLOAD_THIS.txt into its header, per-case records and summary."""
    head, cases, summary, tail = {}, [], None, []
    for line in path.read_text(errors='replace').splitlines():
        if line.startswith('CASE '):
            try:
                cases.append(json.loads(line[5:]))
            except json.JSONDecodeError:
                pass
        elif line.startswith('SUMMARY '):
            summary = json.loads(line[8:])
        elif line.startswith('COVERAGE '):
            head['coverage'] = json.loads(line[9:])
        elif line.startswith('PROFILE '):
            head['profile'] = line[8:].strip()
        elif line.startswith('RESUME_FINGERPRINT '):
            head['fingerprint']=line.split(None,1)[1].strip()
        elif line.startswith(('END_OF_', 'INCOMPLETE_', 'COVERAGE_HAS_',
                              'ALL_PLANNED_')):
            tail.append(line.strip())
    return head, cases, summary or {}, tail


def blocks(text):
    if RB is not None:
        return RB.blocks(text)
    out, active = {}, None
    for line in text.splitlines():
        if line.startswith('BEGIN_'):
            active = line[6:].strip(); out[active] = []
        elif line.startswith('END_'):
            active = None
        elif active:
            try:
                row = [float(x) for x in line.split()]
            except ValueError:
                continue
            if len(row) >= 3 and all(math.isfinite(x) for x in row):
                out[active].append(row)
    return out


def waveform_rows(text):
    if RB is not None:
        try:
            return RB.waveform_rows(text)
        except ValueError:
            return []
    rows, active = [], False
    for line in text.splitlines():
        if line.startswith(('BEGIN_AC_DATA', 'BEGIN_DC_DATA', 'BEGIN_TRAN_DATA')):
            active = True; continue
        if line.startswith(('END_AC_DATA', 'END_DC_DATA', 'END_TRAN_DATA')):
            active = False
        if active:
            try:
                values = [float(x) for x in line.split()]
            except ValueError:
                continue
            if len(values) >= 3 and all(math.isfinite(x) for x in values):
                rows.append(values)
    return rows


def cached_cases(root, test, fingerprint):
    """Per-case result.json files, which outlive a truncated or in-progress report."""
    out = []
    cdir = root/test/'cases'
    if not cdir.is_dir():
        return out
    for f in sorted(cdir.glob('*/result.json')):
        try:
            case=json.loads(f.read_text())
            if fingerprint and case.get('fingerprint')==fingerprint: out.append(case)
        except (OSError, json.JSONDecodeError):
            continue
    return out


def progress(test, head, cases):
    """Cases carry their own elapsed_seconds, so a partial run can project its finish."""
    timed = finite([c.get('elapsed_seconds') for c in cases if not c.get('resumed')])
    if not timed or RB is None or not head.get('coverage'):
        return
    try:
        planned = len(list(RB.cases(head['coverage'], test)))
    except Exception:
        return
    timed.sort()
    mid = timed[len(timed)//2]
    jobs = max(1, int(head['coverage'].get('parallel_jobs', 1)))
    print('%-22s   %d of %d cases done · median %.1f s/case · %.1f s at the 90th percentile'
          % ('', len(cases), planned, mid, timed[min(len(timed)-1, int(len(timed)*0.9))]))
    if len(cases) < planned:
        hours = (planned - len(cases)) * mid / jobs / 3600
        print('%-22s   ~%.1f h left at parallel_jobs=%d (%.1f h at %d)'
              % ('', hours, jobs, hours * jobs / (jobs*4), jobs*4))


def diagnose(root, test, report, head, tail):
    """Say why a bench produced nothing, rather than shrugging at an empty report."""
    print('%-22s no plottable cases' % test)
    size = report.stat().st_size
    print('%-22s   %s is %d bytes and holds no CASE lines' % ('', report.name, size))
    finished = [m for m in tail if m.startswith(('END_OF_', 'INCOMPLETE_'))]
    print('%-22s   %s' % ('', 'run reached its end marker (%s)' % finished[0] if finished
                          else 'no end marker: the run did not finish — killed, interrupted, '
                               'or still going'))
    if RB is not None and head.get('coverage'):
        try:
            planned = len(list(RB.cases(head['coverage'], test)))
            print('%-22s   %d cases were planned for profile %s'
                  % ('', planned, head.get('profile', '?')))
        except Exception:
            pass
    cdir = root/test/'cases'
    dirs = sorted(d for d in cdir.iterdir() if d.is_dir()) if cdir.is_dir() else []
    if not dirs:
        print('%-22s   %s is empty, so not one case has started' % ('', cdir))
        print('%-22s   try one case first: run_bandgap.py --test %s --deck <deck> --max-cases 1'
              % ('', test))
        return
    done = sum(1 for d in dirs if (d/'result.json').is_file())
    print('%-22s   %d case folder(s) under %s, %d with a result.json'
          % ('', len(dirs), cdir, done))
    logs = [d/'run.log' for d in dirs if (d/'run.log').is_file()]
    if logs:
        newest = max(logs, key=lambda p: p.stat().st_mtime)
        lines = [l for l in newest.read_text(errors='replace').splitlines() if l.strip()][-6:]
        print('%-22s   newest log %s:' % ('', newest.parent.name + '/run.log'))
        for l in lines:
            print('%-22s     %s' % ('', l[:150]))
    else:
        print('%-22s   no run.log yet: ngspice has not written anything for this bench' % '')


def retained_waveforms(root, test, cases, max_waveforms=24):
    """Bound plot memory; use current-fingerprint, successful case traces only.
    Metrics/CSV still include ALL cases. --max-waveforms 0 draws all traces.
    """
    eligible=sorted(complete(cases),key=lambda c:c['case_id'])
    if max_waveforms and len(eligible)>max_waveforms:
        indices=np.linspace(0,len(eligible)-1,max_waveforms,dtype=int)
        eligible=[eligible[i] for i in indices]
        print('  Waveform display sampled to %d cases; all metrics remain included.' % max_waveforms)
    out={}
    for case in eligible:
        d=root/test/'cases'/case['case_id']; cache=d/'result.json'
        if not cache.is_file(): continue
        saved=json.loads(cache.read_text())
        if saved.get('fingerprint')!=case.get('fingerprint') or saved.get('status')!='complete': continue
        gz=d/'waveforms.txt.gz'; raw=d/'case_report.txt'
        if gz.is_file():
            with gzip.open(gz,'rt') as z: text=z.read()
        elif raw.is_file(): text=raw.read_text(errors='replace')
        else: continue
        out[case['case_id']]=(case,text)
    return out


# --------------------------------------------------------------------------
# CSV
# --------------------------------------------------------------------------
def flatten(prefix, value, into):
    if isinstance(value, dict):
        for k, v in value.items():
            flatten(prefix + ('.' if prefix else '') + str(k), v, into)
    elif isinstance(value, list):
        into[prefix + '.count'] = len(value)
        if value and not isinstance(value[0], (dict, list)):
            into[prefix] = ' '.join(str(x) for x in value)
    else:
        into[prefix] = value


def write_csv(path, cases):
    rows = []
    for c in cases:
        flat = {}
        for k, v in c.items():
            if k in ('fingerprint', 'log_tail'):
                continue
            if k == 'metrics':
                flatten('', v, flat)
            else:
                flatten(k, v, flat)
        rows.append(flat)
    if not rows:
        return None
    fields, seen = [], set()
    for r in rows:
        for k in r:
            if k not in seen:
                seen.add(k); fields.append(k)
    lead = [f for f in ('case_id', 'status', 'mos', 'bjt', 'res', 'mim',
                        'temperature_C', 'vdd_V', 'range') if f in seen]
    fields = lead + [f for f in fields if f not in lead]
    with path.open('w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return path


# --------------------------------------------------------------------------
# Shared building blocks
# --------------------------------------------------------------------------
def complete(cases):
    return [c for c in cases if c.get('status') == 'complete' and c.get('metrics')]


def status_figure(test, cases, summary, head):
    """One overview per test: how many cases ran, and how they were distributed."""
    counts = {}
    for c in cases:
        counts[c.get('status', 'unknown')] = counts.get(c.get('status', 'unknown'), 0) + 1
    if not counts:
        return None
    order = [s for s in ('complete', 'failed', 'timeout') if s in counts]
    order += [s for s in counts if s not in order]
    colors = {'complete': GOOD, 'failed': CRITICAL, 'timeout': WARNING}
    fig, ax = plt.subplots(figsize=(7.5, 3.1))
    bars = ax.barh(order, [counts[s] for s in order],
                   color=[colors.get(s, CAT[0]) for s in order], height=0.55)
    for b, s in zip(bars, order):
        ax.annotate('%d' % counts[s], xy=(b.get_width(), b.get_y() + b.get_height()/2),
                    xytext=(6, 0), textcoords='offset points', va='center',
                    fontsize=9, color=INK2)
    ax.invert_yaxis()
    ax.xaxis.grid(True); ax.yaxis.grid(False)
    ax.set_xlabel('Cases')
    planned = summary.get('planned_cases')
    sub = 'profile %s' % head.get('profile', '?')
    if planned:
        sub += '  ·  %d of %d planned cases in this report' % (len(cases), planned)
    ax.set_title('%s — case outcomes\n%s' % (test, sub), loc='left')
    ax.set_xlim(0, max(counts.values()) * 1.15)
    note(ax, 'Simulation complete is not a performance pass; the metric figures carry the verdicts.')
    fig.tight_layout()
    return fig


def heatmap(ax, rows, cols, grid, fmt=None, cmap=SEQ, label=''):
    data = np.array(grid, dtype=float)
    fmt = fmt or auto_fmt([v for row in grid for v in row])
    masked = np.ma.masked_invalid(data)
    im = ax.imshow(masked, cmap=cmap, aspect='auto')
    ax.set_xticks(range(len(cols)), [str(c) for c in cols])
    ax.set_yticks(range(len(rows)), [str(r) for r in rows])
    ax.grid(False)
    for sp in ax.spines.values():
        sp.set_visible(False)
    # Every cell is labelled, so the colour is a scan aid rather than the only channel.
    vmin, vmax = (masked.min(), masked.max()) if masked.count() else (0, 1)
    for i in range(len(rows)):
        for j in range(len(cols)):
            if masked.mask.any() and np.ma.getmaskarray(masked)[i, j]:
                ax.annotate('—', (j, i), ha='center', va='center', fontsize=8, color=MUTED)
                continue
            rel = (data[i, j] - vmin) / (vmax - vmin) if vmax > vmin else 0.5
            ax.annotate(fmt % data[i, j], (j, i), ha='center', va='center', fontsize=8,
                        color='#ffffff' if rel > 0.55 else INK)
    if label:
        ax.set_title(label, loc='left')
    return im


def axis_of(cases, key):
    return sorted({c[key] for c in cases if c.get(key) is not None})


def grid_by(cases, rowkey, colkey, value):
    rows, cols = axis_of(cases, rowkey), axis_of(cases, colkey)
    grid = [[float('nan')] * len(cols) for _ in rows]
    for c in cases:
        try:
            i, j = rows.index(c[rowkey]), cols.index(c[colkey])
        except (ValueError, KeyError):
            continue
        v = value(c)
        if v is None or not math.isfinite(v):
            continue
        cur = grid[i][j]
        grid[i][j] = v if math.isnan(cur) else min(cur, v) if value.worst == 'min' else max(cur, v)
    return rows, cols, grid


def worst_grid(cases, rowkey, colkey, get, worst):
    fn = get
    fn.worst = worst
    return grid_by(cases, rowkey, colkey, fn)


def by_temperature(ax, cases, xkey, get, temps, marker='o'):
    """One line per temperature over an ordered x axis, with a legend."""
    drew = False
    for t in temps:
        pts = sorted(((c[xkey], get(c)) for c in cases
                      if c.get('temperature_C') == t and get(c) is not None
                      and c.get(xkey) is not None), key=lambda p: p[0])
        if not pts:
            continue
        xs = sorted({p[0] for p in pts})
        ys = [min(v for x, v in pts if x == xv) for xv in xs]
        ax.plot(xs, ys, marker=marker, markersize=5, color=temp_color(t, temps),
                label='%g °C' % t)
        drew = True
    if drew and len(temps) > 1:
        ax.legend(title='Temperature', title_fontsize=8.5, loc='best', labelcolor=INK2)
    return drew


def nominal_band(ax, head, key_lo='nominal_supply_min_V', key_hi='nominal_supply_max_V'):
    cov = head.get('coverage', {})
    if key_lo in cov and key_hi in cov:
        ax.axvspan(cov[key_lo], cov[key_hi], color=BLUE_RAMP[0], alpha=0.45, zorder=0, lw=0)
        ax.annotate('nominal supply', xy=(cov[key_lo], 1.0), xycoords=('data', 'axes fraction'),
                    xytext=(4, -10), textcoords='offset points', fontsize=8, color=MUTED)


# --------------------------------------------------------------------------
# TB01 — PSRR
# --------------------------------------------------------------------------
def figures_tb01(test, head, cases, summary, waves):
    figs, ok = [], complete(cases)
    temps = axis_of(ok, 'temperature_C')

    if waves:
        fig, ax = plt.subplots(figsize=(8.6, 5.0))
        supplies = [c['vdd_V'] for c, _ in waves.values() if c.get('vdd_V')] or [5.0]
        worst = None
        for case, text in waves.values():
            rows = waveform_rows(text)
            if not rows:
                continue
            f = np.array([r[0] for r in rows]); db = np.array([r[1] for r in rows])
            ax.semilogx(f, db, color=supply_color(case.get('vdd_V', 5.0), supplies),
                        linewidth=1.4, alpha=0.85 if len(waves) < 12 else 0.5)
            band = db[f <= 1e6]
            if band.size and (worst is None or band.min() < worst[0]):
                worst = (band.min(), f, db, case)
        if worst:
            ax.semilogx(worst[1], worst[2], color=CAT[1], linewidth=2.4, zorder=5,
                        label='worst retained: %s (%.1f dB)' % (worst[3]['case_id'], worst[0]))
            ax.legend(loc='lower left', labelcolor=INK2)
        ax.axvspan(1, 1e6, color=BLUE_RAMP[0], alpha=0.35, zorder=0, lw=0)
        threshold(ax, 60, '60 dB target')
        ax.set_xlabel('Frequency (Hz)'); ax.set_ylabel('PSRR (dB)')
        ax.set_title('%s — PSRR vs frequency, %d retained case(s)' % (test, len(waves)), loc='left')
        supply_colorbar(fig, ax, supplies)
        note(ax, 'Shaded band is the 1 Hz – 1 MHz specification window. Curves come only from cases '
                 'whose profile set retain_waveforms true.')
        fig.tight_layout(); figs.append(fig)

    if ok:
        get = lambda c: c['metrics'].get('psrr_min_1hz_1mhz_db')
        fig, ax = plt.subplots(figsize=(8.0, 4.6))
        nominal_band(ax, head)
        if by_temperature(ax, ok, 'vdd_V', get, temps):
            threshold(ax, 60, '60 dB target')
            ax.set_xlabel('Supply (V)'); ax.set_ylabel('Worst PSRR in 1 Hz – 1 MHz (dB)')
            ax.set_title('%s — worst-case PSRR across the supply sweep' % test, loc='left')
            note(ax, 'Each point is the worst corner combination at that supply and temperature.')
            fig.tight_layout(); figs.append(fig)
        else:
            plt.close(fig)

        fig, ax = plt.subplots(figsize=(8.0, 4.6))
        if ecdf(ax, [get(c) for c in ok], 'Worst PSRR in 1 Hz – 1 MHz (dB)',
                limit=60, limit_label='60 dB target', worse='below', unit='dB'):
            ax.set_title('%s — PSRR distribution over %d completed cases\n%s'
                         % (test, len(ok), ax.get_title(loc='left')), loc='left')
            fig.tight_layout(); figs.append(fig)
        else:
            plt.close(fig)

        if len(axis_of(ok, 'mos')) > 1 or len(axis_of(ok, 'vdd_V')) > 1:
            rows, cols, grid = worst_grid(ok, 'mos', 'vdd_V',
                                          lambda c: c['metrics'].get('psrr_min_1hz_1mhz_db'), 'min')
            fig, ax = plt.subplots(figsize=(max(6.5, 1.0*len(cols)+3.5), 0.55*len(rows)+2.6))
            im = heatmap(ax, rows, cols, grid)
            ax.set_xlabel('Supply (V)'); ax.set_ylabel('MOS corner')
            ax.set_title('%s — worst PSRR (dB) per MOS corner and supply' % test, loc='left')
            cb = fig.colorbar(im, ax=ax, pad=0.015, fraction=0.03)
            cb.set_label('dB', color=INK2, fontsize=9); cb.outline.set_visible(False)
            cb.ax.tick_params(colors=MUTED, labelsize=8)
            note(ax, 'Minimum over BJT, resistor, MIM corners and temperature. Darker is better.')
            fig.tight_layout(); figs.append(fig)

        fig, axes = plt.subplots(2, 1, figsize=(8.0, 6.2), sharex=True)
        drew = by_temperature(axes[0], ok, 'vdd_V', lambda c: c['metrics'].get('op_vref_v'), temps)
        by_temperature(axes[1], ok, 'vdd_V', lambda c: c['metrics'].get('op_idd_ua'), temps)
        if drew:
            axes[0].axhspan(VREF_TARGET*0.995, VREF_TARGET*1.005, color=BLUE_RAMP[0],
                            alpha=0.5, zorder=0, lw=0)
            axes[0].axhline(VREF_TARGET, color=MUTED, linewidth=1.2, linestyle=(0, (5, 3)))
            axes[0].set_ylabel('VREF at operating point (V)')
            axes[1].set_ylabel('Supply current (µA)')
            axes[1].set_xlabel('Supply (V)')
            axes[0].set_title('%s — operating point across the supply sweep' % test, loc='left')
            note(axes[1], 'Shaded band on the upper axes is 1.194 V ±0.5%. Separate axes rather '
                          'than a second y-scale, so neither curve distorts the other.')
            fig.tight_layout(); figs.append(fig)
        else:
            plt.close(fig)
    return figs


# --------------------------------------------------------------------------
# TB02 — line regulation
# --------------------------------------------------------------------------
def figures_tb02(test, head, cases, summary, waves):
    figs, ok = [], complete(cases)
    temps = axis_of(ok, 'temperature_C')

    if waves:
        fig, axes = plt.subplots(2, 1, figsize=(8.6, 6.4), sharex=True)
        for case, text in waves.values():
            rows = waveform_rows(text)
            if not rows:
                continue
            v = np.array([r[0] for r in rows])
            axes[0].plot(v, [r[1] for r in rows], color=temp_color(case.get('temperature_C', 25), temps),
                         linewidth=1.4, alpha=0.85 if len(waves) < 12 else 0.5)
            axes[1].plot(v, [r[2] for r in rows], color=temp_color(case.get('temperature_C', 25), temps),
                         linewidth=1.4, alpha=0.85 if len(waves) < 12 else 0.5)
        nominal_band(axes[0], head); nominal_band(axes[1], head)
        axes[0].axhline(VREF_TARGET, color=MUTED, linewidth=1.2, linestyle=(0, (5, 3)))
        axes[0].axhspan(VREF_TARGET*0.995, VREF_TARGET*1.005, color=BLUE_RAMP[0], alpha=0.5, zorder=0, lw=0)
        axes[0].set_ylabel('VREF (V)'); axes[1].set_ylabel('Supply current (µA)')
        axes[1].set_xlabel('Supply (V)')
        axes[0].set_title('%s — DC sweeps, %d retained case(s)' % (test, len(waves)), loc='left')
        if len(temps) > 1:
            axes[0].legend(handles=[Line2D([], [], color=temp_color(t, temps), label='%g °C' % t)
                                    for t in temps], title='Temperature', title_fontsize=8.5,
                           loc='best', labelcolor=INK2)
        note(axes[1], 'Shaded column is the nominal supply window; the band on the upper axes is '
                      '1.194 V ±0.5%.')
        fig.tight_layout(); figs.append(fig)

    for group, title in [('nominal', 'nominal 3.3–5 V window'),
                         ('full_stress_sweep', 'full 3.0–5.5 V stress sweep')]:
        rr = [c for c in ok if isinstance(c['metrics'].get(group), dict)]
        if not rr:
            continue
        fig, axes = plt.subplots(1, 2, figsize=(11.4, 4.6), layout='constrained')
        ecdf(axes[0], [c['metrics'][group]['vref_span_mV'] for c in rr],
             'VREF span (mV)', unit='mV')
        axes[0].set_title('Span distribution', loc='left')
        rows, cols, grid = worst_grid(rr, 'mos', 'temperature_C',
                                      lambda c: c['metrics'][group]['vref_span_mV'], 'max')
        im = heatmap(axes[1], rows, cols, grid)
        axes[1].set_xlabel('Temperature (°C)'); axes[1].set_ylabel('MOS corner')
        axes[1].set_title('Worst span (mV) per corner', loc='left')
        cb = fig.colorbar(im, ax=axes[1], pad=0.015, fraction=0.04)
        cb.set_label('mV', color=INK2, fontsize=9); cb.outline.set_visible(False)
        cb.ax.tick_params(colors=MUTED, labelsize=8)
        fig.suptitle('%s — %s' % (test, title), x=0.012, ha='left', fontsize=11.5,
                     fontweight='bold', color=INK)
        note(axes[0], 'Span is max VREF minus min VREF over the sweep; lower is better. '
                      'Heatmap takes the worst BJT/resistor/MIM combination.')
        figs.append(fig)

    if ok:
        fig, axes = plt.subplots(2, 1, figsize=(8.0, 6.2), sharex=True)
        g = 'full_stress_sweep' if any('full_stress_sweep' in c['metrics'] for c in ok) else 'nominal'
        drew = by_temperature(axes[0], ok, 'mos_index',
                              lambda c: c['metrics'].get(g, {}).get('endpoint_slope_mV_per_V'), temps) \
            if False else False
        slopes = [(c, c['metrics'].get(g, {})) for c in ok]
        idx = np.arange(len(slopes))
        axes[0].bar(idx, [m.get('endpoint_slope_mV_per_V', float('nan')) for _, m in slopes],
                    color=CAT[0], width=0.9)
        axes[1].bar(idx, [m.get('max_abs_adjacent_slope_mV_per_V', float('nan')) for _, m in slopes],
                    color=CAT[1], width=0.9)
        axes[0].set_ylabel('Endpoint slope (mV/V)')
        axes[1].set_ylabel('Max local slope (mV/V)')
        axes[1].set_xlabel('Case index (see the metrics CSV for the case_id at each index)')
        axes[0].set_title('%s — line sensitivity per case, %s' % (test, g.replace('_', ' ')), loc='left')
        for a in axes:
            a.xaxis.grid(False)
        note(axes[1], 'Endpoint slope is the straight-line sensitivity across the sweep; the local '
                      'slope catches kinks a straight line hides.')
        fig.tight_layout(); figs.append(fig)
        del drew
    return figs


# --------------------------------------------------------------------------
# TB03 — startup and restart
# --------------------------------------------------------------------------
def figures_tb03(test, head, cases, summary, waves):
    figs, ok = [], complete(cases)
    temps = axis_of(ok, 'temperature_C')

    if waves:
        fig, axes = plt.subplots(2, 1, figsize=(8.8, 6.4), sharex=True, layout='constrained')
        supplies = [c['vdd_V'] for c, _ in waves.values() if c.get('vdd_V')] or [5.0]
        for case, text in waves.values():
            rows = waveform_rows(text)
            if not rows:
                continue
            t = np.array([r[0] for r in rows]) * 1e3
            col = supply_color(case.get('vdd_V', 5.0), supplies)
            axes[0].plot(t, [r[1] for r in rows], color=col, linewidth=1.3,
                         alpha=0.85 if len(waves) < 12 else 0.5)
            axes[1].plot(t, [r[2] for r in rows], color=col, linewidth=1.3,
                         alpha=0.85 if len(waves) < 12 else 0.5)
        for a in axes:
            a.axvspan(4.0, 4.5, color='#f0efec', zorder=0, lw=0)
        axes[1].axhline(VREF_TARGET, color=MUTED, linewidth=1.2, linestyle=(0, (5, 3)))
        axes[0].set_ylabel('AVDD (V)'); axes[1].set_ylabel('VREF (V)')
        axes[1].set_xlabel('Time (ms)')
        axes[0].set_title('%s — startup and restart transients, %d retained case(s)'
                          % (test, len(waves)), loc='left')
        supply_colorbar(fig, axes, supplies)
        note(axes[1], 'Grey column is the 4.0–4.5 ms power-off window; the restart ramp follows it.')
        figs.append(fig)

    if ok:
        fig, axes = plt.subplots(1, 2, figsize=(11.4, 4.6), layout='constrained')
        for ax, key, label in [(axes[0], 'start_ready_300us', 'First startup'),
                               (axes[1], 'restart_ready_300us', 'Restart')]:
            rows, cols = axis_of(ok, 'temperature_C'), axis_of(ok, 'vdd_V')
            grid = [[float('nan')]*len(cols) for _ in rows]
            for i, t in enumerate(rows):
                for j, v in enumerate(cols):
                    sel = [c for c in ok if c.get('temperature_C') == t and c.get('vdd_V') == v]
                    if sel:
                        grid[i][j] = 100.0 * sum(c['metrics'].get(key) == 1 for c in sel) / len(sel)
            im = heatmap(ax, rows, cols, grid, '%.0f')
            ax.set_xlabel('Supply (V)'); ax.set_ylabel('Temperature (°C)')
            ax.set_title('%s ready within 300 µs (%% of corners)' % label, loc='left')
            cb = fig.colorbar(im, ax=ax, pad=0.015, fraction=0.04)
            cb.set_label('%', color=INK2, fontsize=9); cb.outline.set_visible(False)
            cb.ax.tick_params(colors=MUTED, labelsize=8)
        fig.suptitle('%s — readiness across the sweep' % test, x=0.012, ha='left',
                     fontsize=11.5, fontweight='bold', color=INK)
        note(axes[0], 'Percentage of corner combinations at that supply/temperature that settled '
                      'within 0.5% of the pre-shutdown reference.')
        figs.append(fig)

        fig, axes = plt.subplots(2, 1, figsize=(8.0, 6.2), sharex=True)
        by_temperature(axes[0], ok, 'vdd_V', lambda c: c['metrics'].get('start_peak_v'), temps)
        by_temperature(axes[1], ok, 'vdd_V', lambda c: c['metrics'].get('restart_peak_v'), temps)
        nominal_band(axes[0], head); nominal_band(axes[1], head)
        axes[0].set_ylabel('Peak VREF, first ramp (V)')
        axes[1].set_ylabel('Peak VREF, restart (V)')
        axes[1].set_xlabel('Supply (V)')
        axes[0].set_title('%s — worst VREF overshoot' % test, loc='left')
        note(axes[1], 'Worst (highest) peak over all corner combinations at each point.')
        fig.tight_layout(); figs.append(fig)

        fig, axes = plt.subplots(2, 1, figsize=(8.0, 6.2), sharex=True)
        by_temperature(axes[0], ok, 'vdd_V', lambda c: c['metrics'].get('final_vref_v'), temps)
        by_temperature(axes[1], ok, 'vdd_V', lambda c: c['metrics'].get('final_idd_ua'), temps)
        axes[0].axhspan(VREF_TARGET*0.995, VREF_TARGET*1.005, color=BLUE_RAMP[0], alpha=0.5,
                        zorder=0, lw=0)
        axes[0].axhline(VREF_TARGET, color=MUTED, linewidth=1.2, linestyle=(0, (5, 3)))
        axes[0].set_ylabel('Settled VREF (V)'); axes[1].set_ylabel('Settled supply current (µA)')
        axes[1].set_xlabel('Supply (V)')
        axes[0].set_title('%s — settled state after restart' % test, loc='left')
        note(axes[1], 'Averaged over the last 200 µs of the 6 ms transient.')
        fig.tight_layout(); figs.append(fig)
    return figs


# --------------------------------------------------------------------------
# TB04 — temperature
# --------------------------------------------------------------------------
def figures_tb04(test, head, cases, summary, waves):
    figs, ok = [], complete(cases)

    if waves:
        fig, axes = plt.subplots(2, 1, figsize=(8.8, 6.4), sharex=True, layout='constrained')
        supplies = [c['vdd_V'] for c, _ in waves.values() if c.get('vdd_V')] or [5.0]
        for case, text in waves.values():
            rows = blocks(text).get('TC_DATA', [])
            if not rows:
                continue
            t = [r[0] for r in rows]
            col = supply_color(case.get('vdd_V', 5.0), supplies)
            axes[0].plot(t, [r[1] for r in rows], color=col, linewidth=1.4,
                         alpha=0.85 if len(waves) < 12 else 0.5)
            axes[1].plot(t, [r[2] for r in rows], color=col, linewidth=1.4,
                         alpha=0.85 if len(waves) < 12 else 0.5)
        axes[0].axhspan(VREF_TARGET*0.995, VREF_TARGET*1.005, color=BLUE_RAMP[0], alpha=0.5,
                        zorder=0, lw=0)
        axes[0].axhline(VREF_TARGET, color=MUTED, linewidth=1.2, linestyle=(0, (5, 3)))
        threshold(axes[1], 60, '60 µA budget')
        axes[0].set_ylabel('VREF (V)'); axes[1].set_ylabel('Supply current (µA)')
        axes[1].set_xlabel('Temperature (°C)')
        axes[0].set_title('%s — reference drift, %d retained case(s)' % (test, len(waves)), loc='left')
        supply_colorbar(fig, axes, supplies)
        note(axes[1], 'Band on the upper axes is 1.194 V ±0.5%.')
        figs.append(fig)

    if ok:
        rows, cols, grid = worst_grid(ok, 'mos', 'vdd_V',
                                      lambda c: c['metrics'].get('TC_box_ppm_per_C'), 'max')
        fig, ax = plt.subplots(figsize=(max(6.5, 1.0*len(cols)+3.5), 0.55*len(rows)+2.8))
        im = heatmap(ax, rows, cols, grid)
        ax.set_xlabel('Supply (V)'); ax.set_ylabel('MOS corner')
        ax.set_title('%s — worst temperature coefficient (ppm/°C)' % test, loc='left')
        cb = fig.colorbar(im, ax=ax, pad=0.015, fraction=0.03)
        cb.set_label('ppm/°C', color=INK2, fontsize=9); cb.outline.set_visible(False)
        cb.ax.tick_params(colors=MUTED, labelsize=8)
        note(ax, 'Box TC over −40 to 125 °C, worst BJT/resistor/MIM combination. Target is 10 ppm/°C; '
                 'lighter cells are better here.')
        fig.tight_layout(); figs.append(fig)

        fig, axes = plt.subplots(1, 2, figsize=(11.0, 4.6), layout='constrained')
        tc = sorted(v for v in (c['metrics'].get('TC_box_ppm_per_C') for c in ok) if v is not None)
        err = sorted(v for v in (c['metrics'].get('max_absolute_error_percent') for c in ok)
                     if v is not None)
        for ax, vals, lim, xlabel, name, unit in [
                (axes[0], tc, 10, 'Box TC (ppm/°C)', 'TC', 'ppm/°C'),
                (axes[1], err, 0.5, 'Max |error| vs 1.194 V (%)', 'Accuracy', '%')]:
            if ecdf(ax, vals, xlabel, limit=lim, limit_label='%g limit' % lim,
                    worse='above', unit=unit):
                ax.set_title('%s — %s' % (name, ax.get_title(loc='left')), loc='left')
        fig.suptitle('%s — distributions' % test, x=0.012, ha='left', fontsize=11.5,
                     fontweight='bold', color=INK)
        figs.append(fig)

        fig, axes = plt.subplots(2, 1, figsize=(8.0, 6.2), sharex=True)
        supplies = axis_of(ok, 'vdd_V')
        for ax, key, label in [(axes[0], 'vref_at_25C_V', 'VREF at 25 °C (V)'),
                               (axes[1], 'max_IDD_uA', 'Peak supply current (µA)')]:
            pts = {}
            for c in ok:
                pts.setdefault(c['vdd_V'], []).append(c['metrics'].get(key))
            xs = [v for v in supplies if pts.get(v)]
            lo = [min(x for x in pts[v] if x is not None) for v in xs]
            hi = [max(x for x in pts[v] if x is not None) for v in xs]
            ax.fill_between(xs, lo, hi, color=BLUE_RAMP[2], alpha=0.7, lw=0, label='corner spread')
            ax.plot(xs, hi, color=CAT[0], marker='o', markersize=5, label='worst corner')
            ax.set_ylabel(label)
            ax.legend(loc='best', labelcolor=INK2)
        threshold(axes[1], 60, '60 µA budget')
        axes[0].axhline(VREF_TARGET, color=MUTED, linewidth=1.2, linestyle=(0, (5, 3)))
        axes[1].set_xlabel('Supply (V)')
        axes[0].set_title('%s — corner spread across the supply sweep' % test, loc='left')
        fig.tight_layout(); figs.append(fig)
    return figs


# --------------------------------------------------------------------------
# TB05 — loop stability
# --------------------------------------------------------------------------
def loop_curve(text, cut):
    """Full-resolution L(f) from the retained injection sweeps, if available."""
    if RB is None:
        return None
    data = blocks(text)
    v, i = data.get(cut.upper()+'_VOLTAGE', []), data.get(cut.upper()+'_CURRENT', [])
    if not v or not i:
        return None
    try:
        values, _ = RB.loop_gain(v, i)
    except Exception:
        return None
    return values


def figures_tb05(test, head, cases, summary, waves):
    figs, ok = [], complete(cases)
    if not ok:
        return figs

    for cut in ('main', 'bias'):
        curves = []
        for c in ok:
            loop = c['metrics'].get('loops', {}).get(cut)
            if not loop:
                continue
            full = None
            entry = waves.get(c['case_id'])
            if entry:
                full = loop_curve(entry[1], cut)
            if full:
                f = np.array([x[0] for x in full])
                g = np.array([x[1] for x in full])
                db = 20*np.log10(np.maximum(np.abs(g), 1e-300))
                ph = np.degrees(np.unwrap(np.angle(g)))
                src = 'full sweep'
            else:
                s = loop.get('curve_samples') or []
                if not s:
                    continue
                f = np.array([p['frequency_Hz'] for p in s])
                db = np.array([p['gain_dB'] for p in s])
                ph = np.array([p['phase_deg'] for p in s])
                g = np.array([complex(p['real'], p['imag']) for p in s])
                src = 'report samples'
            curves.append((c, f, db, ph, g, loop, src))
        if not curves:
            continue

        fig, axes = plt.subplots(2, 1, figsize=(8.8, 6.8), sharex=True)
        for c, f, db, ph, _, loop, _src in curves:
            col = CAT[0] if loop.get('phase_margin_deg') is not None else CAT[1]
            axes[0].semilogx(f, db, color=col, linewidth=1.8,
                             alpha=0.9 if len(curves) < 8 else 0.55)
            axes[1].semilogx(f, ph, color=col, linewidth=1.8,
                             alpha=0.9 if len(curves) < 8 else 0.55)
            for u in loop.get('unity_crossings', []):
                axes[0].plot([u['frequency_Hz']], [0], marker='o', markersize=7,
                             color=col, markeredgecolor=SURFACE, markeredgewidth=1.5, zorder=6)
        axes[0].axhline(0, color=AXIS, linewidth=1.4)
        axes[1].axhline(-180, color=CRITICAL, linewidth=1.4, linestyle=(0, (5, 3)))
        axes[1].annotate('−180°', xy=(0.995, -180), xycoords=('axes fraction', 'data'),
                         ha='right', va='bottom', fontsize=8, color=CRITICAL)
        axes[0].set_ylabel('|L| (dB)'); axes[1].set_ylabel('∠L (deg, unwrapped)')
        axes[1].set_xlabel('Frequency (Hz)')
        axes[0].set_title('%s — %s loop, %d case(s), %s'
                          % (test, cut.upper(), len(curves), curves[0][6]), loc='left')
        handles = []
        if any(l.get('phase_margin_deg') is not None for *_x, l, _s in curves):
            handles.append(Line2D([], [], color=CAT[0], label='conventional single crossing'))
        if any(l.get('phase_margin_deg') is None for *_x, l, _s in curves):
            handles.append(Line2D([], [], color=CAT[1], label='review required (no or multiple crossings)'))
        if any(l.get('unity_crossings') for *_x, l, _s in curves):
            handles.append(Line2D([], [], color=MUTED, marker='o', linestyle='none',
                                  label='unity crossing'))
        if len(handles) > 1:
            axes[0].legend(handles=handles, loc='best', labelcolor=INK2)
        note(axes[1], 'Conditional loop: the other feedback path stays closed. A phase margin is '
                      'only meaningful on the conventional branch — see the status per case below.')
        fig.tight_layout(); figs.append(fig)

        fig, ax = plt.subplots(figsize=(6.6, 6.2))
        th = np.linspace(0, 2*np.pi, 400)
        ax.plot(np.cos(th), np.sin(th), color=GRID, linewidth=1.2, zorder=1)
        for c, _f, _db, _ph, g, loop, _src in curves:
            col = CAT[0] if loop.get('phase_margin_deg') is not None else CAT[1]
            ax.plot(np.real(g), np.imag(g), color=col, linewidth=1.6,
                    alpha=0.9 if len(curves) < 8 else 0.55)
        ax.plot([-1], [0], marker='x', markersize=11, markeredgewidth=2.5, color=CRITICAL, zorder=6)
        ax.annotate('−1', xy=(-1, 0), xytext=(6, 6), textcoords='offset points',
                    fontsize=9, color=CRITICAL)
        ax.set_aspect('equal', adjustable='datalim')
        ax.set_xlabel('Re L'); ax.set_ylabel('Im L')
        ax.set_title('%s — %s loop, Nyquist view' % (test, cut.upper()), loc='left')
        note(ax, 'Grey circle is |L| = 1. Distance from the −1 point is the stability margin the '
                 'phase-margin number stands in for.')
        fig.tight_layout(); figs.append(fig)

    rows = []
    for c in ok:
        for cut in ('main', 'bias'):
            loop = c['metrics'].get('loops', {}).get(cut)
            if loop:
                rows.append((c['case_id'], cut, loop))
    if rows:
        fig, axes = plt.subplots(1, 2, figsize=(10.6, max(3.2, 0.34*len(rows)+2.2)))
        labels = ['%s · %s' % (cut.upper(), cid) for cid, cut, _ in rows]
        y = np.arange(len(rows))
        pm = [l.get('phase_margin_deg') if l.get('phase_margin_deg') is not None else float('nan')
              for _, _, l in rows]
        axes[0].barh(y, pm, color=CAT[0], height=0.55)
        axes[0].set_yticks(y, labels, fontsize=8)
        axes[0].invert_yaxis(); axes[0].yaxis.grid(False)
        axes[0].set_xlabel('Conditional phase margin (deg)')
        axes[0].set_title('Phase margin, where conventional', loc='left')
        for i, v in enumerate(pm):
            if math.isnan(v):
                axes[0].annotate('review required', xy=(0, i), xytext=(6, 0),
                                 textcoords='offset points', va='center', fontsize=8, color=CAT[1])
        m1 = [l.get('minimum_sampled_abs_1_plus_L', float('nan')) for _, _, l in rows]
        axes[1].barh(y, m1, color=CAT[2], height=0.55)
        axes[1].set_yticks(y, ['' for _ in y])
        axes[1].invert_yaxis(); axes[1].yaxis.grid(False)
        axes[1].set_xlabel('min |1 + L| over the sweep')
        axes[1].set_title('Distance from the −1 point', loc='left')
        fig.suptitle('%s — conditional margins per case and cut' % test, x=0.012, ha='left',
                     fontsize=11.5, fontweight='bold', color=INK)
        note(axes[0], 'Bars are absent where the crossing pattern does not support a conventional '
                      'phase margin; the loop status in the CSV says which case and why.')
        fig.tight_layout(rect=(0, 0, 1, 0.94)); figs.append(fig)

    fig, axes = plt.subplots(1, 2, figsize=(10.2, 4.0))
    ids = [c['case_id'] for c in ok]
    y = np.arange(len(ids))
    axes[0].barh(y, [c['metrics'].get('op_vref_v', float('nan')) for c in ok], color=CAT[0], height=0.5)
    axes[0].axvline(VREF_TARGET, color=MUTED, linewidth=1.2, linestyle=(0, (5, 3)))
    axes[0].set_xlabel('VREF at operating point (V)')
    axes[1].barh(y, [max(abs(c['metrics'].get('main_dc_error_v', 0)),
                         abs(c['metrics'].get('bias_dc_error_v', 0))) for c in ok],
                 color=CAT[2], height=0.5)
    axes[1].set_xlabel('Worst probe DC error (V)')
    for ax, labels in [(axes[0], ids), (axes[1], ['' for _ in ids])]:
        ax.set_yticks(y, labels, fontsize=8); ax.invert_yaxis(); ax.yaxis.grid(False)
    axes[0].set_title('Reference', loc='left'); axes[1].set_title('Probe continuity', loc='left')
    fig.suptitle('%s — operating point before the injection sweeps' % test, x=0.012, ha='left',
                 fontsize=11.5, fontweight='bold', color=INK)
    note(axes[0], 'The runner rejects a case whose probes shift the DC solution by more than 1 nV, '
                  'so this bar should read as zero.')
    fig.tight_layout(rect=(0, 0, 1, 0.93)); figs.append(fig)
    return figs



def figures_tb06(test,head,cases,summary,waves):
    ok=complete(cases)
    if not ok:return []
    # Histogram samples at ONE V/T point, never mix PVT into a yield histogram.
    conditions=sorted({(c['temperature_C'],c['vdd_V']) for c in ok})
    point=(25,5.0) if (25,5.0) in conditions else conditions[0]
    rr=[c for c in ok if (c['temperature_C'],c['vdd_V'])==point]
    fig,ax=plt.subplots(1,2,figsize=(11,4.8),layout='constrained')
    modes=sorted({c['mc_mode'] for c in rr})
    for i,mode in enumerate(modes):
        group=[c for c in rr if c['mc_mode']==mode]; col=CAT[i]
        vals=[c['metrics']['op_vref_v'] for c in group]
        ax[0].hist(vals,bins=max(3,min(30,int(len(vals)**.5))),histtype='step',linewidth=2,color=col,label=f'{mode}: n={len(vals)}')
        allmode=[c for c in ok if c['mc_mode']==mode]
        ids=sorted({c['seed'] for c in allmode})
        worst=[max(c['metrics']['absolute_error_percent'] for c in allmode if c['seed']==seed) for seed in ids]
        ax[1].plot(ids,worst,'o',markersize=4,color=col,label=mode)
    ax[1].xaxis.set_major_locator(MaxNLocator(nbins=4,integer=True))
    ax[1].xaxis.set_major_formatter(FuncFormatter(lambda x,_: str(int(x))))
    for limit in [VREF_TARGET*.995,VREF_TARGET*1.005]:ax[0].axvline(limit,color=CRITICAL,linestyle='--')
    ax[0].set(xlabel='Untrimmed VREF (V)',ylabel='Samples',title=f'One condition: {point[0]:g} °C, {point[1]:g} V')
    ax[1].set(xlabel='Random seed',ylabel='Worst absolute error (%)',title='Worst over completed V/T points per seed')
    threshold(ax[1],.5,'0.5% reference target');ax[0].legend();ax[1].legend()
    note(ax[0],'Statistical sample count is not a population-yield guarantee. MIM capacitance is fixed in this DC test.')
    note(ax[1],'Missing/failed points are excluded here and remain visible in the status page and CSV.')
    fig.suptitle(test+' — statistical accuracy',x=.012,ha='left',fontweight='bold')
    fig2,bx=plt.subplots(figsize=(8,4.2),layout='constrained')
    corrections=[c['metrics']['required_output_correction_mV'] for c in rr]
    bx.scatter([c['seed'] for c in rr],corrections,c=[CAT[modes.index(c['mc_mode'])] for c in rr],s=22)
    bx.xaxis.set_major_locator(MaxNLocator(nbins=4,integer=True));bx.xaxis.set_major_formatter(FuncFormatter(lambda x,_: str(int(x))))
    bx.axhline(0,color=MUTED,linestyle='--');bx.set(xlabel='Seed',ylabel='Required output offset (mV)',title=test+' — correction required at histogram condition')
    note(bx,'This estimates the required output correction only. No physical trim network or trim-code yield is simulated.')
    return [fig,fig2]


def figures_tb07(test,head,cases,summary,waves):
    figs=[]; ok=complete(cases)
    if waves:
        fig,ax=plt.subplots(figsize=(8.5,4.8),layout='constrained')
        drawn=0
        for case,text in waves.values():
            rows=blocks(text).get('NOISE_DATA',[])
            if not rows:continue
            a=np.array(rows); qualified=case['metrics'].get('op_reference_in_target',False)
            ax.loglog(a[:,0],a[:,1]*1e9,alpha=.65,linewidth=1.3,linestyle='-' if qualified else '--')
            drawn+=1
        ax.set(xlabel='Frequency (Hz)',ylabel='Output noise ASD (nV/√Hz)',title=f'{test} — {drawn} retained spectra')
        note(ax,'Solid: operating point in reference target. Dashed: outside target. Noise includes only what the installed models implement.')
        figs.append(fig)
    if ok:
        bands=sorted({(b['low_Hz'],b['high_Hz']) for c in ok for b in c['metrics']['bands']})
        fig,axes=plt.subplots(1,len(bands),figsize=(5.4*len(bands),4.5),squeeze=False,layout='constrained')
        for ax,(lo,hi) in zip(axes[0],bands):
            vals=[b['output_rms_uV'] for c in ok if c['metrics']['op_reference_in_target'] for b in c['metrics']['bands'] if (b['low_Hz'],b['high_Hz'])==(lo,hi)]
            ecdf(ax,vals,'Integrated output noise (µV RMS)');ax.set_title(f'{lo:g} Hz – {hi:g} Hz',loc='left')
            note(ax,'In-target OP cases only. No noise pass/fail limit has been assigned.')
        fig.suptitle(test+' — integrated noise',x=.012,ha='left',fontweight='bold');figs.append(fig)
    return figs


def figures_tb08(test,head,cases,summary,waves):
    ok=complete(cases); figs=[]
    if not ok:return figs
    fig,ax=plt.subplots(1,2,figsize=(11,4.6),layout='constrained')
    for t in axis_of(ok,'temperature_C'):
        rr=[c for c in ok if c['temperature_C']==t]
        ax[0].scatter([c['vdd_V'] for c in rr],[c['metrics']['op_idd_ua'] for c in rr],s=14,alpha=.5,label=f'{t:g} °C')
        ax[1].scatter([c['vdd_V'] for c in rr],[c['metrics']['power_uW'] for c in rr],s=14,alpha=.5,label=f'{t:g} °C')
    threshold(ax[0],head.get('coverage',{}).get('idd_limit_uA',60),'Current limit')
    for a in ax:a.set_xlabel('Supply (V)');nominal_band(a,head);a.legend()
    ax[0].set_ylabel('Quiescent IDD (µA)');ax[1].set_ylabel('Quiescent power (µW)')
    fig.suptitle(test+' — quiescent power',x=.012,ha='left',fontweight='bold');figs.append(fig)
    devs={}
    for c in ok:
        for d in c['metrics']['devices']:
            old=devs.get(d['name'])
            if old is None or d['max_abs_terminal_V']/d['screen_limit_V']>old['max_abs_terminal_V']/old['screen_limit_V']:devs[d['name']]=d
    selected=sorted(devs.values(),key=lambda d:d['max_abs_terminal_V']/d['screen_limit_V'],reverse=True)
    fig,bx=plt.subplots(figsize=(10,max(4.5,len(selected)*.19+1.8)),layout='constrained')
    names=[d['name'] for d in selected];ratios=[d['max_abs_terminal_V']/d['screen_limit_V'] for d in selected]
    bx.barh(names,ratios,color=[CRITICAL if r>1 else CAT[0] for r in ratios]);bx.invert_yaxis()
    bx.axvline(1,color=CRITICAL,linestyle='--');bx.set(xlabel='Maximum |terminal voltage| / screening threshold',title=test+' — worst DC or startup voltage per MOS')
    bx.text(0,-.05,'Conservative screening thresholds, not foundry reliability limits. Terminal details: device CSV.',transform=bx.transAxes,fontsize=8,color=MUTED)
    figs.append(fig)
    fig,ax=plt.subplots(figsize=(9,4.6),layout='constrained')
    margins={name:[] for name in devs}
    for c in ok:
        for d in c['metrics']['devices']:
            if abs(d['id'])>1e-9:margins[d['name']].append(d['saturation_margin_V'])
    names=[n for n,vals in margins.items() if vals]
    ax.bar(range(len(names)),[min(margins[n]) for n in names],color=CAT[2]);ax.set_xticks(range(len(names)),names,rotation=90,fontsize=7)
    ax.axhline(0,color=CRITICAL,linestyle='--');ax.set(ylabel='Minimum |VDS| − |VDSAT| (V)',title=test+' — DC saturation margin, devices with |ID| > 1 nA')
    note(ax,'Off devices are excluded; a negative margin may be intentional in startup circuitry and requires circuit review.')
    figs.append(fig)
    return figs


def figures_tb09(test,head,cases,summary,waves):
    ok=complete(cases);figs=[]
    if ok:
        kinds=sorted({c['scenario']['kind'] for c in ok})
        fig,ax=plt.subplots(1,2,figsize=(11,4.6),layout='constrained')
        for i,kind in enumerate(kinds):
            rr=[c for c in ok if c['scenario']['kind']==kind]
            count=sum(c['metrics']['all_events_ready'] for c in rr)
            ax[0].bar(i,count,color=GOOD);ax[0].bar(i,len(rr)-count,bottom=count,color=CRITICAL)
            ax[0].text(i,len(rr),f'{count}/{len(rr)} ready',ha='center',va='bottom',fontsize=8)
            times=[e['settling_time_s']*1e6 for c in rr for e in c['metrics']['events'] if e['settling_time_s'] is not None]
            if times:ax[1].scatter([i]*len(times),times,s=16,alpha=.5,color=CAT[i])
        for a in ax:a.set_xticks(range(len(kinds)),kinds)
        ax[0].set_ylabel('Cases');ax[0].set_ylim(0,max(sum(c['scenario']['kind']==k for c in ok) for k in kinds)*1.2)
        ax[1].set_ylabel('Settling after supply recovery (µs)')
        threshold(ax[1],head.get('coverage',{}).get('recovery_limit_s',.0003)*1e6,'Recovery deadline')
        note(ax[0],'Ready includes baseline startup and every recovery event. Failed simulations are counted on the status page.')
        note(ax[1],'Unsettled events have no settling time and are omitted from this scatter; they fail readiness.')
        fig.suptitle(test+' — supply disturbances and recovery',x=.012,ha='left',fontweight='bold');figs.append(fig)
    for kind in sorted({c['scenario']['kind'] for c,_ in waves.values()}):
        rr=[(c,t) for c,t in waves.values() if c['scenario']['kind']==kind]
        fig,ax=plt.subplots(2,1,figsize=(9,6),sharex=True,layout='constrained')
        for c,text in rr:
            rows=blocks(text).get('TRAN_DATA',[])
            if not rows:continue
            a=np.array(rows); label=f'{c["vdd_V"]:g} V, {c["temperature_C"]:g} °C, '+c['case_id'].split('_event')[-1]
            ax[0].plot(a[:,0]*1e3,a[:,1],alpha=.65,linewidth=1.2)
            ax[1].plot(a[:,0]*1e3,a[:,2],alpha=.65,linewidth=1.2,label=label if len(rr)<=6 else None)
        ax[1].axhspan(VREF_TARGET*.995,VREF_TARGET*1.005,color=BLUE_RAMP[0],alpha=.5)
        ax[0].set(ylabel='Supply (V)',title=f'{test} — {kind}, {len(rr)} retained case(s)');ax[1].set(xlabel='Time (ms)',ylabel='VREF (V)')
        if len(rr)<=6:ax[1].legend(fontsize=7)
        note(ax[1],'The shaded band is the absolute reference target. Supply recovers to the case voltage; no forced reference reset is applied.')
        figs.append(fig)
    return figs


def write_device_csv(path,cases):
    rows=[]
    for case in complete(cases):
        for d in case['metrics'].get('devices',[]):
            row={'case_id':case['case_id'],'temperature_C':case['temperature_C'],'vdd_V':case['vdd_V']}
            flatten('',d,row);rows.append(row)
    if not rows:return
    fields=list(dict.fromkeys(k for r in rows for k in r))
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)


BUILDERS = {
    'TB01_PSRR': figures_tb01,
    'TB02_LINE_REGULATION': figures_tb02,
    'TB03_STARTUP_RESTART': figures_tb03,
    'TB04_TEMPERATURE': figures_tb04,
    'TB05_LOOP_STABILITY': figures_tb05,
    'TB06_MONTE_CARLO': figures_tb06,
    'TB07_NOISE': figures_tb07,
    'TB08_POWER_DEVICE_LIMITS': figures_tb08,
    'TB09_SUPPLY_DISTURBANCE': figures_tb09,
}


def slug(fig, index):
    title = ''
    for ax in fig.axes:
        for loc in ('left', 'center', 'right'):
            title = title or ax.get_title(loc=loc)
        if title:
            break
    if fig._suptitle is not None:
        title = fig._suptitle.get_text()
    title = title.split('\n')[0]
    title = re.sub(r'^TB\d\d[_A-Z]*\s*[—-]\s*', '', title)
    title = re.sub(r'[^a-z0-9]+', '_', title.lower()).strip('_')
    return '%02d_%s' % (index, title[:52] or 'figure')


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--config', type=Path, default=HERE/CONFIG_NAME,
                    help='Settings file that names output_directory (default: %s here)' % CONFIG_NAME)
    ap.add_argument('--results', type=Path,
                    help='Results folder to read, overriding the settings file')
    ap.add_argument('--test', action='append', choices=TESTS,
                    help='Plot only this test; repeatable. Default: every report present')
    ap.add_argument('--out', type=Path, help='Figure folder (default: <results>/plots)')
    ap.add_argument('--profile',help='Plot only one profile directory')
    ap.add_argument('--max-waveforms',type=int,default=24,help='Displayed traces per test; 0 = all. All metrics are always plotted.')
    ap.add_argument('--dpi', type=int, default=150)
    ap.add_argument('--no-pdf', action='store_true', help='Skip the combined PDF')
    ap.add_argument('--no-csv', action='store_true', help='Skip the per-test metrics CSV')
    args = ap.parse_args()

    root = (args.results or output_directory(args.config)).expanduser().resolve()
    if not root.is_dir():
        sys.exit('Results folder does not exist yet: %s\nRun a bench first.' % root)
    if args.max_waveforms < 0: ap.error('--max-waveforms must be nonnegative')
    if args.profile: root=root/args.profile
    # The one output_directory contains separate full/smoke profile directories.
    children=sorted(d for d in root.iterdir() if d.is_dir() and any(d.glob('TB*_UPLOAD_THIS.txt')))
    if children and not any(root.glob('TB*_UPLOAD_THIS.txt')):
        codes=[]
        for child in children:
            cmd=[sys.executable,str(Path(__file__).resolve()),'--results',str(child),'--dpi',str(args.dpi),'--max-waveforms',str(args.max_waveforms)]
            if args.out: cmd+=['--out',str(args.out/child.name)]
            if args.no_pdf: cmd+=['--no-pdf']
            if args.no_csv: cmd+=['--no-csv']
            for test in args.test or []: cmd+=['--test',test]
            codes.append(subprocess.run(cmd).returncode)
        return 0 if codes and all(c==0 for c in codes) else 1
    out = (args.out or root/'plots').expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    tests = args.test or list(TESTS)
    pdf = None if args.no_pdf else PdfPages(out/'bandgap_plots.pdf')
    made = 0
    errors = 0
    for test in tests:
        report = root/(test+'_UPLOAD_THIS.txt')
        if not report.is_file():
            print('%-22s no report yet (%s)' % (test, report.name))
            if args.test: errors += 1
            continue
        head, cases, summary, tail = read_report(report)
        source = 'report'
        if not cases:
            # The runner truncates the report when a run starts and appends a line per
            # finished case, so a header-only file means no case has finished yet — an
            # interrupted, killed, or still-running sweep. Every case that did finish
            # left a result.json in its own directory, so recover those instead.
            cases = cached_cases(root, test, head.get('fingerprint'))
            source = 'case caches'
            if not cases:
                diagnose(root, test, report, head, tail)
                continue
            source = 'recovered from case caches — report is header-only, run unfinished'
        waves = retained_waveforms(root, test, cases, args.max_waveforms)
        print('%-22s %d cases (%s), %d with retained waveforms, profile %s'
              % (test, len(cases), source, len(waves), head.get('profile', '?')))
        progress(test, head, cases)
        if not args.no_csv:
            written = write_csv(out/(test+'_metrics.csv'), cases)
            if test=='TB08_POWER_DEVICE_LIMITS': write_device_csv(out/(test+'_devices.csv'),cases)
            if written:
                print('%-22s   %s' % ('', written.name))
        figs = [status_figure(test, cases, summary, head)]
        try:
            figs += BUILDERS[test](test, head, cases, summary, waves)
        except Exception as exc:
            print('%-22s   figure build stopped: %r' % ('', exc))
            errors += 1
        for i, fig in enumerate(f for f in figs if f is not None):
            name = '%s_%s.png' % (test, slug(fig, i))
            fig.savefig(out/name, dpi=args.dpi, bbox_inches='tight')
            if pdf is not None:
                pdf.savefig(fig, bbox_inches='tight')
            plt.close(fig)
            made += 1
            print('%-22s   %s' % ('', name))
        for line in tail:
            if line.startswith(('INCOMPLETE_', 'COVERAGE_HAS_')):
                print('%-22s   note: %s' % ('', line))
    if pdf is not None:
        if made:
            pdf.close()
            print('\nCombined PDF: %s' % (out/'bandgap_plots.pdf'))
        else:
            pdf.close()
            (out/'bandgap_plots.pdf').unlink(missing_ok=True)
    if not made:
        print('\nNothing plotted. Reports are written to %s once a bench runs.' % root)
        return 1
    print('\n%d figures in %s' % (made, out))
    return 1 if errors else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        print('PLOT_ERROR: ' + str(exc), file=sys.stderr)
        sys.exit(1)
