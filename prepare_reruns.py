#!/usr/bin/env python3
"""Prepare a separate, reproducible rerun folder. Never launch simulations."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

HERE=Path(__file__).resolve().parent

def read_cases(path):
    with path.open() as f:
        return [json.loads(line[5:]) for line in f if line.startswith('CASE ')]

def issue_cases(test,rows):
    selected=[]
    for row in rows:
        reason=None;m=row.get('metrics',{})
        if row['status']!='complete':reason='execution failure or unresolved analysis'
        elif row.get('range')=='nominal':
            if test.startswith('TB03') and m.get('pre_valid') and m.get('final_valid') and not (
                    m.get('start_ready_300us') and m.get('restart_ready_300us')):
                reason='nominal accuracy valid, startup/restart readiness missed'
            elif test.startswith('TB09') and m.get('op_reference_in_target') and not m.get('all_events_ready'):
                reason='nominal DC accuracy valid, disturbance readiness missed'
        if reason:selected.append(dict(case_id=row['case_id'],reason=reason,range=row.get('range')))
    return selected

def prepare(source,output,project=HERE):
    source=Path(source).resolve();output=Path(output).resolve();project=Path(project).resolve()
    if output.exists():raise ValueError('Destination already exists; reuse its run_selected.sh to resume or choose a new folder')
    tests=['TB03_STARTUP_RESTART','TB09_SUPPLY_DISTURBANCE']
    selections={};reports={}
    for test in tests:
        path=source/(test+'_UPLOAD_THIS.txt')
        selections[test]=issue_cases(test,read_cases(path))
        reports[test]=dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    # Refuse missing project files before creating anything.
    names=['run_bandgap.py','plot_bandgap.py','bandgap_config.json']
    names += [p.name for p in project.glob('*.sch')]+[p.name for p in project.glob('*.sym')]
    if any(not (project/n).is_file() for n in names):raise ValueError('Incomplete project source')
    output.mkdir(parents=True)
    snapshot=output/'source';snapshot.mkdir()
    for name in names:shutil.copy2(project/name,snapshot/name)
    (output/'selections').mkdir()
    for test,rows in selections.items():
        (output/'selections'/(test+'.txt')).write_text(''.join(r['case_id']+'\n' for r in rows))
    manifest=dict(source_reports=reports,selections=selections,
                  scope='TB03/TB09: execution failures plus nominal accuracy-valid readiness misses. TB05 and TB10 require complete fresh coverage.',
                  source_snapshot={name:hashlib.sha256((snapshot/name).read_bytes()).hexdigest() for name in names})
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    script='''#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SRC="$ROOT/source"
export PDK=gf180mcuD
case "${1:-plan}" in
  TB03) bench=TB03_STARTUP_RESTART; selection=yes ;;
  TB05) bench=TB05_LOOP_STABILITY; selection=no ;;
  TB09) bench=TB09_SUPPLY_DISTURBANCE; selection=yes ;;
  TB10) bench=TB10_RESISTOR_TRIM; selection=no ;;
  plan)
    for bench in TB03_STARTUP_RESTART TB05_LOOP_STABILITY TB09_SUPPLY_DISTURBANCE TB10_RESISTOR_TRIM; do
      extra=()
      if [ -f "$ROOT/selections/$bench.txt" ]; then extra=(--case-ids-file "$ROOT/selections/$bench.txt"); fi
      python3 "$SRC/run_bandgap.py" --test "$bench" --profile full --results-root "$ROOT" "${extra[@]}" --list-cases
    done
    exit 0 ;;
  *) echo 'Usage: bash run_selected.sh [plan|TB03|TB05|TB09|TB10]' >&2; exit 1 ;;
esac
mkdir -p "$ROOT/netlists"
xschem -n -x -q -r -s -o "$ROOT/netlists" -N "$bench.spice" "$SRC/$bench.sch"
test -s "$ROOT/netlists/$bench.spice"
extra=()
if [ "$selection" = yes ]; then extra=(--case-ids-file "$ROOT/selections/$bench.txt"); fi
status=0
python3 "$SRC/run_bandgap.py" --test "$bench" --deck "$ROOT/netlists/$bench.spice" \\
  --profile full --results-root "$ROOT" --retry-failed "${extra[@]}" || status=$?
# A separate plot folder per bench avoids replacing another bench's combined PDF.
python3 "$SRC/plot_bandgap.py" --results "$ROOT/full" --test "$bench" \\
  --out "$ROOT/full/plots_$bench" --max-waveforms 6
exit "$status"
'''
    with (output/'run_selected.sh').open('w',newline='\n') as f:f.write(script)
    (output/'README.txt').write_text(
        'This folder is a separate rerun workspace. Original reports/caches are untouched.\n'
        'Run in Bash inside FOSS; first source /foss/tools/sak/sak-pdk-script.sh gf180mcuD.\n'
        'bash run_selected.sh plan    # list only; no simulation\n'
        'bash run_selected.sh TB05    # all cases: repaired untrimmed loop-probe core\n'
        'bash run_selected.sh TB03    # selected unresolved/readiness issues\n'
        'bash run_selected.sh TB09    # selected unresolved/readiness issues\n'
        'bash run_selected.sh TB10    # full held-code trim PVT, substantial run\n'
        'Repeat a command to resume. Completed performance misses are not rerun by --retry-failed.\n'
        'The source snapshot is intentionally fixed. After circuit changes, prepare a NEW folder.\n'
        'This selection excludes steady-state accuracy misses; it is a debug subset, not signoff.\n')
    return {test:len(rows) for test,rows in selections.items()}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--from-results',type=Path,default=HERE/'results/full')
    ap.add_argument('--to',type=Path,required=True)
    args=ap.parse_args()
    print(json.dumps(prepare(args.from_results,args.to),indent=2))
    print('PREPARED_ONLY_NO_SIMULATIONS '+str(args.to.resolve()))

if __name__=='__main__':
    try:main()
    except Exception as exc:print(str(exc),file=sys.stderr);sys.exit(1)
