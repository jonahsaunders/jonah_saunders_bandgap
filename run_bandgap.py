#!/usr/bin/env python3
"""Unified GF180 test runner: TB01-TB09, reporting, resume, and --configure.
Python standard library only. One bandgap_config.json supplies settings, profiles and control templates.
TB05 requires the intended loop-probe core. TB08 includes the GND-vector fix.
Replace the previous run_bandgap.py with this file, then run --configure using
its existing netlist directory. The separate TB08 runner is no longer needed.
Completed compatible suite-v9 and corrected-TB08 caches can migrate automatically;
source/config/model/executable changes still invalidate them. plot_bandgap.py
remains the separate plotting program.
"""
import argparse
import cmath
import concurrent.futures
import contextlib
import fcntl
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
TESTS = ('TB01_PSRR', 'TB02_LINE_REGULATION', 'TB03_STARTUP_RESTART', 'TB04_TEMPERATURE', 'TB05_LOOP_STABILITY', 'TB06_MONTE_CARLO', 'TB07_NOISE', 'TB08_POWER_DEVICE_LIMITS', 'TB09_SUPPLY_DISTURBANCE')
MIM_FACTORS = {'mimcap_typical': 1.0, 'mimcap_ff': 0.9, 'mimcap_ss': 1.1}
ALLOWED = {'mos_corners': {'typical','ff','ss','fs','sf'},
           'bjt_corners': {'bjt_typical','bjt_ff','bjt_ss'},
           'res_corners': {'res_typical','res_ff','res_ss'},
           'mim_corners': set(MIM_FACTORS)}


def atomic_json(path, data):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, indent=2, allow_nan=False) + '\n')
    temp.replace(path)


def _base_validate_config(c):
    for key, allowed in ALLOWED.items():
        if not c[key] or len(set(c[key])) != len(c[key]) or not set(c[key]) <= allowed:
            raise ValueError('Invalid or duplicate values for ' + key)
    for key in ['temperatures_C','supply_voltages_V']:
        if not c[key] or not all(isinstance(v,(float,int)) and math.isfinite(v) for v in c[key]):
            raise ValueError('Invalid ' + key)
        if len(c[key]) != len(set(c[key])):
            raise ValueError('Duplicate ' + key)
    if min(c['supply_voltages_V']) <= 0:
        raise ValueError('Supply sweep must contain positive voltages')
    a,b,h = (c[k] for k in ['line_start_V','line_stop_V','line_step_V'])
    if not (0 < a < b and h > 0 and h <= b-a):
        raise ValueError('Invalid line sweep')
    if abs((b-a)/h-round((b-a)/h)) > 1e-6:
        raise ValueError('Line endpoints must be separated by an integer number of steps')
    if not a <= c['nominal_supply_min_V'] < c['nominal_supply_max_V'] <= b:
        raise ValueError('Line sweep must contain the full nominal range')
    if int(c['parallel_jobs']) < 1 or c['case_timeout_seconds'] <= 0:
        raise ValueError('Invalid jobs/timeout')


def _base_cases(c, test):
    axes = [c[k] for k in ['mos_corners','bjt_corners','res_corners','mim_corners','temperatures_C']]
    for mos,bjt,res,mim,temp in itertools.product(*axes):
        for vdd in (c['supply_voltages_V'] if test != TESTS[1] else [None]):
            d = dict(mos=mos,bjt=bjt,res=res,mim=mim,temperature_C=temp,vdd_V=vdd)
            d['range'] = 'nominal_and_stress_sweep' if vdd is None else (
                'nominal' if c['nominal_supply_min_V'] <= vdd <= c['nominal_supply_max_V'] else 'stress')
            tag = f'{mos}_{bjt}_{res}_{mim}_T{temp:g}'
            if vdd is not None:
                tag += f'_V{vdd:g}'
            d['case_id'] = tag.replace('.','p').replace('-','m')
            yield d


def _base_prepare_source(deck):
    s = deck.read_text()
    # Read the original Xschem netlist, not ngspice's expanded listing.
    if re.search(r'^\s*\.control\b', s, re.M|re.I):
        s = re.sub(r'^\s*\.control\b.*?^\s*\.endc\b[^\n]*', '', s, flags=re.M|re.S|re.I)
    s = re.sub(r'^\s*\.end\s*$', '', s, flags=re.M|re.I)
    if len(re.findall(r'^VDD\s+', s, re.M|re.I)) != 1:
        raise ValueError('Expected exactly one top-level VDD source in the netlist')
    if '.subckt cap_mim_2f0ff' not in s.lower():
        raise ValueError('Embedded cap_mim_2f0fF compatibility model is missing')
    # Corners are switched by replacing actual .lib statements in a NEW deck.
    # .lib inside parameter-controlled .if is deliberately not used.
    paths = []
    for family in ['typical','bjt_typical','res_typical']:
        hits = re.findall(r'^\s*\.lib\s+(.+?)\s+'+family+r'\s*$', s, re.M|re.I)
        if len(hits) != 1:
            raise ValueError('Expected one bootstrap .lib section: '+family)
        p = Path(hits[0].strip().strip('"\''))
        if not p.is_absolute():
            p = (deck.parent/p).resolve()
        if not p.is_file():
            raise FileNotFoundError(p)
        paths.append(p)
    for inc in re.findall(r'^\s*\.include\s+(.+?)\s*$', s, re.M|re.I):
        p = Path(inc.strip().strip('"\''))
        if not p.is_absolute():
            p = (deck.parent/p).resolve()
        if not p.is_file():
            raise FileNotFoundError(p)
        paths.append(p)
    # Absolute includes remain valid when cases run from their own directories.
    def abs_inc(m):
        token = m[2].strip().strip('"\'')
        p = Path(token)
        if not p.is_absolute():
            p = (deck.parent/p).resolve()
        return m[1] + '"' + str(p) + '"' + (m[3] or '')
    s = re.sub(r'^(\s*\.lib\s+)(.+?)(\s+(?:typical|bjt_typical|res_typical))\s*$', abs_inc, s, flags=re.M|re.I)
    s = re.sub(r'^(\s*\.include\s+)(.+?)()\s*$', abs_inc, s, flags=re.M|re.I)
    return s, list(dict.fromkeys(paths))


def source_for_case(source, case, test):
    s = source
    for initial,key in [('typical','mos'),('bjt_typical','bjt'),('res_typical','res')]:
        s,n = re.subn(r'^(\s*\.lib\s+.+?\s+)'+initial+r'\s*$',
                       lambda m: m[1]+case[key], s, flags=re.M|re.I)
        if n != 1:
            raise ValueError('Ambiguous model section replacement: '+initial)
    s,n = re.subn(r'mim_corner_2p0fF\s*=\s*1(?:\.0)?\b',
                   'mim_corner_2p0fF='+str(MIM_FACTORS[case['mim']]), s, flags=re.I)
    if n != 1:
        raise ValueError('Expected one nominal MIM corner parameter assignment')
    s = re.sub(r'^\s*\.temp\s+[^\n]*', '.temp '+str(case['temperature_C']), s, flags=re.M|re.I)
    v = case['vdd_V'] if case['vdd_V'] is not None else 5.0
    if test == TESTS[2]:
        supply = f'PWL(0 0 1u 0 101u {v} 4m {v} 4001u 0 4500u 0 4501u {v} 6m {v})'
    else:
        supply = f'DC {v} AC '+('1' if test == TESTS[0] else '0')
    s = re.sub(r'^VDD\s+[^\n]*', 'VDD avdd 0 '+supply, s, flags=re.M|re.I)
    return s


def _base_control_for_case(template, test, c):
    out = 'case_report.txt'
    pre = f'''.control
set noaskquit
set numdgt=15
set wr_vecnames
set wr_singlescale
unset appendwrite
echo PVT_SINGLE_CASE > {out}
set appendwrite
'''
    if test == TESTS[1]:
        body = f'''save v(avdd) v(vref) i(vdd)
dc vdd {c['line_start_V']} {c['line_stop_V']} {c['line_step_V']}
let VREF_V=v(vref)
let IDD_UA=-i(vdd)*1e6
echo BEGIN_DC_DATA >> {out}
wrdata {out} VREF_V IDD_UA
echo END_DC_DATA >> {out}
echo END_OF_TB02_LINE_REGULATION_RUN >> {out}
'''
    else:
        body = template[template.index('save v(avdd)'):template.rindex('.endc')]
        body = re.sub(r'/foss/designs/chipalooza-bandgap/individual_tests/\S+_UPLOAD_THIS\.txt', out, body)
    return pre+body+'\nquit\n.endc\n.end\n'


def waveform_rows(text):
    active = False
    rows = []
    for line in text.splitlines():
        if line.startswith(('BEGIN_AC_DATA','BEGIN_DC_DATA','BEGIN_TRAN_DATA')):
            active = True
            continue
        if line.startswith(('END_AC_DATA','END_DC_DATA','END_TRAN_DATA')):
            active = False
        if active:
            try:
                values = [float(x) for x in line.split()]
            except ValueError:
                continue
            if len(values) >= 3:
                if not all(math.isfinite(x) for x in values):
                    raise ValueError('Nonfinite waveform data')
                rows.append(values)
    return rows


def line_metrics(rows, lo, hi):
    points = [r for r in rows if lo-1e-8 <= r[0] <= hi+1e-8]
    if len(points)<2 or abs(points[0][0]-lo)>1e-7 or abs(points[-1][0]-hi)>1e-7:
        raise ValueError('Line sweep does not include requested range endpoints')
    vs = [r[1] for r in points]
    span = max(vs)-min(vs)
    slopes = [(b[1]-a[1])/(b[0]-a[0])*1e3 for a,b in zip(points,points[1:])]
    return {'vdd_min_V':lo,'vdd_max_V':hi,'vref_min_V':min(vs),'vref_max_V':max(vs),
            'vref_at_low_V':vs[0],'vref_at_high_V':vs[-1], 'vref_span_mV':span*1e3,
            'span_percent_of_1p194V':span/1.194*100,'span_mV_per_V':span*1e3/(hi-lo),
            'endpoint_slope_mV_per_V':(vs[-1]-vs[0])*1e3/(hi-lo),
            'max_abs_adjacent_slope_mV_per_V':max(map(abs,slopes)),
            'max_IDD_uA':max(r[2] for r in points),
            'all_points_within_0p5pct_of_1p194V':all(abs(v-1.194)<=0.005*1.194 for v in vs)}


def _base_read_result(text, test, c):
    if 'END_OF_'+test+'_RUN' not in text:
        raise ValueError('Missing completion marker (simulation may have aborted)')
    metrics = {k:float(v) for k,v in re.findall(r'^([a-z0-9_]+)\s*=\s*([-+0-9.eE]+)$',text,re.M)}
    rows = waveform_rows(text)
    if not rows:
        raise ValueError('No waveform data exported')
    if test == TESTS[0]:
        if abs(rows[0][0]-1)>1e-8 or abs(rows[-1][0]-1e8)>1:
            raise ValueError('Incomplete AC sweep')
        band = [r for r in rows if r[0]<=1e6*(1+1e-9)]
        worst = min(band,key=lambda r:r[1])
        metrics.update(psrr_min_1hz_1mhz_db=worst[1],psrr_min_frequency_Hz=worst[0])
        required = ['op_valid','op_vref_v','op_idd_ua','psrr_1mhz_db','psrr_pass']
    elif test == TESTS[1]:
        metrics = {'nominal':line_metrics(rows,c['nominal_supply_min_V'],c['nominal_supply_max_V']),
                   'full_stress_sweep':line_metrics(rows,c['line_start_V'],c['line_stop_V'])}
        required = []
    else:
        if abs(rows[-1][0]-0.006)>1e-9:
            raise ValueError('Incomplete transient export')
        required = ['sim_end_s','pre_vref_v','final_vref_v','start_ready_300us','restart_ready_300us',
                    'start_peak_v','restart_peak_v','pre_valid','final_valid']
    if any(k not in metrics for k in required):
        raise ValueError('Missing required measurements')
    return metrics


def run_case(case, *, root, source, template, test, config, fingerprint, ngspice, retry_failed, compatible_fingerprints=()):
    d = root/'cases'/case['case_id']
    d.mkdir(parents=True,exist_ok=True)
    cache = d/'result.json'
    if config['resume'] and cache.exists():
        old = json.loads(cache.read_text())
        if old.get('fingerprint')==fingerprint and (old.get('status')=='complete' or not retry_failed):
            return dict(old,resumed=True)
        # Only completed results from the exact supported predecessor can migrate.
        # Legacy error/timeout results are never accepted through this path.
        if old.get('status')=='complete' and old.get('fingerprint') in compatible_fingerprints:
            migrated=dict(old,fingerprint=fingerprint,resumed=True,
                          cache_migrated_from_fingerprint=old['fingerprint'])
            atomic_json(cache,migrated)
            return migrated
    # Remove only this case's prior transient artifacts, so failure cannot reuse stale metrics.
    for name in ['case_report.txt','waveforms.txt.gz','run.log','circuit.spice']:
        (d/name).unlink(missing_ok=True)
    result = dict(case,fingerprint=fingerprint,status='failed',resumed=False)
    start = time.monotonic()
    try:
        case_config=dict(config,_case=case)
        deck = prepare_case_deck(source,case,test,config,template)
        (d/'circuit.spice').write_text(deck)
        with (d/'run.log').open('w') as log:
            p = subprocess.run([ngspice,'-b',str(d/'circuit.spice')],cwd=d,
                               stdout=log,stderr=subprocess.STDOUT,
                               timeout=config['case_timeout_seconds'])
        log = (d/'run.log').read_text(errors='replace')
        if p.returncode != 0:
            raise ValueError('ngspice exit '+str(p.returncode))
        if re.search(r'(?im)^\s*Error:|^\s*ERROR:|Warning from checkvalid|failed!|TRANSIENT_ABORTED',log):
            raise ValueError('ngspice analysis or measurement error; see run.log')
        warning_lines=[line.strip() for line in log.splitlines() if re.search(r'(?i)warning|unsupported|not recognized',line)]
        result['simulator_warnings']=list(dict.fromkeys(warning_lines))[:30]
        result['metrics'] = read_result((d/'case_report.txt').read_text(),test,case_config)
        # Compressed full traces remain plottable even when deck/log retention is off.
        import gzip
        with gzip.open(d/'waveforms.txt.gz','wt') as z: z.write((d/'case_report.txt').read_text())
        result['status'] = 'complete'
        if not config['retain_waveforms']:
            (d/'case_report.txt').unlink()
            (d/'circuit.spice').unlink()
            (d/'run.log').unlink()
    except subprocess.TimeoutExpired:
        result['status'] = 'timeout'
        result['error'] = 'Exceeded case_timeout_seconds; this is not a performance pass'
    except Exception as e:
        result['error'] = str(e)
    result['elapsed_seconds'] = round(time.monotonic()-start,3)
    if result['status'] != 'complete':
        log_path=d/'run.log'
        result['log_tail'] = log_path.read_text(errors='replace')[-1800:] if log_path.exists() else ''
    atomic_json(cache,result)
    return result


def _base_summarize(results,test):
    complete = [r for r in results if r['status']=='complete']
    summary = {'attempted':len(results),'simulation_complete':len(complete),
               'execution_failed_or_timed_out':len(results)-len(complete)}
    if test == TESTS[0]:
        for group in ['nominal','stress']:
            rr = [r for r in complete if r['range']==group]
            if rr:
                worst = min(rr,key=lambda r:r['metrics']['psrr_min_1hz_1mhz_db'])
                summary[group] = {'cases':len(rr),'psrr_pass_count':sum(r['metrics']['psrr_pass']==1 for r in rr),
                                  'minimum_PSRR_dB':worst['metrics']['psrr_min_1hz_1mhz_db'],
                                  'worst_case_id':worst['case_id']}
    elif test == TESTS[1]:
        for group in ['nominal','full_stress_sweep']:
            if complete:
                worst = max(complete,key=lambda r:r['metrics'][group]['vref_span_mV'])
                summary[group] = {'maximum_span_mV':worst['metrics'][group]['vref_span_mV'],
                                  'worst_case_id':worst['case_id']}
    else:
        for group in ['nominal','stress']:
            rr = [r for r in complete if r['range']==group]
            if rr:
                summary[group] = {'cases':len(rr),
                    'startup_ready_count':sum(r['metrics']['start_ready_300us']==1 for r in rr),
                    'restart_ready_count':sum(r['metrics']['restart_ready_300us']==1 for r in rr),
                    'maximum_start_peak_V':max(r['metrics']['start_peak_v'] for r in rr),
                    'maximum_restart_peak_V':max(r['metrics']['restart_peak_v'] for r in rr)}
    return summary


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--configure',action='store_true',help='Set this folder and netlist paths in all nine schematics; no simulation')
    ap.add_argument('--netlist-dir',type=Path,default=Path.home()/'.xschem'/'simulations',help='Netlist directory for --configure')
    ap.add_argument('--deck',type=Path)
    ap.add_argument('--test',choices=TESTS)
    ap.add_argument('--config',type=Path,default=HERE/'bandgap_config.json')
    ap.add_argument('--profile',help='Override the configured per-test profile: full, smoke, loop_smoke')
    ap.add_argument('--list-cases',action='store_true',help='Print coverage without netlisting or simulation')
    ap.add_argument('--ngspice',default='ngspice')
    ap.add_argument('--retry-failed',action='store_true')
    ap.add_argument('--max-cases',type=int,help='Debug only: report explicitly remains INCOMPLETE')
    args = ap.parse_args()
    if args.configure:
        if args.deck or args.test:
            ap.error("--configure cannot be combined with --deck or --test")
        configure(HERE,args.netlist_dir.expanduser().resolve())
        return 0
    if args.test is None or (args.deck is None and not args.list_cases):
        ap.error("simulation requires --deck and --test; use --configure for path setup")
    c,templates = load_config(args.config,args.test,args.profile)
    validate_config(c)
    if args.max_cases is not None and args.max_cases < 1: ap.error('--max-cases must be positive')
    if args.list_cases:
        planned=list(cases(c,args.test))
        print(json.dumps({'test':args.test,'profile':c['_profile'],'planned_cases':len(planned),'first_case':planned[0],'last_case':planned[-1]},indent=2))
        return 0
    source,model_paths = prepare_source(args.deck.resolve())
    model_paths = model_dependencies(model_paths)
    ng = shutil.which(args.ngspice)
    if ng is None:
        raise FileNotFoundError('ngspice executable not found: '+args.ngspice)
    ng = str(Path(ng).resolve())
    # Fail before the sweep for unavailable model sections.
    pdk_text='\n'.join(p.read_text(errors='replace') for p in model_paths)
    for key in ['mos_corners','bjt_corners','res_corners']:
        for section in c[key]:
            if not re.search(r'^\s*\.lib\s+'+re.escape(section)+r'\s*$',pdk_text,re.M|re.I):
                raise ValueError('PDK section not found: '+section)
    if args.test == 'TB06_MONTE_CARLO':
        for section in ['statistical','bjt_statistical','res_statistical']:
            if not re.search(r'^\s*\.lib\s+'+section+r'\s*$',pdk_text,re.M|re.I):
                raise ValueError('PDK statistical section unavailable: '+section)
    if args.test == 'TB08_POWER_DEVICE_LIMITS': c['_devices']=mos_devices(source)
    # Current fingerprint changes with this runner. Legacy fingerprints are also
    # recomputed from CURRENT source/config/models/executable, never trusted merely
    # because an old report exists.
    executable_bytes=Path(ng).read_bytes()
    dependency_bytes=[p.read_bytes() for p in model_paths]
    fingerprint=run_fingerprint(source,Path(__file__).read_bytes(),c,templates,
                                executable_bytes,dependency_bytes)
    compatible=compatible_legacy_fingerprints(source,c,templates,args.test,
                                             executable_bytes,dependency_bytes)
    all_cases=list(cases(c,args.test))
    selected=all_cases[:args.max_cases] if args.max_cases is not None else all_cases
    base=Path(c['results_directory']).expanduser().resolve();base.mkdir(parents=True,exist_ok=True)
    root=base/args.test;root.mkdir(exist_ok=True)
    report=base/(args.test+'_UPLOAD_THIS.txt')
    with (root/'runner.lock').open('w') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('This test is already running in the same results directory')
        print(f'{args.test}: {len(all_cases)} planned cases; {len(selected)} selected. Report: {report}',flush=True)
        results=[]
        with report.open('w',buffering=1) as out:
            out.write(args.test+'_PVT_V2\n')
            out.write('PROFILE '+c['_profile']+'\n')
            out.write('COVERAGE '+json.dumps(c,sort_keys=True)+'\n')
            out.write('RESUME_FINGERPRINT '+fingerprint+'\n')
            out.write('TB08_GROUND_FIX_INTEGRATED_LEGACY_COMPLETED_CACHE_MIGRATION_ENABLED\n')
            out.write('MIM_CHARGE_COMPATIBILITY_MODEL_NOT_UNMODIFIED_FOUNDRY_SUBCIRCUIT\n')
            out.write(('PDK_STATISTICAL_MODELS_MIM_FIXED_NO_EXTRACTED_LAYOUT' if args.test=='TB06_MONTE_CARLO' else 'FIXED_CORNERS_NO_MISMATCH_MONTE_CARLO_NO_EXTRACTED_LAYOUT')+'\n')
            out.write('SIMULATION_COMPLETE_IS_NOT_A_PERFORMANCE_PASS\n')
            with concurrent.futures.ThreadPoolExecutor(max_workers=int(c['parallel_jobs'])) as pool:
                # Only keep at most jobs*2 pending futures, preserving interruption responsiveness.
                iterator=iter(selected); pending={}
                def submit_next():
                    try: case=next(iterator)
                    except StopIteration:return False
                    f=pool.submit(run_case,case,root=root,source=source,template=templates[args.test],
                                  test=args.test,config=c,fingerprint=fingerprint,ngspice=ng,retry_failed=args.retry_failed,
                                  compatible_fingerprints=compatible)
                    pending[f]=case;return True
                for _ in range(int(c['parallel_jobs'])*2): submit_next()
                while pending:
                    done,_=concurrent.futures.wait(pending,return_when=concurrent.futures.FIRST_COMPLETED)
                    for f in done:
                        pending.pop(f);r=f.result();results.append(r)
                        out.write('CASE '+json.dumps(r,sort_keys=True,allow_nan=False)+'\n')
                        print(f'{len(results)}/{len(selected)} {r["case_id"]} {r["status"]}'+(' (resumed)' if r['resumed'] else ''),flush=True)
                        submit_next()
            summary=summarize(results,args.test)
            summary['planned_cases']=len(all_cases)
            out.write('SUMMARY '+json.dumps(summary,sort_keys=True)+'\n')
            if len(results)==len(all_cases):
                out.write('END_OF_'+args.test+'_PVT_RUN\n')
                if summary['execution_failed_or_timed_out']:
                    out.write('COVERAGE_HAS_FAILED_CASES_NOT_FULLY_VALIDATED\n')
                else:
                    out.write('ALL_PLANNED_SIMULATIONS_COMPLETED_CHECK_PERFORMANCE_METRICS\n')
            else:
                out.write('INCOMPLETE_DEBUG_LIMIT_NOT_FULL_COVERAGE\n')
        print('UPLOAD_THIS_FILE '+str(report),flush=True)
    return 0 if len(results)==len(all_cases) and not summary['execution_failed_or_timed_out'] else 2



# Temperature and conditional loop analyses.
TC = 'TB04_TEMPERATURE'
LG = 'TB05_LOOP_STABILITY'


def validate_loop_dut_connection(source):
    """Reject the supplied disconnected TB05 probes before scheduling a sweep."""
    top=[]
    depth=0
    for line in source.splitlines():
        tokens=line.split()
        if not tokens or tokens[0].startswith('*'):
            continue
        if tokens[0].lower()=='.subckt':
            depth+=1
        elif tokens[0].lower()=='.ends':
            depth=max(0,depth-1)
        elif depth==0:
            top.append([x.lower() for x in tokens])
    if not any(t[0]=='vlg_main' for t in top):
        return
    ports={'lg_main_e','lg_main_f','lg_bias_e','lg_bias_f'}
    if not any(t[0].startswith('x') and ports.issubset(set(t[1:])) for t in top):
        raise ValueError('TB05_LOOP_PROBES_NOT_CONNECTED: the DUT instance must connect '
                         'lg_main_e, lg_main_f, lg_bias_e and lg_bias_f to the intended '
                         'loop-probe core. The supplied three-pin Bandgap_Core and this '
                         'runner do not insert those cuts. No loop sweep was started.')


def prepare_source(deck):
    validate_loop_dut_connection(deck.read_text())
    source, paths = _base_prepare_source(deck)
    return source, paths


def validate_config(c):
    _base_validate_config(c)
    a,b,h=(c[k] for k in ['temperature_sweep_start_C','temperature_sweep_stop_C','temperature_sweep_step_C'])
    if not a < b or h <= 0 or abs((b-a)/h-round((b-a)/h))>1e-7:
        raise ValueError('Invalid dense temperature sweep')
    if not a <= 25 <= b or abs((25-a)/h-round((25-a)/h))>1e-7:
        raise ValueError('Temperature sweep must include exactly 25 C')
    if not 0 < c['loop_start_Hz'] < c['loop_stop_Hz'] or c['loop_points_per_decade'] < 20:
        raise ValueError('Invalid loop frequency sweep')


def cases(c,test):
    if test != TC:
        yield from _base_cases(c,test)
        return
    axes=[c[k] for k in ['mos_corners','bjt_corners','res_corners','mim_corners']]
    for mos,bjt,res,mim in itertools.product(*axes):
        for v in c['supply_voltages_V']:
            yield dict(mos=mos,bjt=bjt,res=res,mim=mim,temperature_C=25,vdd_V=v,
                temperature_sweep_C=[c['temperature_sweep_start_C'],c['temperature_sweep_stop_C'],c['temperature_sweep_step_C']],
                range='nominal' if c['nominal_supply_min_V']<=v<=c['nominal_supply_max_V'] else 'stress',
                case_id=f'{mos}_{bjt}_{res}_{mim}_Tsweep_V{v:g}'.replace('.','p'))


def control_for_case(template,test,c):
    if test not in (TC,LG):
        return _base_control_for_case(template,test,c)
    out='case_report.txt'
    s=f'''.control
set noaskquit
set numdgt=15
set wr_vecnames
set wr_singlescale
unset appendwrite
echo {test}_SINGLE_CASE > {out}
set appendwrite
'''
    if test==TC:
        s+=f'''save v(avdd) v(vref) i(vdd)
dc temp {c['temperature_sweep_start_C']} {c['temperature_sweep_stop_C']} {c['temperature_sweep_step_C']}
let IDD_UA=-i(vdd)*1e6
echo BEGIN_TC_DATA >> {out}
wrdata {out} v(vref) IDD_UA
echo END_TC_DATA >> {out}
'''
    else:
        s+=f'''save v(avdd) v(vref) v(lg_main_e) v(lg_main_f) v(lg_bias_e) v(lg_bias_f) i(vdd) i(VLG_MAIN) i(VLG_BIAS)
op
let OP_VREF_V=v(vref)
let OP_IDD_UA=-i(vdd)*1e6
let MAIN_DC_ERROR_V=v(lg_main_e)-v(lg_main_f)
let BIAS_DC_ERROR_V=v(lg_bias_e)-v(lg_bias_f)
print OP_VREF_V OP_IDD_UA MAIN_DC_ERROR_V BIAS_DC_ERROR_V >> {out}
let OP_REF_ERROR_V=abs(OP_VREF_V-1.194)
if OP_REF_ERROR_V gt 0.005*1.194
  echo LOOP_OPERATING_POINT_OUTSIDE_REFERENCE_TARGET_NO_MARGIN_ACCEPTED >> {out}
  echo LOOP_OPERATING_POINT_OUTSIDE_REFERENCE_TARGET_CHECK_DC_AND_STARTUP
  quit
end
'''
        for cut in ['main','bias']:
            for mode in ['voltage','current']:
                for other in ['MAIN','BIAS']:
                    s+=f'alter VLG_{other} acmag=0\nalter ILG_{other} acmag=0\n'
                s+=f'alter {"VLG" if mode=="voltage" else "ILG"}_{cut.upper()} acmag=1\n'
                s+=f'''ac dec {c['loop_points_per_decade']} {c['loop_start_Hz']} {c['loop_stop_Hz']}
echo BEGIN_{cut.upper()}_{mode.upper()} >> {out}
wrdata {out} real(v(lg_{cut}_e)) imag(v(lg_{cut}_e)) real(v(lg_{cut}_f)) imag(v(lg_{cut}_f)) real(i(VLG_{cut.upper()})) imag(i(VLG_{cut.upper()}))
echo END_{cut.upper()}_{mode.upper()} >> {out}
'''
    return s+f'echo END_OF_{test}_RUN >> {out}\nquit\n.endc\n.end\n'


def blocks(text):
    out={};active=None
    for line in text.splitlines():
        if line.startswith('BEGIN_'):
            active=line[6:].strip();out[active]=[]
        elif line.startswith('END_'):
            active=None
        elif active:
            try: row=[float(x) for x in line.split()]
            except ValueError:continue
            if len(row)>=3:
                if not all(math.isfinite(x) for x in row):
                    raise ValueError('Nonfinite waveform data')
                out[active].append(row)
    return out


def temperature_metrics(rows,c):
    lo,hi,step=[c[k] for k in ['temperature_sweep_start_C','temperature_sweep_stop_C','temperature_sweep_step_C']]
    n=round((hi-lo)/step)+1
    if len(rows)!=n or any(abs(r[0]-(lo+i*step))>1e-6 for i,r in enumerate(rows)):
        raise ValueError('Incomplete or incorrect temperature grid')
    vs=[r[1] for r in rows];mean=sum(vs)/n
    if mean<=0:
        raise ValueError('Nonpositive mean reference')
    v25=rows[round((25-lo)/step)][1]
    tc=(max(vs)-min(vs))/mean/(hi-lo)*1e6
    err=max(abs(v-1.194)/1.194*100 for v in vs)
    return dict(temperature_min_C=lo,temperature_max_C=hi,temperature_step_C=step,points=n,
        vref_at_25C_V=v25,vref_min_V=min(vs),vref_max_V=max(vs),vref_mean_V=mean,
        temperature_at_vref_min_C=rows[vs.index(min(vs))][0],temperature_at_vref_max_C=rows[vs.index(max(vs))][0],
        TC_box_ppm_per_C=tc,TC_normalized_to_1p194V_ppm_per_C=(max(vs)-min(vs))/1.194/(hi-lo)*1e6,
        max_absolute_error_percent=err,accuracy_pass=err<=0.5,TC_pass=tc<=10,
        max_IDD_uA=max(r[2] for r in rows),IDD_60uA_pass=max(r[2] for r in rows)<=60,
        temperature_accuracy_pass=(err<=0.5 and tc<=10))


def loop_gain(voltage,current):
    if len(voltage)!=len(current) or not voltage:
        raise ValueError('Missing or mismatched injection sweeps')
    values=[];conditions=[]
    for a,b in zip(voltage,current):
        if len(a)!=7 or len(b)!=7 or abs(a[0]-b[0])>1e-7*max(a[0],1):
            raise ValueError('Injection data mismatch')
        ev,fv,iv=complex(a[1],a[2]),complex(a[3],a[4]),complex(a[5],a[6])
        ei,fi,ii=complex(b[1],b[2]),complex(b[3],b[4]),complex(b[5],b[6])
        det=ev*fi-ei*fv
        scale=math.hypot(abs(ev),abs(fv))*math.hypot(abs(ei),abs(fi))
        conditioning=abs(det)/max(scale,1e-300);conditions.append(conditioning)
        if conditioning<1e-12 or det==0:
            raise ValueError('Ill-conditioned two-port reconstruction at '+str(a[0])+' Hz')
        yee=(-iv*fi-(1-ii)*fv)/det
        yef=((1-ii)*ev+iv*ei)/det
        yfe=(iv*fi-ii*fv)/det
        yff=(ii*ev-iv*ei)/det
        if abs(yee+yff)<1e-20:
            raise ValueError('Near-zero two-port loop-gain denominator')
        gain=(yef+yfe)/(yee+yff)
        if not math.isfinite(gain.real) or not math.isfinite(gain.imag):
            raise ValueError('Nonfinite loop gain')
        values.append((a[0],gain))
    return values,min(conditions)


def loop_metrics(values,conditioning,c):
    freq=[x[0] for x in values];g=[x[1] for x in values]
    if abs(freq[0]/c['loop_start_Hz']-1)>1e-6 or abs(freq[-1]/c['loop_stop_Hz']-1)>1e-6:
        raise ValueError('Incomplete loop frequency sweep')
    db=[20*math.log10(max(abs(z),1e-300)) for z in g]
    phase=[]
    for z in g:
        p=math.degrees(cmath.phase(z))
        if phase:
            while p-phase[-1]>180:p-=360
            while p-phase[-1]<-180:p+=360
        phase.append(p)
    # Report each crossing. PM is the distance to the next -180+360k phase boundary
    # on a lagging continuation; positive-feedback LF branches are flagged for review.
    unity=[];gm=[]
    for i in range(len(freq)-1):
        d0,d1=db[i:i+2];p0,p1=phase[i:i+2]
        if (d0>=0>d1) or (d0<0<=d1):
            w=-d0/(d1-d0);f=math.exp(math.log(freq[i])+w*math.log(freq[i+1]/freq[i]));p=p0+w*(p1-p0)
            principal=(p+180)%360-180
            # Conventional PM branch around a negative-feedback 0-degree LF loop.
            pm=180+p
            unity.append(dict(frequency_Hz=f,gain_direction='down' if d0>d1 else 'up',
                              unwrapped_phase_deg=p,phase_margin_deg=pm,principal_phase_deg=principal))
        if p1!=p0:
            lo,hi=sorted((p0,p1))
            k0=math.ceil((lo+180)/360);k1=math.floor((hi+180)/360)
            for k in range(k0,k1+1):
                target=-180+360*k
                if not (lo<=target<hi):continue
                w=(target-p0)/(p1-p0);f=math.exp(math.log(freq[i])+w*math.log(freq[i+1]/freq[i]))
                gm.append(dict(frequency_Hz=f,phase_deg=target,gain_margin_dB=-(d0+w*(d1-d0))))
    low_phase=phase[0]
    conventional=abs(low_phase)<45 and db[0]>0 and len(unity)==1 and unity[0]['gain_direction']=='down'
    sampled=min(range(len(g)),key=lambda i:abs(1+g[i]))
    if conventional:
        status='CONVENTIONAL_SINGLE_CROSSING_CONDITIONAL_MARGIN'
    elif not unity:
        status='NO_UNITY_CROSSING_IN_SWEEP_NO_PHASE_MARGIN'
    else:
        status='MULTIPLE_CROSSINGS_OR_NONSTANDARD_PHASE_REVIEW_REQUIRED'
    # Sample a compact curve into the consolidated upload file; full curves can be retained.
    indices=sorted(set([0,len(g)-1,sampled]+list(range(0,len(g),max(1,c['loop_points_per_decade']//2)))))
    samples=[dict(frequency_Hz=freq[i],gain_dB=db[i],phase_deg=phase[i],real=g[i].real,imag=g[i].imag) for i in indices]
    return dict(status=status,low_frequency_gain_dB=db[0],low_frequency_phase_deg=low_phase,
        unity_crossings=unity,phase_crossings=gm,
        phase_margin_deg=unity[0]['phase_margin_deg'] if conventional else None,
        minimum_gain_margin_dB=min((x['gain_margin_dB'] for x in gm),default=None) if conventional else None,
        low_frequency_positive_feedback_gain_headroom_dB=-db[0] if abs(abs(low_phase)-180)<1 else None,
        minimum_sampled_abs_1_plus_L=abs(1+g[sampled]),frequency_at_min_abs_1_plus_L_Hz=freq[sampled],
        minimum_normalized_injection_determinant=conditioning,
        whole_network_stability_certified=False,curve_samples=samples)


def read_result(text,test,c):
    if test not in (TC,LG):return _base_read_result(text,test,c)
    if test==LG and 'LOOP_OPERATING_POINT_OUTSIDE_REFERENCE_TARGET' in text:
        raise ValueError('Loop operating point outside the configured bench reference target (1.194 V +/-0.5%); inspect DC/startup before accepting margins')
    if 'END_OF_'+test+'_RUN' not in text:raise ValueError('Missing completion marker')
    data=blocks(text)
    if test==TC:return temperature_metrics(data.get('TC_DATA',[]),c)
    op={k:float(v) for k,v in re.findall(r'^([a-z0-9_]+)\s*=\s*([-+0-9.eE]+)$',text,re.M)}
    for k in ['op_vref_v','op_idd_ua','main_dc_error_v','bias_dc_error_v']:
        if k not in op:raise ValueError('Missing '+k)
    if max(abs(op['main_dc_error_v']),abs(op['bias_dc_error_v']))>1e-9:
        raise ValueError('Probe changed DC voltage continuity')
    op['reference_accuracy_valid']=abs(op['op_vref_v']-1.194)<=0.005*1.194
    op['loops']={}
    for cut in ['MAIN','BIAS']:
        vals,cond=loop_gain(data.get(cut+'_VOLTAGE',[]),data.get(cut+'_CURRENT',[]))
        op['loops'][cut.lower()]=loop_metrics(vals,cond,c)
    op['scope']='Two conditional loop cuts with other feedback paths closed; no blanket stability pass'
    return op


def summarize(results,test):
    if test not in (TC,LG):return _base_summarize(results,test)
    ok=[r for r in results if r['status']=='complete']
    s=dict(attempted=len(results),simulation_complete=len(ok),execution_failed_or_timed_out=len(results)-len(ok))
    for group in ['nominal','stress']:
        rr=[r for r in ok if r['range']==group]
        if not rr:continue
        if test==TC:
            worst=max(rr,key=lambda r:r['metrics']['TC_box_ppm_per_C'])
            s[group]=dict(cases=len(rr),TC_accuracy_pass_count=sum(r['metrics']['temperature_accuracy_pass'] for r in rr),
                maximum_TC_ppm_per_C=worst['metrics']['TC_box_ppm_per_C'],worst_TC_case=worst['case_id'],
                maximum_absolute_error_percent=max(r['metrics']['max_absolute_error_percent'] for r in rr))
        else:
            s[group]={'cases':len(rr),'loops':{}}
            for cut in ['main','bias']:
                conventional=[r for r in rr if r['metrics']['loops'][cut]['phase_margin_deg'] is not None]
                s[group]['loops'][cut]=dict(conventional_margin_cases=len(conventional),review_required_cases=len(rr)-len(conventional))
                if conventional:
                    worst=min(conventional,key=lambda r:r['metrics']['loops'][cut]['phase_margin_deg'])
                    s[group]['loops'][cut].update(minimum_conditional_PM_deg=worst['metrics']['loops'][cut]['phase_margin_deg'],worst_case=worst['case_id'])
    if test==LG:s['whole_network_stability_certified']=False
    return s



# Optional path configuration.
def quoted(value):
    if any(c in str(value) for c in '\n\r\x00$`"\\{}'):
        raise ValueError('Use a folder path without newlines, dollar signs, backticks, quotes, backslashes or braces')
    return '"'+str(value)+'"'

def configure(folder,netlist_dir):
    # Resolve and validate every edit before writing any file.
    updates=[]
    for test in TESTS:
        p=folder/(test+'.sch');s=p.read_text()
        runner='run_bandgap.py'
        cmd='shell python3 '+quoted(folder/runner)+' --deck '+quoted(netlist_dir/(test+'.spice'))+' --test '+test
        if test=='TB05_LOOP_STABILITY':
            pass # TB05 default profile is selected in the single configuration file.
        value='.control\nset noaskquit\necho BANDGAP_SINGLE_RUNNER_V9_'+test+'\n'+cmd+'\necho RUNNER_RETURNED_CHECK_REPORT_AND_ERRORS\n.endc\n'
        encoded=value.replace('\\','\\\\').replace('"','\\"')
        replacement='C {code.sym} 530 420 0 0 {name=TEST only_toplevel=true format="@value" value="'+encoded+'"}'
        s,n=re.subn(r'C \{code.sym\} 530 420 0 0 \{name=TEST.*?\n"\}',lambda m:replacement,s,flags=re.S)
        if n!=1:raise ValueError('Expected one TEST block: '+str(p))
        # Bind to this folder's exact core, not an old library alias.
        core=str(folder/('Bandgap_Core_LoopProbe.sym' if test=='TB05_LOOP_STABILITY' else 'Bandgap_Core.sym'));quoted(core)
        s,n=re.subn(r'C \{[^\n{}]*Bandgap_Core(?:_LoopProbe)?(?:\(1\))?\.sym\} 400 240 0 0 \{name=x1\}',lambda m:'C {'+core+'} 400 240 0 0 {name=x1}',s)
        if n!=1:raise ValueError('Expected one core instance: '+str(p))
        updates.append((p,s))
    for p,s in updates:p.write_text(s)
    print('Configured nine testbenches in '+str(folder))
    print('Expected Xschem netlist directory: '+str(netlist_dir))
    print('Open canonical TBxx filenames, regenerate the netlist, then simulate.')
    print('TB05 defaults to loop_smoke; override test_profiles in bandgap_config.json for full.')


# TB06-TB09 and consolidated configuration. Existing TB01-TB05 math stays above.
MC, NOISE, POWER, DISTURB = TESTS[5:]
_previous_cases, _previous_source = cases, source_for_case
_previous_control, _previous_read, _previous_summary = control_for_case, read_result, summarize
_previous_validate = validate_config


def model_dependencies(paths):
    """Hash nested model includes as well as the directly included model files.
    The deck's simulator executable and source are hashed by main().
    """
    pending=list(paths); seen=set(); out=[]
    while pending:
        p=Path(pending.pop()).resolve()
        if p in seen: continue
        seen.add(p); out.append(p)
        for line in p.read_text(errors='replace').splitlines():
            m=re.match(r"^\s*\.(?:include|inc|lib)\s+(?:['\"]([^'\"]+)['\"]|([^\s]+))",line,re.I)
            if not m: continue
            token=m[1] or m[2]
            # .lib SECTION declarations have no file path and no second token.
            if re.match(r'^\s*\.lib\s+\S+\s*$',line,re.I): continue
            candidate=Path(token)
            if not candidate.is_absolute(): candidate=p.parent/candidate
            if candidate.is_file(): pending.append(candidate)
            elif '.' in token or '/' in token:
                raise FileNotFoundError('Nested model dependency not found: '+str(candidate))
    return sorted(out)


def load_config(path, test, profile=None):
    path=Path(path).expanduser().resolve(); doc=json.loads(path.read_text())
    if doc.get('schema_version') != 3:
        raise ValueError('Use the consolidated bandgap_config.json (schema_version 3)')
    profile=profile or doc.get('test_profiles',{}).get(test,doc['default_profile'])
    if profile not in doc['profiles']: raise ValueError('Unknown profile: '+profile)
    c=dict(doc['defaults']); c.update(doc.get('test_overrides',{}).get(test,{})); c.update(doc['profiles'][profile])
    root=Path(doc['output_directory']).expanduser()
    if not root.is_absolute(): root=path.parent/root
    c.update(results_directory=str(root.resolve()/profile),_profile=profile)
    if any(not isinstance(v,str) for v in doc['controls'].values()): raise ValueError('Control templates must be strings')
    if set(doc['controls']) != set(TESTS): raise ValueError('controls must contain all nine test names')
    return c,doc['controls']


def validate_config(c):
    _previous_validate(c)
    for key in ['mc_samples','mc_seed_start','repeated_cycle_count','noise_points_per_decade']:
        if type(c[key]) is not int or c[key]<1: raise ValueError(key+' must be a positive integer')
    if c['mc_seed_start']+c['mc_samples']>=2147483647: raise ValueError('MC seed exceeds signed 32-bit range')
    if not c['mc_modes'] or not set(c['mc_modes']) <= {'global','mismatch','combined'}: raise ValueError('Invalid mc_modes')
    if len(set(c['mc_modes']))!=len(c['mc_modes']): raise ValueError('Duplicate mc_modes')
    if not 0<c['noise_start_Hz']<c['noise_stop_Hz']: raise ValueError('Invalid noise frequency range')
    for a,b in c['noise_bands_Hz']:
        if not c['noise_start_Hz']<=a<b<=c['noise_stop_Hz']: raise ValueError('Noise integration band outside sweep')
    for key in ['startup_stop_s','startup_ramp_s','transient_max_step_s','recovery_limit_s','recovery_observe_s','disturbance_hold_s','disturbance_edge_s','reference_target_V','reference_tolerance_fraction','idd_limit_uA']:
        if not isinstance(c[key],(int,float)) or not math.isfinite(c[key]) or c[key]<=0: raise ValueError('Invalid '+key)
    if c['startup_stop_s']<=c['startup_ramp_s']+1e-6: raise ValueError('Startup must continue after ramp')
    if c['recovery_observe_s']<c['recovery_limit_s']: raise ValueError('Observation window shorter than recovery deadline')
    for key in ['disturbance_ramps_s','brownout_durations_s']:
        if not c[key] or len(set(c[key]))!=len(c[key]) or any(v<=0 or not math.isfinite(v) for v in c[key]): raise ValueError('Invalid '+key)
    if not c['supply_step_levels_V'] or len(set(c['supply_step_levels_V']))!=len(c['supply_step_levels_V']) or any(not 0<v<=5.5 for v in c['supply_step_levels_V']): raise ValueError('Invalid supply_step_levels_V')
    if not c['brownout_levels_V'] or len(set(c['brownout_levels_V']))!=len(c['brownout_levels_V']) or any(v<0 or v>=min(c['supply_voltages_V']) for v in c['brownout_levels_V']): raise ValueError('Brownout levels must be below every selected supply')
    if not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_]*',c['intrinsic_mos_name']): raise ValueError('Invalid intrinsic_mos_name')
    if not c['device_screen_limits_V'] or any(v<=0 or not math.isfinite(v) for v in c['device_screen_limits_V'].values()): raise ValueError('Invalid device screening limits')


def cases(c,test):
    if test==MC:
        # Statistical libraries replace deterministic process corners. Mixing global
        # random process shifts with ff/ss is not a population-yield calculation.
        for mode, sample in itertools.product(c['mc_modes'],range(c['mc_samples'])):
            seed=c['mc_seed_start']+sample
            for temp,v in itertools.product(c['temperatures_C'],c['supply_voltages_V']):
                yield dict(mos='statistical',bjt='bjt_statistical',res='res_statistical',mim='mimcap_typical',
                    temperature_C=temp,vdd_V=v,mc_mode=mode,sample=sample,seed=seed,
                    range='nominal' if c['nominal_supply_min_V']<=v<=c['nominal_supply_max_V'] else 'stress',
                    case_id=f'{mode}_S{seed}_T{temp:g}_V{v:g}'.replace('.','p').replace('-','m'))
    elif test==DISTURB:
        scenarios=[dict(kind='ramp',ramp_s=r) for r in c['disturbance_ramps_s']]
        scenarios += [dict(kind='brownout',low_V=v,duration_s=t) for v,t in itertools.product(c['brownout_levels_V'],c['brownout_durations_s'])]
        scenarios += [dict(kind='cycles',low_V=0,duration_s=max(c['brownout_durations_s']))]
        for base in _base_cases(c,test):
            steps=[dict(kind='step',low_V=v,duration_s=c['disturbance_hold_s']) for v in c['supply_step_levels_V'] if abs(v-base['vdd_V'])>1e-9]
            for i,sc in enumerate(scenarios+steps):
                yield dict(base,scenario=sc,case_id=base['case_id']+f'_event{i:02d}_{sc["kind"]}')
    else: yield from _previous_cases(c,test)


def disturbance_waveform(case,c):
    v=case['vdd_V']; sc=case['scenario']; edge=c['disturbance_edge_s']; hold=c['disturbance_hold_s']; obs=c['recovery_observe_s']
    if sc['kind']=='ramp':
        end=1e-6+sc['ramp_s']; return [(0,0),(1e-6,0),(end,v),(end+obs,v)],[end],end+obs
    # Establish a real cold start, then wait before disturbing the rail.
    ramp=1e-6+c['startup_ramp_s']; t=ramp+obs+hold
    pts=[(0,0),(1e-6,0),(ramp,v),(t,v)]; recover=[]
    count=c['repeated_cycle_count'] if sc['kind']=='cycles' else 1
    for _ in range(count):
        pts.extend([(t+edge,sc['low_V']),(t+edge+sc['duration_s'],sc['low_V'])])
        end=t+2*edge+sc['duration_s']; pts.append((end,v)); recover.append(end)
        t=end+obs+hold; pts.append((t,v))
    return pts,recover,t


def source_for_case(source,case,test):
    s=_previous_source(source,case,test)
    if test==MC:
        for key,on in [('sw_stat_global',case['mc_mode']!='mismatch'),('sw_stat_mismatch',case['mc_mode']!='global')]:
            s,n=re.subn(r'\b'+key+r'\s*=\s*0\b',key+'='+str(int(on)),s,flags=re.I)
            if n!=1: raise ValueError('Expected one disabled statistical switch: '+key)
        # MIM bank remains its original charge-form model. Its fixed nominal
        # capacitance has no effect on this DC-only mismatch/accuracy measurement.
    elif test==NOISE:
        s=re.sub(r'^VDD\s+[^\n]*',f'VDD avdd 0 DC {case["vdd_V"]} AC 1',s,flags=re.M|re.I)
    # Waveforms require config, inserted by control_for_case through a parameter
    # independent .alter is avoided; run_case prepares them in per-case source below.
    return s


def spice_statements(source):
    joined=re.sub(r'\n\s*\+\s*',' ',source)
    return [l.split() for l in joined.splitlines() if l.strip() and not l.lstrip().startswith('*')]


def mos_devices(source):
    """Extract MOS subcircuit instances from the actual connected Bandgap_Core.
    Never assume the top instance is XDUT; uploaded schematics use x1.
    Unsupported nested custom blocks fail instead of silently omitting devices.
    """
    sub={}; top=[]; active=None
    for t in spice_statements(source):
        if t[0].lower()=='.subckt':
            active=t[1].lower(); sub[active]={'ports':[v.lower() for v in t[2:] if '=' not in v],'lines':[]}
        elif t[0].lower()=='.ends': active=None
        elif active: sub[active]['lines'].append(t)
        else: top.append(t)
    dut=[t for t in top if t[0].lower().startswith('x') and any(v.lower()=='bandgap_core' for v in t)]
    if len(dut)!=1 or 'bandgap_core' not in sub: raise ValueError('Expected one embedded Bandgap_Core DUT for device screening')
    inst=dut[0]; body=sub['bandgap_core']; idx=next(i for i,v in enumerate(inst) if v.lower()=='bandgap_core')
    if len(inst[1:idx])!=len(body['ports']): raise ValueError('DUT formal/actual pin count mismatch')
    mapping=dict(zip(body['ports'],[n.lower() for n in inst[1:idx]])); prefix=inst[0].lower()
    devices=[]
    for t in body['lines']:
        if not t[0].lower().startswith('x'): continue
        model=t[5].lower() if len(t)>5 else ''
        if re.search(r'(?:n|p)fet_0[356]v[03]',model):
            nodes=[mapping.get(n.lower(),prefix+'.'+n.lower()) if n!='0' else '0' for n in t[1:5]]
            nodes=[ground_name(n) for n in nodes]
            devices.append(dict(name=t[0],path=prefix+'.'+t[0].lower(),model=model,nodes=nodes))
        elif any(x.lower() in sub for x in t[1:] if '=' not in x):
            # Known primitive MIM is embedded; custom hierarchy needs explicit support.
            if not any(x.lower()=='cap_mim_2f0ff' for x in t): raise ValueError('Nested custom DUT block needs device probe support: '+t[0])
    if not devices: raise ValueError('No MOS devices found in Bandgap_Core')
    return devices


def prepare_case_deck(source,case,test,c,template):
    s=source_for_case(source,case,test)
    if test in (POWER,DISTURB):
        if test==POWER:
            end=1e-6+c['startup_ramp_s']; points=[(0,0),(1e-6,0),(end,case['vdd_V']),(c['startup_stop_s'],case['vdd_V'])]
        else: points,_,_=disturbance_waveform(case,c)
        wave='PWL('+' '.join(f'{t:.15g} {v:.15g}' for t,v in points)+')'
        # DC value is deliberately nominal for the OP screen. UIC transient starts
        # at zero and follows the PWL, independent of the OP analysis.
        s=re.sub(r'^VDD\s+[^\n]*',f'VDD avdd 0 DC {case["vdd_V"]} '+wave,s,flags=re.M|re.I)
    return s+control_for_case(template,test,dict(c,_case=case))


def export_block(name,vectors):
    return f'echo BEGIN_{name} >> case_report.txt\nwrdata case_report.txt {vectors}\necho END_{name} >> case_report.txt\n'


def control_for_case(template,test,c):
    if test not in (MC,NOISE,POWER,DISTURB): return _previous_control(template,test,c)
    case=c['_case']; out='case_report.txt'
    s=f'.control\nset noaskquit\nset numdgt=15\nset wr_vecnames\nset wr_singlescale\nunset appendwrite\necho {test}_SINGLE_CASE > {out}\nset appendwrite\n'
    if test==MC:
        # Reparse after resetting the random generator. Each PVT point uses the
        # same seed and deck ordering, preserving its model draw across V/T.
        s+=f'setseed {case["seed"]}\nreset\n'
    s+='save all\n'
    if test==POWER:
        for d in c['_devices']:
            base='@m.'+d['path']+'.'+c['intrinsic_mos_name']
            s+=f'save {base}[vdsat] {base}[gm] {base}[id]\n'
    s+='op\nlet OP_VREF_V=v(vref)\nlet OP_IDD_UA=-i(vdd)*1e6\nprint OP_VREF_V OP_IDD_UA >> case_report.txt\n'
    if test==NOISE:
        s+='unset sqrnoise\n'
        s+=f'noise v(vref) VDD dec {c["noise_points_per_decade"]} {c["noise_start_Hz"]} {c["noise_stop_Hz"]} 1\nsetplot noise1\n'
        s+='let OUTPUT_ASD=onoise_spectrum\nlet OUTPUT_PSD=OUTPUT_ASD*OUTPUT_ASD\n'
        s+=export_block('NOISE_DATA','OUTPUT_ASD OUTPUT_PSD')
    if test==POWER:
        for i,d in enumerate(c['_devices']):
            dn,gn,sn,bn=d['nodes']; base='@m.'+d['path']+'.'+c['intrinsic_mos_name']
            for label,a,b in [('vds',dn,sn),('vgs',gn,sn),('vgd',gn,dn),('vgb',gn,bn),('vdb',dn,bn),('vsb',sn,bn)]:
                expr=voltage(a,b)
                s+=f'let dev{i}_{label}={expr}\nprint dev{i}_{label} >> {out}\n'
            for par in ['vdsat','gm','id']:
                s+=f'let dev{i}_{par}={base}[{par}]\nprint dev{i}_{par} >> {out}\n'
    if test in (POWER,DISTURB):
        stop=c['startup_stop_s'] if test==POWER else disturbance_waveform(case,c)[2]
        step=c['transient_max_step_s']
        s+=f'tran {step:.15g} {stop:.15g} 0 {step:.15g} uic\nlet IDD_UA=-i(vdd)*1e6\n'
        s+=export_block('TRAN_DATA','v(avdd) v(vref) IDD_UA')
        if test==POWER:
            for i,d in enumerate(c['_devices']):
                dn,gn,sn,bn=d['nodes']
                for label,a,b in [('vds',dn,sn),('vgs',gn,sn),('vgd',gn,dn),('vgb',gn,bn),('vdb',dn,bn),('vsb',sn,bn)]:
                    s+=f'let dev{i}_{label}_wave=abs({voltage(a,b)})\n'
                    s+=f'meas tran dev{i}_{label}_peak MAX dev{i}_{label}_wave\nprint dev{i}_{label}_peak >> {out}\n'
    return s+f'echo END_OF_{test}_RUN >> {out}\nquit\n.endc\n.end\n'


def ground_name(node):
    node=node.strip().lower()
    return '0' if node in ('0','gnd') else node


def voltage(a,b):
    a,b=ground_name(a),ground_name(b)
    if a==b:return '0*v(avdd)'
    if b=='0': return 'v('+a+')'
    if a=='0': return '-v('+b+')'
    return 'v('+a+')-v('+b+')'


def scalars(text):
    pairs=re.findall(r'^([a-z0-9_]+)\s*=\s*([-+0-9.eE]+)\s*$',text,re.M|re.I)
    vals={k.lower():float(v) for k,v in pairs}
    if any(not math.isfinite(v) for v in vals.values()): raise ValueError('Nonfinite measurement')
    return vals


def integrate_psd(rows,lo,hi):
    """Log-log power-law interpolation/integration of a nonnegative PSD.
    Unlike trapezoids across wide logarithmic steps, this is exact for 1/f.
    """
    total=0.
    for r1,r2 in zip(rows,rows[1:]):
        x1,y1=r1[0],r1[2]; x2,y2=r2[0],r2[2]
        a,b=max(lo,x1),min(hi,x2)
        if b<=a:continue
        if y1>0 and y2>0:
            k=math.log(y2/y1)/math.log(x2/x1); ya=y1*(a/x1)**k
            total+=ya*a*math.log(b/a) if abs(k+1)<1e-10 else ya*a*math.expm1((k+1)*math.log(b/a))/(k+1)
        else:
            ya=y1+(y2-y1)*(a-x1)/(x2-x1); yb=y1+(y2-y1)*(b-x1)/(x2-x1)
            total+=(ya+yb)/2*(b-a)
    return math.sqrt(total)


def recovery_metrics(rows,start,end,c):
    pts=[r for r in rows if start-1e-12<=r[0]<=end+1e-12]
    if len(pts)<2 or pts[-1][0]<end-2*c['transient_max_step_s']: raise ValueError('Recovery window incomplete')
    target=c['reference_target_V']; tol=target*c['reference_tolerance_fraction']
    last_bad=max((i for i,r in enumerate(pts) if abs(r[2]-target)>tol),default=-1)
    settled=None if last_bad==len(pts)-1 else max(0,pts[last_bad+1][0]-start)
    # Ready means stays in-band to the end of this observation window.
    return dict(recovery_edge_s=start,observation_end_s=end,settling_time_s=settled,
                ready_by_deadline=settled is not None and settled<=c['recovery_limit_s'],
                final_vref_V=pts[-1][2],vref_min_V=min(r[2] for r in pts),vref_peak_V=max(r[2] for r in pts),
                overshoot_above_target_mV=max(0,max(r[2] for r in pts)-target)*1e3)


def read_result(text,test,c):
    if test not in (MC,NOISE,POWER,DISTURB): return _previous_read(text,test,c)
    if 'END_OF_'+test+'_RUN' not in text: raise ValueError('Missing completion marker')
    m=scalars(text)
    if any(k not in m for k in ['op_vref_v','op_idd_ua']): raise ValueError('Missing operating point')
    target=c['reference_target_V']; err=m['op_vref_v']-target
    m.update(absolute_error_percent=abs(err)/target*100,op_reference_in_target=abs(err)<=c['reference_tolerance_fraction']*target,
        power_uW=m['op_idd_ua']*c['_case']['vdd_V'],idd_within_limit=0<=m['op_idd_ua']<=c['idd_limit_uA'])
    if test==MC:
        m.update(required_output_correction_mV=-err*1e3,physical_trim_simulated=False,
                 scope='DC statistical accuracy and power; correction is an ideal output offset requirement, not a resistor trim code; no MC startup/noise/PSRR signoff')
        return m
    data=blocks(text)
    if test==NOISE:
        rows=data.get('NOISE_DATA',[])
        if len(rows)<2 or abs(rows[0][0]/c['noise_start_Hz']-1)>1e-6 or abs(rows[-1][0]/c['noise_stop_Hz']-1)>1e-6: raise ValueError('Incomplete noise sweep')
        if any(r[1]<0 or r[2]<0 or len(r)!=3 for r in rows) or not any(r[2]>0 for r in rows): raise ValueError('Invalid or zero noise spectrum; review PDK noise support')
        if any(b[0]<=a[0] for a,b in zip(rows,rows[1:])): raise ValueError('Nonmonotonic noise frequencies')
        m['bands']=[dict(low_Hz=a,high_Hz=b,output_rms_uV=integrate_psd(rows,a,b)*1e6) for a,b in c['noise_bands_Hz']]
        m.update(noise_requirement_pass=None,noise_qualified_at_target=m['op_reference_in_target'],noise_scope='Output ASD and integrated output RMS using installed PDK models; no numerical noise requirement assigned')
        return m
    rows=data.get('TRAN_DATA',[])
    stop=c['startup_stop_s'] if test==POWER else disturbance_waveform(c['_case'],c)[2]
    if len(rows)<2 or abs(rows[-1][0]-stop)>max(1e-12,stop*1e-7): raise ValueError('Incomplete transient')
    if any(len(r)!=4 for r in rows): raise ValueError('Transient export column mismatch')
    m.update(transient_peak_IDD_uA=max(r[3] for r in rows),transient_final_vref_V=rows[-1][2])
    if test==POWER:
        devs=[]
        for i,d in enumerate(c['_devices']):
            dv=dict(d)
            for key in ['vds','vgs','vgd','vgb','vdb','vsb','vdsat','gm','id']:
                dv[key]=m.pop(f'dev{i}_{key}')
            dv['startup_max_abs_V']={k:m.pop(f'dev{i}_{k}_peak') for k in ['vds','vgs','vgd','vgb','vdb','vsb']}
            family=next((k for k in c['device_screen_limits_V'] if k in d['model']),None)
            if family is None: raise ValueError('No voltage screening threshold for '+d['model'])
            limit=c['device_screen_limits_V'][family]
            worst=max([abs(dv[k]) for k in ['vds','vgs','vgd','vgb','vdb','vsb']]+list(dv['startup_max_abs_V'].values()))
            dv.update(screen_limit_V=limit,max_abs_terminal_V=worst,voltage_screen_flag=worst>limit,
                saturation_margin_V=abs(dv['vds'])-abs(dv['vdsat']),gm_over_id_per_V=abs(dv['gm']/dv['id']) if abs(dv['id'])>1e-15 else None)
            devs.append(dv)
        m['devices']=devs
        m['voltage_screen_flag_count']=sum(d['voltage_screen_flag'] for d in devs)
        m['foundry_reliability_signoff']=False
        m['device_scope']='Conservative user-editable voltage screens, not foundry absolute maxima; saturation margin is DC only. BJT/passive/ERC and extracted-layout checks remain separate.'
        m['startup']=recovery_metrics(rows,1e-6+c['startup_ramp_s'],stop,c)
    else:
        _,edges,_=disturbance_waveform(c['_case'],c)
        events=[recovery_metrics(rows,t,t+c['recovery_observe_s'],c) for t in edges]
        sc=c['_case']['scenario']
        baseline=None if sc['kind']=='ramp' else recovery_metrics(rows,1e-6+c['startup_ramp_s'],1e-6+c['startup_ramp_s']+c['recovery_observe_s'],c)
        if sc['kind']=='step':
            after=[r for r in rows if r[0]>=1e-6+c['startup_ramp_s']+c['recovery_observe_s']]
            m['step_max_reference_deviation_mV']=max(abs(r[2]-target)*1e3 for r in after)
        m.update(events=events,baseline_startup=baseline,
                 all_events_ready=all(e['ready_by_deadline'] for e in events) and (baseline is None or baseline['ready_by_deadline']),
                 max_recovery_overshoot_mV=max(e['overshoot_above_target_mV'] for e in events))
    return m


def summarize(results,test):
    if test not in (MC,NOISE,POWER,DISTURB): return _previous_summary(results,test)
    ok=[r for r in results if r['status']=='complete']
    s=dict(attempted=len(results),simulation_complete=len(ok),execution_failed_or_timed_out=len(results)-len(ok))
    for group in ['nominal','stress']:
        rr=[r for r in ok if r['range']==group]
        if not rr:continue
        ss=dict(cases=len(rr),reference_in_target_count=sum(r['metrics']['op_reference_in_target'] for r in rr))
        if test==MC:
            ss['modes']={}
            for mode in sorted({r['mc_mode'] for r in rr}):
                subset=[r for r in rr if r['mc_mode']==mode]
                samples={seed:[r for r in subset if r['seed']==seed] for seed in {r['seed'] for r in subset}}
                ss['modes'][mode]=dict(completed_sample_ids=len(samples),completed_PVT_points=len(subset),
                    accuracy_pass_PVT_points=sum(r['metrics']['op_reference_in_target'] for r in subset),
                    maximum_required_correction_mV=max(abs(r['metrics']['required_output_correction_mV']) for r in subset))
            ss['population_yield_certified']=False
        elif test==NOISE:ss['noise_requirement_pass']=None
        elif test==POWER:ss.update(idd_pass_count=sum(r['metrics']['idd_within_limit'] for r in rr),cases_with_voltage_flags=sum(r['metrics']['voltage_screen_flag_count']>0 for r in rr))
        else:ss.update(all_events_ready_count=sum(r['metrics']['all_events_ready'] for r in rr),maximum_overshoot_mV=max(r['metrics']['max_recovery_overshoot_mV'] for r in rr))
        s[group]=ss
    return s



# Resume compatibility for the exact previously delivered suite-v9 runner.
# This compressed source is DATA ONLY: it is decompressed to reproduce the old
# SHA-256 input, never imported or executed. It avoids needing a second .py file.
# Compatibility is appropriate for this release because other test algorithms
# are unchanged and TB08 is equivalent to the published ground-fix wrapper.
# Future algorithm changes must narrow/remove this predecessor compatibility.
_LEGACY_RUNNER_SHA256 = "b9e4da86e6d2c1339bbcd4bea579833d076a11a3ea21b9f554aa0d8faf82abb5"
_LEGACY_TB08_PATCH_SHA256 = "a24f23277a8a1485de6c15118b2e94d573856b910440538dda1ded8f9b1f0921"
_LEGACY_RUNNER_B85 = (
    'c-rlK|5xKUw&(Bs6>j?NaZH?$P+c|MP_BLyP~GfMz(T5eW<#FWiJjmfu`_lOplSa1y<a3*vYkN9%zN+bIooHZh;8ZWO1iqby1M%4'
    '`|oy_dA2)@lies;S@XxmZJNB<+TPy&lEmXU3awv0b${$wizr`M*)mC@Y~SjA>~vf3&rhzEMe{UU#K{DI=F3^+T0s(8t=1?_#_?pC'
    'MeVIiB5LIe_!4BHHI0W^kUd&yGJR}Y7fECd;mahL`<$u$w;Yo%=ksYC<yIaouz=jP=2<$9r|=4kfV7J&odRdG`7{9j+FQWVTVUhw'
    '%NTgE7PpZVCyOWvp%&9Lowp$WFoKN86x47lo+0yAkWJ=6mPhh=Gz%8D>LE==%PfnMMSHwlKz(xU%OZMMKyBok@hDkL<-=`|-)i6D'
    'MU*YlbgHsrCFO6uz%<_)XX(tE!#l`tiPx7}l1#Ch-!2!iDl%UVp^Bp@SB2z{>gOV!MO$0Ho?M++9#L!fKDMUsJ8h^{I$cE#rwt7O'
    'Ro&{HT=%XaUBkw{_Ajrmu58!Bhdux7^!&uXI{D?x*<tVW;#|Cc<6rj<uX<lD;S>E5?|<-nC!a4*t`2)&u1>_exBl71#U*C=czSl)'
    '`>S~U&i{OI-aGM+4zJEG#JfNF=NG5fGUJc_<;8C&SN`$I*VCgD;N<gZ?^=BO$-n+`d3p9%|M>J8%KCVCesp3xTc1xq`=1VvdKXt%'
    'pC@}3&qg3=i^q993a0kH)opixfOtI~!<$a~r{YbXQ=0Dc*5TP16n@N9(j0^}gVBJWpKM9awSj_bLnioz|Kwx)+1;{=|Lo!47DiTl'
    'F0$hjk-#57rj!{v%E*k*MP_`W%=n|48ET|uhGEsv8pnCw+S&@Eu@x-RSv>MlJR2y3t`!E0z}Y8KIM|>8@O}F}UflZmay*V78g_dz'
    'n?q~MH0}Eg1m4H-(LhS=a5<aj4W#74pbSCAygg7A(`kC|Cqd$U3Z{AFSWU~mNpw1(U#7t*B2FB^p+5}r$X^B180bYpX*5QH#c`Th'
    'chRFD4nsdqEYWps;AxgOL_+*89$QHYL%9z*1{UO;Mo9x(hTk}j^_@rW#4{$r3|bQFy(f#>*PGkQf;f+?ufcQ~on%>>HSE)bm_{Pu'
    '5|rBr*tb@gASbqMs6Wtj^m-useH+^%$^z0q{t?O*YR5-^l};DI1m1nM2ODaIPrzd%&f^5tFf{1OZH%XBuy8>|LN!sNq84h$`8ZCX'
    'of<2LSXdzgqN=a0pHUCNklu)*P4#wuiS)5*FM~J`p2bMGu0g14ItAq_)oaRR<@ZrEw`R+nm3ja*o~L=dh*!`(f}jw}z#Y1`s2G9q'
    '0rwI2&@@gWAKErsK+&#zOy~MjG$*#Uv_5KdtoK#`{~uBp+*%*3j`#)44_kq=iGSJPNS|wAE9${8Z#0m=?rkeemq{p}ptnC*-Kh0$'
    '6Xi3c2vg@g1^LLiZD8)qBbXqd7eZ_J2yD{)I*CBQma`%JNyiq}GPjL723Qs7q68F65=?#3Rq%k#0d=qW7Ci7bXoDBotm!_S`^U@a'
    ')Dm<dYch!nwt#OG8m!E88cqGbrNf*A#_HmDflnjUF*s+YOHjlS5Ds%@sPmd0L4vy?yKO2iq?|WKF4<I~dxHm10iM+_OO-y)xW?4s'
    '8gqebD0jE4F9rjpQh=fhbX@r0LLQeiI+UgClQx(T;c~QS>>yK`_>ndUNuRD6aM-eBD8c|I3!>j0SP>|8tACy*QCWe6P~$L$l7J^q'
    '@Z|~KJi(tQc@(wrk34*Gff4_!2md-I$-d1!JpkHDs9-$7=mUx{E7BlAMyV>fg^V$e4TBQRn1TSM-ypyq5vvz+A;?sM%}m%P&(M6p'
    '?AU&SCV2LrpaI}tNC*Ey<)8iD6V`Zt@@yN~iYnk3!)okTDuAS$NZbGV1c@s&LLujINDT(b)r4!eL5x716fasRWhLGp<7gUMp&{S%'
    '43z}vyL6dBzAzfyiH=7R$48(Uglrrzx$mtjctfK$&Eg4-*uUhX+h}Gb5m?yy!lhcmDgbPq$j+_kVIHty4<BK5(3T?`Z2LS4ve9iL'
    'v;X5J-??dvg~H7c48<ImDecdHz(1#&G$Lb|aXGB!YVZ8aZ$KN4ZifB;xJd>(Xmc{T@idsAv@+3aro6R=D3E}^|F$mosnSn4J;Do^'
    'ibI^YA^+Fo<D0x$t^&=a-AxMV<Y69-P+><8!DunXRaa!eywsXTt7vKgS&KW$5^7U4c%dt8titFHlq;CSsAl%Y9k4Q~Lm*GyM%yQA'
    'Y@Dc0V0s9#yL1|#KwZzku#1QBG+sP{Y6^iP5a?N)gP}69rEnavUW0`iD*Jc=f<Y4yizcMBplVBynKmw%U=oG_6XCQ4>;=~O$!{!m'
    'f*K_PJ17n#3nzeC1gftk`g;nL+c-hwkOvZ?+KHgmu(HcM3YiF6qol73y*dtN@l;xChB<HA=kiH2*KXs5kQJ@JNnU^f==4Ur`Llza'
    '-{eA?nJuKqkcG0fg=EX}@q&z?Yz)(M0eUK!i`IlMahmK~vh<>yxm-wMN&U{C4cX#3EF$@@y?tZbj#IWu=U`&`V4S4WC0LoIDFI26'
    '#t;k9-MO|nt)+xZ*ha1S_zAw8r;AT$`*20)8t>SH?O;BKAt~QuH^#{b`>>`j;LCIwMn!*AdtkrXG?456^=A3rIuvYKq78DW^9;=_'
    'wsr1rBUmD!Rf8TPi@X=0Nn)@E?-Q8eGY}zA>*%4ONhc!X)CXdXna1KGy#qR)HS6!yi&C|9Da(IGQ)Uqu8ws!i1`Mo8w{g({tU!~f'
    '$HuJxh89<nGgIF;v;pjp#57QJe%==f;15kT{GllZM@p7xqV>~6U3rC&iZWkKP1G1ZqxNs0UDn2)gr!zatMA;AW-QMaJ`5MKWgGnL'
    'k_Z@9Epo^owebbZs$lBMm2E>)mSF$bj@zhuMCfhB)nPlD4$a*}HAhlze`pD85xXf$R|>RZFp2-B!E6`?)@+|7potZub?W-&lj8R('
    'eS0_?#*<~b%*B)^bgY=qXzoINE4UTCU8-PV@B4dmm`kBT9{j%x5_Z$>I6tGgQ&+u8M$c}dWNWUVKGhc!!otBZ>s**9$?HuIoL1yQ'
    '49c;%_+s+40+{b73D(<QYdfJ4482&`U-ZUe?wMm_onV()*Sl*4^f?bLBzWmkdQlkGY`wp2cVyjZk>kll&YmuZ>`_3Q`|`IlSlxH5'
    '?h^m$z@Mkpv-QJ_|8zR^{)e}nj`%AQyrTpT8|qkaE%D<cN_=<(4bZT=c9pA+Ty%75+m!9eqBYSF3~)iw!6v1GURD<7x|S`dLN7?q'
    'JnIC|4?-=#k{DNKwDREngZAQK!4-zZ1J%#Ar3Jo~M_~A;L4No5WxU|0<t&^myzX0iy3hPoG)h2}a`}wb<21@aRYY6M1Yh!$MqbIS'
    'Xmp!emtTAS_38O9XXtOfKCwPnPr%pnRyi?nQs3)ct=ETX_$b)U19TcSuqhq*yUL=mW5o?xsfHt3vOSGT?xMl7{*HV`<|}p_J#S5c'
    'xvy6zpK$5Rr0Lb^@v;Bq&}(rqJKg9V*YV@YFQ@1J@sWRg*gLd7$SU4v=!fM8K~9k1Y$xZ()lBNk#V5aR8^FK%a$cmCt!B!vXeKEa'
    'efgt}9^r?E(RQ}8uRdquJ1xOL?UxBEsoou@dA<t<3TTsjcXS)igK3)n9<;;;(=HH-S8)hy1s{7e-@UnR`d=>3E)I|V-mj<EHzbKJ'
    'il|G}4S5IQY~stNeUqRt-Xy#zq(3)_Er!EAR09UV%+J#Myn)MH>E#)bOVP8)+s%|AiMfy<UmmW-AYVJ5!^#NXl)cvYu1)fT3!>Xb'
    '!{*LD<bH!0(&&8k+`BqF=Qm}at75K~EhFO#4#YUoUe=b6vQd<-$&h$@Maf08NFOGBF;g$H$Eu@4IMJaY$*J9VVCVG%HYBr(4cX8{'
    'hotji6wMdfoK+=Usk^qo;zAwkgJ->|=9JD)SVEYNb)7dsV!zf9sm`e9xYdC~l#J2lOvx!D<x1M|q7Yq@@w1RtQZX<MXYnX+;CrwD'
    'Qx_Jcf-B(xhNjJk?~K+*D7M%PX{#Hxenj6_hBFTQy^WjrYM{F^n1=Iy5A9`iO!EuK0sm`FQ|AL@`BUj*t4m*j5&HT{H*lCnxo}O8'
    'DNOspFx0^eA<tmp)E2F_;<}-wud2rhxC;3^pjAom&{*Y83%46qqA~MnI%lbC3?Y9jfPb7__}#(ZodK%iH$*jX(dA(M4r>{v?TSiv'
    '_Xk2KMbA8u0m81uedq{&BroFrZ48f~_2p;5i+st61f!<$$0>q^kNa(qXoYR>s<*fC<W{_fR(C~mthqmf*Z2dgQld%U!QdK!-R7rb'
    'zdP^#^n*yg+ik<cPPfx>Z9xZ<`Wm&}#%+v!U!p4e$EViS@->*d7V++Epnwg5>zyF{TR^;(DPa@Mf_VcHx!i|N9Sxilmxr7@11qmA'
    'ALTqS)P4TqqfUfA>dfEHM@HMAIzSm;wWxud_g<&n>Ac;cr((kmI`G*ruE=AG5f;-0%_wD?3jK6qcD9@NscGYkth{uXXVVD!%q}<b'
    '$bm_LtC3ld-GOc1$m7`(reS{dXx-u@9Sp&0i*S}EnnHcx*7)5%YhbZ`c;~LF{**>PX#L)4{p1gtj##%e`mH9sX-6mU4pwGVN3=Sj'
    '9kh9}W@^=Un(*zWTArt-;zTzxRiyBCmW^m**2SK~GKAvll4kl*>Mi;rv{pCz5k9`WVJg}?LQ7uXz$5Dh_W|qmE-Ksi9vFH%jV`L&'
    'pR}3nKFzQSv@wb#aINi$6>YYUimoU^bX<Em$F20nJkK&xF5TPT{q79@35OohgIuoqIwqZ(j2``8e;1!S1KoK-5je!V4c07qiNFfL'
    'pQu+>{5uB4whVBW0qKg;<l`Kcg!Vw#kQ;4pP4?7&&3<)KTf2SZuHCe8>KD+suV`*3)fZ=)_-@(27lK`GutAO8tV^DdFVq_ENc?{K'
    '1|eI(6qv`L5{2N~YdQ^vydUAF8FmLOrd79%shQLx*A8{lqyGjLvSM4Z`nJ}-5!vTaa7WZ+PW6I{7Q!P+rYB`v1j%FLPO3O52x|LO'
    'R>^sd;#2jXMM1vIcmu&Uj3!Zl(978};bktny>?s}oGEBz=?$x_ekn`^7SvE$l+9sHgPU5sp@mLluxtHs5Kk4q*cC`}msZNTz03Xy'
    'wPDAJ+OxYb&Km5@%sn*T-RL3CVb-~$C$7RM7~P_Y9q!sZi%^iATG}#meVb$W>;XsEVV*V-GnOCe6j`IN9#HjR-r$7Vrk>#wgXHZ='
    'v}o8`&27i?v_~qgp%UT_4oD58v8CwRGK{6Bp-N6$+ENBuE>|YhS^@VNXDQ5I7<y>I6rGdP$IfAC7efKX_y9SK$FTg!u|q8^4rBrn'
    'C(OeVqzJg2MoNRK^&2`OcpIqf;Baj@`Q-TAp8SqNzr<FYz^_r9jbKsP<}FT5!!^QPB<i%6322bJhS(l6JD7V_?x>SYY7MM6w#&`y'
    '+1!Y>YA24tV#^i>A}-bAS=64TQ0X*@N5VmFtiVRX^#kJLanUU2G&Vf^rw|5oyJPg2*dV5?_)dC|iEA1yf`}YLj@}lfhH~^+Gumt}'
    'W<s#SD2Hrhrwztl(y;Gs#|m;-y-cc`14R&J8?rU}a){b3n4HkpSmgke`+ewzYu(Apf42zJ<-&tvflwG_nWq(Y-8;Vc(tDAHh$->p'
    'h^>!PDcS%Eqa6>u5sHx-p%Mg95T0k-7`PaHha+l~!ZPYRBk-kOmx`u>$t7M0$E;4nR15k>edFhN=AfIGSK)uq&#SA8tNlNI3$g_D'
    'GwmvYni<{E9PkGV?{|NoTjBcj<h<t}e!RHqogCXPRML4Zs{za^k2&Z842>x?zeNpmVC7L{sdg*mih1(MG2``xFN8L%3>OaMGCVjn'
    ')pi7}Kb8p^A7qUF!8&G?PLlX{9H5w8Gw^t*(=3gKd7Alx2z0zxvwLH(>p1=WH=Qamp~ol=L|<%>xR(@}E<uhMu!R~Z+6i~=XLB@^'
    'U|ywgEKsncV*7ADO&5z`2wF5+MG5aC;t1YFp#`~tj=)t1_Re_RE`)~znkTTDHitUC;Sml@*XY{&1&{mR_pRSqYrI@Nr`qg1J5hv@'
    'nw~1Lmuf=Acr;%zqw960&no2$MekITmQ>%`gvDStk_eBNrgnO)I!+$uX#MPOtgVb^t0bb)!f8&Rgoq<Os*34==UlP15?HVv$5z3B'
    'REsQroyimWg8~3u7VU2+6cvpz4Z_E1FbApABKOdk!YIh{l-8oT&VAz)5k#e$f2Vi!zOGq)+!*z==B_Y_i9iCT#DL7PNdbd_|6`}K'
    'KVa{gNH1+Lv7^Jq=z-c~fw^3$>FA?ZhAROkdsy0oW@+%p+|{;h)l#9f?&Orb^i(aQ+h@XAMzkMkF%~Rv`o_ieK8G_A3CFbyhk{=;'
    'E5!$kr|QDXjvk`XlCrSk_d)AnPr?rnNTYz3LF)PCg+11C0>Uw8vrR4{T^X)d8nRhdY8=&O+&Urv(esGrpzJx$YP`()l0D1H3-&@c'
    '_wBkBx<1_(TZPmSeddAsgI5vURGFi#v!NH3V3O}co<>b+ycGAmt|ktd^P-``d(8>-^^DGs_~A!;pPdCSSLjvLiI^|fLz1>yA3eXu'
    'd$6|etE>Ey7|^PTJAOll1`kRUH*_oaQr~pDzOGlH1ZraCtgSS0J@J2K3+uj$|Ng=BvgmK{Ml9#Taj|wxRJ|Lo92+Ii$l3zx94N0X'
    'LP<m6Nck!q*wso1N6X+_C>u_iTG}Nyj!FI5h#%md60;MUgwo9r;7UxM%WEHIlO<Z^m-qw=uqYpav5m8V=lfwg@_lhQW8MzJ&<{lN'
    'hOHe#wB3M$Y&@uY3X9JLtekE4Hk!^o`#M^%VKPpqA%>$Qp$vl+p`I8>il+%^p9$lVVfq?@Ig_MTF`L<Ixe&x!VVv3S;&C2%7{2C0'
    'tpk{{=%Ia^&Z361YquY$0DD)PCv(Z^x!_6$)jd+<>eXD!0~*#^;cL^OuC(3JZ3-4<?vciPp>^x3gy#%*?V59)>lqZMJ7rZbR$v=p'
    'j4lQxtNMj#GZK&TH0VC9EL<y}rFW4_2R(iIy}l&s3)Tr6q~el1Q==642qqD&FfejO^d+uIq3K`M`yy&xHI7_;uFpbVu9kGr)bO}A'
    'CyYl~HR=^~_;7uWqv3Kwp09mzY!|)2(|8nPSU4}qa_jW`=;HI`*-7t2mXS@+xei6qV8p`mMsdmrp4zH+OqVr&B9{;DkKhA#TWRZm'
    '-X;sUv8~ClbhFV}-PsVvT*&J?7GjGe9%*eCGo;GgK*@8dIMGu+43;*Z7g(bD(BeHS0iPYCUL<Dnj0lw4D5@milB!4-oSsUf#@GB0'
    'MHRJ;G<8T>REf__V|fP{X0DHD8sVsg@X+CMF6ul|zOkGZ7O<WW=ODEnaaAq&ml!c(-@9^t(x^M`fpAQ(9tekgmOj6?y8A^XbqQ3b'
    '#^hl-+bp7JE-i3+3Vk1i?8cBMrBpSv4kK5lezx?<Ce5{9)Y+CAWq;JSefcne_gsjtnFZpNgBuOf=CSw1TiPq129?*X?%>&#r&-qt'
    'lkja)q^B<r4wTNwD7h+&rkRVM!U&@}qGS|9<7f#uM}qD?J{I1-zl}$?Ok8N3Vz+c6MYy~<QjHJS{Cc<uBZm!2#2AxcplY=Q<^q=G'
    '6sDa_Dr4?@>k}w95Dt)TR`DFZfx^B_f)#wEa*P03;botPceHr+@T_qAZz-4!^G!=?9znE4RBkQfknL*^+m)6NGJ02?ldY^1*q>KE'
    'm&CEjb`!o}sNy_o2uhBMPnI=x>&_UgcWz!D|5<Tmbd)Ths^wsDR6T;fww~+)z*(?3=3>5~6X@ETZ*3G&*uSJD3N}<7G!c7MyVL^@'
    '?Bjty7>_G7mB2<v0TNGQOGBNY;PXj1#9fJ8fk#IOP@~uz)CL%8S`oq&icv6pL~W1a$~!hZ8gB78vH+WC=eNP$+josZxGBm3dyM&M'
    'N92ibIBo?20)`J20N*sNI&yO`6nyj}^JY^)p}J1c@~PQreSS?f6lLqjqHbka0s#=HDwRiaU5>dyROHpR!yx5t^bp1q=ws1Z7`;Oi'
    '!sfXrkERsV?y2<seRD<}yfBB74^QRZ;z*C2?Pok#EBsi#vhnSKv&Mcoz>Kfl0miLl57Y0eDjncEk-aVl8Ht>yp)xgXJz$m{)?3AH'
    '8}C@NV7I3!tT`&1ZlgQx&`&v<lQ2};V@%b+e_VcXc5(D)|Ku-!Xiw)Kiy2qAj6Y%y=;qUlns83m4p*@1j%QLo^l;TD&AebrOKuvK'
    'Xx@thkvVSYN(X4sDP>b+Y(J?sdfvC5(5g_q>^w`$h7U>|@OLRp@LB$BTUXTVK!Mx;*>=a%Wqzx5OyOY8z5c-50}=ZOvdP`yay*WJ'
    '!HL(U=7%MW*(~rv?1kuEjN$QL_Y@XKHL-npb@A!+>;$x@VO=%tO_`1^zMfni{(`wSDVfbgu1>DMd_M6%ou2=4a&>uidfvmsiN)yN'
    'oEs0i9Q}HD^$W~$u+ll~oiYdw%zVcuXa4y`&;N1`zfV7%o*et1F20-}U;Wj;{_^qY^y=u#X>S8<nr{%+rgwVXJ3Tr)W181K9j-b3'
    '3(z~i04eTW9Uk@I;q36Q7hig|G2?h%bsiROf2MGBadm!jb&ZrhpI(1H>>d58C$25wg$BJo{Vb#S<>Jpjy{4u(^e<1YK3!aWMmQb+'
    '^6>h)LWsn!3X|0C-QsY%Ow;KJO=~dTP$Ax@7*?2jYakd%Nav8LI=z2yU0~S89omV(0+9?BgtM@-XQ4$*yTn{JLPbTOD_1;>7hn=D'
    '=VIZN&%uy{#Ylp?U)8AX1s)(uGY@|h<MTk4;5|K8^3a*M<!}}+{Dk%l>%+NG)zRqpD3vV9sZA^t+VvuxpHf0RgDch*W|+L8JUwi='
    'HZ#+Z5lS3aLHeIUl-LyT#KJ_*)SjBM`$`yJ<s~MmEmmD37G$(G{6s7iykz3)!8}aD2=A#aTy#W#JfP^31JNjzQw!2u@X7OtZsf)q'
    'k=xmG_RS8g`txsrAz5^N_l7XHyS`U55bgu$43XDmc75FIu1ovr^y<2&M&WUN6VQ2ctX5cy`cP`A_B@?8#?C?JjoV^VA0Bx6kVgd8'
    'NMTuf<3TAyb7v*Z?UoUpY7~#bqMSPQ4ZP>w^5poG^|!^Y!}fq5c@Gkv@cf(A5HU=SE%y!hSs`!OPVFpO-8)z(1;SVDRd-Jd3$ZRk'
    'zvOKgc&1^nRwsY?{Q2<euV!-#ny;8H6@~;isaGnsDl}TrDvrEt5L|sZukFovT-0{+M(v<pT5Bu>|JTE7|I;B@7{_!#kEf$gU(U|{'
    '>VG{vJ3T&x;Ze(txgWKrn8UL(|MKkc{2a&^)8BP5^1wzo0V7kN{XU=cu1=4t6JULTT49Ax6&8>mzx=}MM^zzT*4d!UL&Mf=ZC}`1'
    '=vQGguPW5i_4JYeD97b%JC4WE-WL4#z11rY+Da_OFvh&F#zhCb2&*DY#v{wC0Rr4Q`$fF3fB}l_AmyJVkAApBZw!nhTBys_HMjcq'
    '_V!iuH~7NlI^#x$V5;XL2RsloB;h~i(&>cTEa7rW@FDDdY9lBlLlMlSVI9IWeCu^8$MeK`y8eJ3;S%6NvN(BG4iMrb=vC%ljGv*-'
    ')7d+AX^_^P!Yi^03>L5+1zL+;!dk*=G`()IVw$eYA7Q*qO>Pgj`Z_NCZgm}#5~uJ=A%f73a)#+Y$TEu4Z(O_yh=w8Ec$@$@SxqNC'
    'Zc5mcgO9PKb3K}ygk79cgO>B2Y>~x}5Oq!b9`o;E9OUvn{T|!TbtN0!@L=;$A^Pn&hsH(NI{g2F4sSVYnX5RX3Soz}(?_AvjxIn4'
    'p{>48(tG@+XGx4c1!;ydY}xBgv7*+lr7BH7xz1DrRcqkW#75mnxrCc)_4FaO024oI&7tle#ZKQ*DpUgPr*5LmE&?!NMEpLO>o|Z@'
    'Xf)76dD}WqS(mV5_#T!8)G@F`R)A{jp{6!!k1__8qdV#qxX*etD`O8^&sA1kC1}cZz?B8EpjW{a)G-aHCB)wTk%{uAzCmr*eTwFU'
    'ico^)vxcaI2yU<=Pcp5+4Sew&rbNFBVOU3&#zPsLP{9K3y(Nr4Rq)<hqh#^;ilTev!g%z^Q=k(43d%b&+2}9;A@3Vg)BgIqL?sk2'
    ';U9X($bj@xob$s2g&-0^7*UqJS78H^RI4*os%cnuq~B4C$<tBwj*0>pdyV3vO<+OO7S)s_0{VIXB8<WHkb>WUCdhjxo54&qn7MDq'
    '3fy}ukpinL+3FBE!p7M!;^+|9+CjJWE04RHwKT0tz1N`(zV}w|y;tH3R!b6#CvOAFAancmX@w|(6&OGzo@+rqc=2BnS#dP0(K~X_'
    'eyPmdF9L@Mni4g{tH%t<z5fEdkSFr%{v(hfo~Mu6yy?9HCWN4Eo;C~P^V$R~j_bd(Kt8_$JEXS}J4Etb1`ny^s)qyF)D)|RvT5`O'
    '`GxHo{XsP!{P}wJi~srX^j!Y_czSs4Y^8ImFqmI85GwGtrX}zT5<(~oI*&rR3eH+OXOtR?s-za&wsdZ{_~4u3rr@AlVwq;qtb%dO'
    'FU!M8RM8Y?%(p-g&1BXD=Dp(FIrIqi9oeQAv_=Cl_b)F_&wKvGm)`a1F+#n3I=MQ*b#M=z=RI;j!!H6IIXbxn6Sm;&A0o&rZm8%X'
    '$dEvj2TC-IVQ?ualG6v6iDCxBMFLD+(6Z&3gXgDEoX8V13?8;)zgwL{0<)xGAZMHhdjsK9pcB@)FG!GsDI!^+xIIzsXDb-Zf{E9;'
    'N%+%g-KVOBtPy+K26Ed3at&4Ryluh%Hmmz>ptueC8`_}_vjMKHB<1c}%C;Sha37lCh1Qrd&&AimBr;wKljvDj76v0QtpLvjU-cRU'
    'jPPlLh6QGRhCu>j7AjDFS57ysNjH}1c+eZ%$mF%33dQxh8b~>mD}d(M*3pr~Orhf;ZG;ON;-;m66NFRU)AIqN-*~ub{7<3-3Gg4g'
    '7I=r;6#aMm3Uu)R%J1{Hfxf>;3;hadto0hgigT5F9iR^a8+iXDcF!iL9w6_0@cvPh9?bo(hv?B-S-Ih%AYHT|i4YQf8aIIk1ZUIK'
    'y^UR*+p8A-zkChJU6FWVmBuJ6yZF^<cDKxS&z<kQgw}V-BSD`ac15c(O`Gu!<)F3QJ4T0eN$Eyluo3Vs=YIhLU!53W_|`Pb$Q7uq'
    '2Pat^DzqQ3g!O|(3=U>dkf3iLp>uW<b+-V#eeZQPLy9Eot^iC9T{n(kYEjX>tG%}#AvY9DTGdzs;DjBHBd<|H7;<)zoP@X`bA;qR'
    '%g7O@gUA$MI|hQxR{2o8Aw*!a9C;u$#!FaD9C;u|M%PoPd-zA77I{gr!jKR`dvA}>+`$ExLMZYiKv98D<VkoUeg!qeckrj6sFw|d'
    '6}cmB##Juh;$%A^9)??+iE2~I#Km(aRU{a!!}P(Q&u26Z9(jwA3-1y<n>fWYxc(v)5I$O>YL8Jr=v`J6AwY=;lh&sYMG2kc!IK+|'
    'z#<7ok967!-yks1TV#S>EJp9WZpWm?@I+n}orngFi=W?hmWNDWO{(|ayUv=HHyCP2j@Y+H+^97nnFJF&y&>!qS6ElYVvyj{_#>zT'
    'I-n<#NL&Z;^)*l(Xwt<wsB6LjkCVTNpgz)33f7B2&tUpGP@5AfSf+%?RnN7?c>p~BN!|`Kln*!p5#_6ecwg+G+M$t&qSbxHWhs(x'
    'vWH}iw22~Gx#N`^uRPXpNVz+31L#G^EndCBS3el9-r}ow+WE04cE_<B$BGidmAONM(hw;P4N60#G&CrM5y<OmXB@YpcxSvS)^fOZ'
    '_Gk*deVnHY(ofOKaq;hX<v2U#Z?X6mJ4O^gcNIoj;8!RP^dK}U(RZPZ-*h^T)}?ah)N>kpE&7M|kiSb9bXX1VMLdJk>9nQtqr3Y)'
    'ZHWuG;5ArFOYXoxq8$+EThq3{G%lEUj3TemimA~W-Buhs&~VN!u%IOwdkyg|S~VdpG>@5L3`Cel99Q#?AwRs2R;`-60zL@%XhK2<'
    'TVe0Tx}Qfu*7`ll(xTS17l7j&{k!CbTBMm)QT*gVF=Hqua&}dL<*hH%(865kjGro1Q1cy)_ZLT0VS15=6*Fqwu|kmY!lM+EIL185'
    'sa(2LNC}yt=%n=}QtI-hj4^cXdi@7PL@Yr)4h|;xp<Df+-`j)vA@go^5hgIl-bn>SDO+7VsaTrHl&>_N);OhU%n!Z(UWW(pG@W!i'
    '4QYV<?#Lm@*7EOIp9xoGev6?_n#Sdi+EEWy7hyEXBJ^9+6XgQBCJ+g}G<#nJ<h1A$Ho%AOkDdK_%X{;#vpM1W7Nu+&Dd}qk_x?(p'
    'k_tw*)+kG9_Gw#}pD|bzchJIEY}APzH4GcEkbDzp-!V~Zh-M$2a%7sQF05%VnK0TOEm<hK>p&foX^o>O90sF1>+F*?%%FtZh%diD'
    'Fy;wjY2YLtt>WmOBiNQ8^^Z8$O=fzF$3^H9&Rp2LPD`Je!j2nuy>Qr%_v7Z?;9%Zy=UtDRieKs7&<Hypyv~QPOCuGY-gn-6VR@#z'
    '_gZ0Rw-I*Xk8?2QPL3Yt4Jkh?voR>j`<>FeCJ3_p>Kx3yc?Z%o=H1r3W3Hdjc{W0HU#~H5LW4X116mwge#;CPJW7)lqlg4k>^N>s'
    'XiMxA=!hhm1ZI<WS}c&*_BbZY5W)G(!|t6MFRAsV@Q|Tx0OXBH&4_SrI>#5L_X&CXLu^gqyI;=jm!j>K$$f^!gg$kV51e{nlhf~6'
    'kWH`@d^K}b`{*g<yVBt5eh2Mr_8~1My`0c!8V!;P$LxT+4tMM*il+@+%wZ?&LMJ!}cU}Gjt9j5d4a9?$-zu)TyFx<mI__P!*>&n}'
    'G0G+|U(12DbGL344}84$IQ4tPudVe6u#7f184A{}5U_tnRx2e;W}5_}=oDsyB}8`NN3R8g3niZikt671WF2c&9-#uoXQatE8BHpk'
    '^Zo}m*h4f?Kk&tJs0m179XwNxZ|DgjEp1a!3E+cdmA6>}oGL<E)D=o);y606LA;L~beof+S=b0uENcFLfkSq5asKt>9OJJJ&(sFX'
    ')x|ab#Q2EgQ}K=6&31w7K)3QB_f?|j7yg%X4C_{uPS5@8-%d_0(Q$qG>*4iDiJq}FA*g)*a@IS&)cCpfFRp;V`E~E`{P^(dSWvn;'
    '`FeWt8~piSUrw)1j%}gruc^sE&(K9jqlE=aj1@&*r1DrZtOzL@0J>q0$2ctvqd#D@Bub4CbqSuLWGEqd1rZ{d;{k0kNHHL#-*LG|'
    'T3uIk)}Tp;S-898XBVgMuDikiySuyRD6wNwuz0GGWR`!S;6Bn!GSH-3%p?OB?K=-;f-F53%{hJ~!>*XDM6CuD*M;a1{^O#A7mR47'
    'gH30CD|k_(qR_G=I=-CQbB~?{`^DSI%r)%<UDp<4r~FCWDWOk5r0CHpsx9ONLP|*i;23K>hykfy+nUulnK|k_Ig)f<Q(CEQguUU*'
    '$&b0Xje;;s(-|ouYEx;Jn#u+BF)SuF)k;Vqp)q&;`E;54XP#6LQbZlMU@2ITt4B|-<V>co7NhxTls5pnU=d}wNJ$7RuQ1Y!^D?*T'
    'H1d;ZfkzV1#^!s-{85D9kFi8VbZHp+au|rea!pVHW`4~+xUv1cj)J*|eD(|JYWthE)a=(lKcAuHpOWJTZBkMP=y}d-z!!!Qnor8b'
    'DW+zt!SK~zt>$j4(|-FuoC6H#!rNc0<D*>xtRmwsgAw6+K~XH&+HIjPLs)+Ua<yE&1dG7a_gE@>^P)HET<n;cF-d#!GJ`%kNJL1&'
    '-22bMyVkt->tK^<+c_KwXW~k1fa-5d@M;B=o6a{hqusnKuGSUHyma2Llr~`Z4SuQ=>y&|sYYygeNZ~C`Od$w~^#92v5sX7yHZn%@'
    '3xO-#k^%|XlS~w?G^m4CSEO*t!zlcxqMg+~@|vw)D2mtlUg7Cff&rO9PQPB9^$veIVd*G+JNj}3W3orz3PVxjrH{LgA~<&7m7NS+'
    'bRlwmJ0HPlg(}#+`?MN*jlq+ACW|+*)yjtB8b{MKk3vGO8BT-b4o0uid>RIy+<=<PJHIx8#=S<%ts%gby7T@ausH^tRXB5=0W(*F'
    'GDiv0JICD^>+V&+<RD9N{P>mNR#|4$DZP6E&`O?&ui3|}jU!ShW9-`B2pU)3-Y7$h<pL|qQ`o_|C$X|1udx-txK&;iwrcI>!Hf7('
    '5?Ts3JJjY%6)CP-3zzZ9-~%12E5nnmFKNw2Ocl#&{jN=^R(d#m*;l2Sw~E2X8esqF`MI(*eob^sW%*|eqfCgLRv%5{tT9=OgX)87'
    '0Exnq)9EPKXT^pjSxA!p)p6N%<x9wQ-;lUgC4KFIqxvOf&FF|tYMaK%ORZCXZmhmlBocwNQ8hj7Uw)>wLsi6IV!$l``6|+0u^0FA'
    'zWt(!3z|r~jH<ZSZR>mMVlJi?0w0n_AZgS#%?W>BrnvMZ|8+4F;5I+qp^6(K{Eg)q-`O|GO?LCp>HORO*}l1XdbT(2?SDa_1PRJU'
    'TofQ&_Z0WyT46e!28hEoN#F@5x<w48p3B^cSNSx^(T56b3<-hQ1opSLdHaUBZNj4pb`_vf%!8{TN(si%Nlai2WSz^<e#A4*9<2y^'
    'Tw1*t8cIivl1EzN3&$-9iLo)sXaoskRqEby=3%$Nrg1yRy~2asn^$hrrkc^|3J*_N_yUEkJ%21>!bY>uv!P9<(7lh)rpX(y{6vR}'
    'f|vwuX9<uhl|XBTf*l4l<K$EaHsY(ZSnZ*&5)L~|8_=|LXiF?|CEOcoD0wneAv93<t|_8gBdgsXPX!6zBu13*O~PSphv&z?99~Kv'
    '6f8c@Pp<s0KdJS|O=35p<?sh(5Gk%sdS9;2)tSMolgo>%9z`)yyydkD{3_a?QBXpU_$s2UZ*D---@t$R#p~PjZrix5LtPZ=*+<qB'
    '(rV|AvuEq=n~wFv9$q`yv7Ru-nGpO4_03<TbGr1~Lj*aCfR`8E_P-Mg+oFYFBnZ}E7-+Y}=WgN^myaG<H>%7Vv(THO)b`HLH_7(R'
    'v+b(;R5ixk+*Nl=UYmP_-+A5r7p@bfTG6U*Un0#rI`H_%7~>RD9oCU<jVC7@j7L`-`J&4#rZH#*7_TsT0}T@Z(|Jf*jyzjG<>ceK'
    'nU*ow3ib=~Eu8#10m|k$2VziRY0ifB#;ZD?o(DTRiN??S1sl%Kc=v0gd*e7i--w?1q0_PUelU9Gp=<OAiVp}i5Nq0IdYK$j=il5v'
    'NKhSQtLq}6`P6>w+|4y38=i1*i$wc#{f-C0j5r^AR5&LHofG?jyc7{p;DWgW9V4S+_b-IEsQ^C}!i(fuSNaBpi#gqUogj`lOq0Ej'
    '4-ceu=x706=`x8D3S$$SgG9!~heYB=Ms3?5scXC(<+p&dJg`!QhzWI+h$~df8k|iA30O|2d|Hl_>AM#E^OHQWTX>$$x!pQ>5crmm'
    'y4xa_W`sYu2p)61`fCM>_4AQyonM?@pSTu5W4YGx={2aqkCud4e!D-|!sBzRI9=v!<GEJxf)CD#dw6rVe5<scm36kB8K*phn8F<|'
    'A0}~i51m`AV>S9}*7nLL_ariH6?cy@<kb1&U%|eB9;Rys8LUfPl^(!q9H-ep?ir(aO&`nPUeuSYd+>-Qp|$3gy5gY>4JKL-H-!=V'
    '3te-M0ztPencC7oAQ;q&xu$C^5)Zcw;5V*#h54}t<zmjzR63l5v*!MJS{Nhs{pxvTe2s9Wpa!Va(sp|}!g(X4-<r^8TH~SKq)@6x'
    'w#}e&pch4J{{esh0Cn&1UF?1PW_!@+{|EkQI`s4hJl^E+<ZRQu8?JfBw;sl_Uw=C&ooe>z>UfM)>+cOpo6-n!XI-Bh;jR{TG}y0<'
    '^2>MYB`FC58@zl>-{NZwm~^`Wg01Rnfau*^HyJyxsKy$OL5GDT_T14_N^O-@!gidib#Vj9DhdP>3)B0qdR0M9*NI?Fk$@B~8O|ls'
    'l#v$DN!+&8;c;wXd$)LAhY45%YI&}YRyDRCOMr=Vx47h`bnurp-awFx@Sp;P6+2Jf{3SFsZ_|iNRq@^k9#x3Nybj(CRyQM0yJ)L)'
    'c|@_n3hBhvSp-h)!%UGACNUlwee=>9tFjeYH=i_2($*VCO<i0)X`o|xon*(DsciS@*`fE;E|92ii@C1A4^vf=<b+d^QY%V>{kp0o'
    'cS(Am6u{7S(?Gl(v8O^W7vX;ntdRm5H29YDZJBX+C}q+)>x-WQ4R()un$m%|%$JMx*nZ}1mg%BA(1;v~ff#1^f@>%Fso)2a4NJt7'
    'WbMj^as5*FIr=)D+CG<NTw{gzUpYmLIn_v_S=xg(N3wxf*7eR2r?U#&VhIn7$4>C_B2_fbOeNYR$oQTC$?FP`i4|-DZkHFZ?d+jO'
    ')687_kK9sGFCF5q*bVXozX>Kgk~@aDRRa$Z-bRBvVRWo|9^pXqM~|avB(4H*?Iev6aiF>%Z|vhBtapQvW*zCTqb<8k;LpDA)-(@%'
    'fTg)?@<0Wf5e&pc?UwNoWRu@Pb7a(K@WI>b{_v+Ceth%phd<Tz#OEWN>_a-E6NNcBXW;S8UTYXHINZlPgU|F)73X}+o{(uGLhC9%'
    'I0zN+WKX8)keu!+WZJbQPPqNNzv1A$BIW3D>D6*%h`RBzj_~mk@zc?Ctdb^df%kM`8+)|~;nd%WSj|mLQ&KH5Q*S;kkX;c)-JLVl'
    '%B55_%y_~3p*UFnB1`AQ3JHvGvd|T^a<5pA88ya&yjg>Y=knfAylMj^ie9LT7wOOjoj76m0fOIu^rtbxav87EAp-nG^b!Lxm)Q`N'
    'lz$6ry~@idoJ1nK+)3oEYyYeHGMz>l<rrs-x(}am$CVja9@ey~rXYFzxd=4p(zdX(Ca75s-(t*qolQbuHzAQeLQ73Lpe`&m>!3;T'
    'zcpm9#g4qvlxPxK!59ynVrD}b)U-IsaHVr<W#)o1v9#RBNtoVS`7N4G8JHb(T#BiH2^NHCsn!XQ-j&E-PJKDdV7ABG#X_-k&HcPq'
    '>al_4@eLmB)cR_etG>WFZv|aZ-)SpHN3EbtukSN4{se3TNjN#<2<^gTZcQRhEv-o)tH7!UD)P4dwhm~coNrStYO|DUrFvp*m1<IG'
    '^{M+>^apjv>H}}()S`tL9aBrKu8JQ;I*Ze($#ED>K}y+$uUySss#$Z4@>ou%a`A;x9*3>}JrI8>;A6+eI6Ke>VB+L4P7=9~M#u}T'
    'UX!8R<_t9M=c5eP)jS4O!+(n$uO+nEoGYMyFt^3I(P_j4UV&%hd7riY?C-5>4X2$wvN2s1NlSi9hI3I0OWa;)2{f9v^*MgP!r3;^'
    'h=MW?)0s-2-^ODZ9x)#8=K5WP>0HDMv>0v%_!x;d?X5DNfGffx>%nde%faR7%aRS{l-w3*FnKkm7iXyK4x<&#p+>c(Yn$=8gr=z*'
    'H`VoW32Mg#`bW^6D%d|l@KgZ*36KX7gGR891e29t)&t`jkUd;80oo&4(W55krVs&mE;Shb<E}ZG{a=NxQ^D5>qi6s630Zsgdrw%O'
    '{mJuMWS!zg3vF6kEb7(0b)F|2t6FsOC`w>-q%tP=4(3(p0i3v9p8GwqOv~gLubDsxgDOF*=~+5WsY-1MtHmCXb1jsy5PHO2td+wW'
    'RqX1ojhWkd1w*u8$|XA;ogKPsZ!K+&I5LefNyv2#a#m?v!o+8`Grp;9k5W4eL$owGtuX*Zgzc&|q)XmO{%t;0`qQ8?`eQdAnFr-n'
    'gEfia%>x_DaAgiJAGuO|hvp6Q&9Uv{&Af}Jc)zm;()^T<`rFtFh`Z|)aq|Wind$OZcw{^s=nW(R68N@qxxQX`BfSX@Ko-Os$uYh}'
    'gTCD0!pMiO*!1hV<G=zt)>~uODh~vF$9huO84av`ZR<Al(6DY|B57(LNOwZN(Q!MD+rSj`1CqNd{@a9-;P=4o!^6N8Z$uoy2}Wm3'
    '<NOxpA`Fs;xec0>FQ?@_BgB!G;RK>)IOn1F4(8`6Pg2MbvsbeqIItET{>EaP*dXk{!)pY}Y-2Lwdx0DuNIP9_6>t<7wPKAcV^C>B'
    'F>YCxcDHK4xhbb6x4>09dRP#4Xk*dD&UJG-vv5yC!xb;78;Vf~3Pw+*AA*K{TQv7}YBL>Bd2%z7`^-_bmLK5%1-*qQI*?k@B!G=('
    'c$wg%D~P!g)1$QGB|vQ%tzFYZxmVsatEOCUSBZ6$D=zM7*!exp)4p`0@YoU)tv&e8EBq?Z#wvN?Y^i1tq?}T8nz@I4Go%F(-{^xO'
    '&>eW=l3U7SM?3C-ritU|kpVSZFSz?`y|DcZ!vnX<Li6$;F#ATg`})F+hu-JY&*;gxQ<va@0Sl&cJV9#!gOsyL)FLPs+AU~Xr|^9o'
    'Kj5A-n+zH;uy=w{%;!RH1GFx!XgtPH_%z{ggyW+Y#$%`>|GP3=Qon(|UA6*fvsJSJMAPD?&)4JQo4knu0=V87+wg25oSN0a$m%ER'
    'ux-+(h@O6UWOZ%5jm3RRLJ$2WuPT?9)T!Hv7^9W98q3?P2nCxiC#bv-UVnzxx*&+a8@#)+u-Xi4g_o_Y(m2FGWO+-01aqZrQUa00'
    'n;z+l*zBZrS-TvmMk8rXD;Vf&YP;OThsGPiz*bc4b(7#O8E%e&!DZR5epQpy;!}w_#Cwv+4wEr<9?69$VUrZ3_Ov|}ugZwd1GS-C'
    'xhP6)C7(Pj(Dh_}zPLs>dU4~silxYTmPMr>@TF1($h8q&LiEmY6>9}Kg5gu1MLI9=g`pe%a{Q%tAda5la8Y-g(lvw+T_*D-L9>N6'
    'yyPzT2o}r02Oq4kFpQe$Mga^!=nxEpz+G+_9t(;k5Y;s|r=flbbS3b%53D-GD>5!Ocd%4`uK~gqMJ)PVmG%JnP=HrYHeo&6`~8)H'
    'SWO1pqQA#ivxCl(J5wvX91!IJvJ9R}0Nb_L+Arc`=?wJ+aRm~!D8(A<DBI#&h<o}A1DU$qK(#2><TudxE%pJk$ktlH8R!mlD9r(-'
    'Onb3r4$(qTn-?{9G#f@?SQ27_!=`J@N?r!(4FQSspm?a)fi+A+yq;m$H<^GharhwaToKmu$~2yl42|WrbvHH)FnPbb4^#)jg@r};'
    'h1{&!Dd39Cg6XapwsX4d8f>02^vewT5+gRqR7ZRogSy*K46#i3*rehJ56+`1h3Uzo*F~2LJbN04M#L$F5K$pQ)G9vIO_Ea+R6x@t'
    'jIp;WlWe<%^Wm+$l4Hw^VNf>#Hh$hu{+K)CXyJGIZ{EHetoofd1DmhVEUj!3^s#t-(Pp$qtJ=rqW@y4nyQy9}!iKOrGA6HM7Y&K6'
    '_;xTTf#0*{($8~KXdE_*OFQ{mL3&Fu$K<@2y38s4>y*Irao82`_&i`VlzhaQFX^0zQZsyS{aI{%qxTKB_0XmP{Vs>qfmGPHF~~f$'
    '^CKv7+?$hE09!)Cx9j3Q3<lAfhjD>m(0k*~cx-E|*2@05F=OCJpjksOAci($%nK&aM#F|Qe4e5o>Nlonx)dome8VcC(wn=!B54Un'
    'e#D1`M|Twq+bu5KRc85%_PcR73J*qcq@3{QlqN4S@+g7XwQ9LpyPgw(Y_+RSV;v3eYPO9^X$Ga4g{ix~>wB9P?!}2(_~6->znwMg'
    'CRkQ{H|yAbTI{#GZzs>z(~5tH8y#2=b0JRCc5Kaz#v_5)!zjcseBvRg>gl7jxS0Z2G#8g*T4-BePLC|LlgLZwTq7AQECMvbnQolo'
    'MMWHv2mHE*l?n!opv?D}#9C1BKW=y1O>CZZhPMI}eE|)d58JqW1_b|6Fl;cA@me4nTcn`e6~%u@XOJjCfRzf!R!m3GrX^(Un?&HW'
    'mfk}bGSO!d0#C51>#5lP9B%mMBbS3rOCv`Ch?j#z>#@VRvHCXO-#j>Y0Ze@DDFFjaoF6qbarHuj6Te9+c;cer)&q*)RCCyyHcqZ0'
    'x|v<>-$syoQ8<QZ|3gF~r&-%NK{TVwuRU?ldztf!OQS~@UQz%DVTbUQ>mgktX<n=ct6&j6mj(A=yCP(Q^>w$`HX*)&AEG7(1pbEc'
    'aFY<HvTl%)k-&rLv{K)aS|p25_*0APcTKfPSE}0oK7%Pa#4Fzxw|F;Yn{KPD+m73+ASDwwPe|vvzY6nUF_2G_nfe)r1HA_6{3fXd'
    '8CS2XDC0NDdMNPvA!W2p*)ITGu*l_q&nTutKXyVD<A@T8w2n$k;6ZP%2|(Ir?B{JWc%=N60!Q#=mjoD=lnV}C>6SRKsVTnnF2D5r'
    '!|P)&6%=qakS%ATsrdUPd@qvj6hBKe4drK3n~3xJc9BOTYCA7VSnP)8GQp6xk^vSb?j&*Z#2qGHh&xHN^>^^ki6OZjf*}}>BFLxT'
    'fT=pS-4KgH@7!tvPm|&)q^D3k4e4pfPvMaAiKiT%h+C)TNGUXC=81j61{CeoLy2QIL3=#K&;Ap!`RqMm)@Lcv=0^<;+pbg-G?;*B'
    '$B_oTHknc6P2GvtO5u<hisk`H4}&rX__9*|Yb-MqYp=#|DoGA6B{tbedKfsNG~+I9UDVUS9ITkedctqghC&v^?~d_h8IO4E)ajTF'
    'qosFscrFJ^`5p!)Wjn7jRlj-EtRFeGsQmvOV_}1|Qy&um#gjf*o}D`IeMJX-ykw=8sm-I{&iZ`#m%38wM-*o%i}k+<mR_$?ak$s>'
    'h7#Ao?(7I@QNwBI;ksH`XCO^>Gf;*-=Qk3xFvU=%DCg5Y3r8>5RAB4qVEOYP&d8en2EY|Q7ojj$G&39lH@v4ixz?=(ccBuW%W=}{'
    'V{DM-=3trvxm4Q$u*<-ta<wW0Fkz<7Lq>roz`nwVe3njH(-g6Mpcbtu7-w_|@;v2mmR&uB6BauG%+ra4LbPCZlwRLyd>5gt&ZFPc'
    '7}n~-#Jk66PoN)wae6z8N4!by^6o|~k6B{<ySro4<GV-~!PM)tmGdd<y4jvYVy3zfU^iZ^R}997uKU>avMxGY;NLx%SReM>$2~9G'
    'qgQ*nb_Ic@SO92~hpt0VuD7xKuxIG7;d?KrMcR1m3Y@&hy$>Z+#5+$x06y;RK6VkASUf-M?Lt`x)??s3c6S;9KJAo%3aRQ%?=jd3'
    '3M|3lZs5qx|GQ?Fz<IkJo=%FCps#1$1|=}FI=l381Na1S)C7iGz%X#u0?u}U-xl*bG`<e?uXW5f9)srN(AnMFp-bU(0VTe`=3F!='
    'ZGn#^cG-<v3wT?boD^~xqZcDH;mK(i8B?|hxcR+@R|mYOZC83>c%gxS^Pa$+;THnEVp>Sr+S^$>)z*#0D;ba~qE%yskt+tIfTJAs'
    '>w<}Ki#?qRSjQbRO*OWdD=-amn2Upuq*nQ;OE)24^`xL6kb8@Za6SOp0trsu%ZW=s#A?JH25KN#geRM-C4k%bQcr9$nWjli*P@0m'
    'kZ^;LwkMNZ90QG$76pF`B*Q2P*=+*DKdprPwkvpkN-Q{N!()Naa{53K-lK?6WnjTc5IvZdD_3)$8gl6mAAK21ER*W6CVYI7-@o^2'
    '<Cv?I#}pSv08?K*DPMbo@?8fe!ag=Lr@(ny+<j1!q<S+5p0T=3(}homZKZV0zKSbY>*+{|0DJGvKZZ{CdT$HTtp%%l8Nto^b_lnb'
    'XUzNh%&S1nW-mjg)$h!xTLnx6yjKo(x{kv{ALGx=xIB}!25^Xg@UzU>75bvv>9|0uC<-J?a3GVu_g+*gI|5X;2&F+Yz+e6*IF-$@'
    'Q+ULb3)sbvxV00DP++g~zLbqPFwaD6h(DPX$I=Aak2nG+E^5J{4uai+x}o5@^V`Q9qcwb(EoQzvCNH5Ft7bKUp?UW4krC>lA}aXq'
    'Ua0<oRTN0^2k>u*VOGozD6cU(O$3(&P$2??VfX-9^fm)W7Q$W-dfMkBODqa^$$znXd3|+7N1cF_UA}+Qn!N^$u;k0ZInXO02z9SU'
    'f8cCY?>Le(AWafzMs)@PM!tORr;H;{sd>`etsVwaSn``O<k_*L9|O`xD&D%oq5P=2_!qJ5eCNF>T}vY4);ZrELKm9}HbtZ()I7TR'
    '1vkR0bRYoJt;^#-%TK)7RAqHYW=0_4`?ae=OapbDEk8?vc|?UM9o~x7`7jz8yitwNb{t-cF>Am6?ge1VPj2zo&=q4Po8|uUt5;+A'
    '<LV3-_|6Mw!3Na<$w@SU=c`@_$(6tTeF+VUC{c*ZD)bQRf*K74x<g0}kH`xiSLk*NXg5yq9?B7S_4(RblIo>^lqt^B*g51<&S{L1'
    '^+N-i8&YEygIefV;kuz#8a$elLynz)fp14CP|d@$VK}y=X_d~M4}`*uW~__PJ9vML^TGgAR;+DIf^r!B@QP8=Q~P7=1i~=W<t(WL'
    'AxJ4H3}-T8j7x{!R4yGVQX3YNs{Gzyv)?t0R=IxV+_(E-SK^R&4c5FoO-61bb{Damh}}c%7GihMYuu3Giq3#}GeX1|+tN1!FP}@-'
    'y+KkXWdc$VCtF01t>k8}j_v67%*z}PN&tevES^4c&<of|iqxiaLj)0vr@HY<Xc&UHXH1X<<%j?#j*}>UUb7!B@m!08L3mkwj-j%|'
    '4*A1nIp*a9WOi)ew9gC-)?i`w>Ea;hoWZxYp+HMt(_4iLr`)-6tmvGA)YD&AQV?j=Q}{r<x}t?-{cu;9zkJ|~RlheLk>SOW00rdx'
    'UXfp{-N0#Sk08F#fs+}*7=ZCc`#D7h5bVJ&{vhl?xw2F*aJuilEwH_va!5=O53@3+G&L|iOr(FQsjmzdCpgitHi^L5Bo%-Zjlw9<'
    '16FQXG>s*+p|rqsU_*m9U*YE-rHNQ?t|HtB&02`qM;JS%_~vc_3xYUd!kTA1(cnPq8G&hSQJ62muC=X?|FgG?Q!A9RdvbL|(_zF>'
    'o>ADE29J0KadaDDASFj2!}=7XXb~Pt=U)gVuwL&~Sr;Zk6O3G>nJyyV#RYi2Ho!xl;Ixa$A__XG=K|J*%{9j>fJhN>Mg{9fems3W'
    'QXKZ!(zkSJRWH37)l(WQu;17^>ppC#g>Eq#T+rd5Qp724%h&q0(4F<c`_|%3y+>jZv7#!hGL&?oDR7>VK;F9J2v=JLOT?s8H4;Tv'
    '^B-6CfG>FU<cpex85neYc!<3Pj~@EwBdk)%Nh3x$9mnDf9E{qK#N|w5iE~?YUu_+o8dr+N?IK%IIaY)(1?a4Gw$$)tIz0aoXzbU!'
    'SOlcm|A))|R=DguufwsfS+T5zvR=2qS%dgo>-S(z*u>HB=Iiby7f4c1nRcp1FY38w*EC;(LRhT9dzM5z3O%jCaTZru&>7Wzod%PY'
    'q7)H6FdedGhA4~&l0B)f<*X$j>ryN9i603V%~BSMGtpq8aBs;AHryh`<=38wO5qe#lv95c*F-DVa{eRzys;#SCSKrJ8!oLv>FQ-}'
    'bc4ymqI%g*MWl+8>OP&jT!ZFZdwvM>*Dw4bZ}mKazDUb+IVqs?ZzC3b*@;+&fTy8JDdcf<pMxT+q&8TMhF7Qp!CtUio{847T~1hL'
    'TXuM58mWTD*G@TWHHbop&-3!}Cg=p8VuO4iRJ!leJsiF;G4Sg2g2*Etn2Z+<hJh5;9$%CG=jd^m23dHD+rZg!u3ZQtkVn;*C~R9t'
    'a^x|5gS1LV0p7Tap0rlB#8V|S_sqabbqPWYImj0wx~Z#Nb>DOhmQLsoU7w0O#-j>HICKTTGQlWIJU&S4yrw*7>;D2%7&4~'
)


def run_fingerprint(source,runner_bytes,config,templates,executable_bytes,dependency_bytes):
    h=hashlib.sha256()
    for data in [source.encode(),runner_bytes,json.dumps(config,sort_keys=True).encode(),
                 json.dumps(templates,sort_keys=True).encode(),executable_bytes]:
        h.update(data)
    for data in dependency_bytes:h.update(data)
    return h.hexdigest()


def compatible_legacy_fingerprints(source,config,templates,test,executable_bytes,dependency_bytes):
    if not config['resume']:return ()
    import base64
    import zlib
    previous=zlib.decompress(base64.b85decode(_LEGACY_RUNNER_B85))
    if hashlib.sha256(previous).hexdigest()!=_LEGACY_RUNNER_SHA256:
        raise ValueError('Corrupt predecessor fingerprint data; cache migration disabled')
    old_config=dict(config)
    if test==POWER:
        # Accept only corrected-TB08 results, never the buggy GND-vector run.
        old_config['_tb08_ground_fix_sha256']=_LEGACY_TB08_PATCH_SHA256
    return (run_fingerprint(source,previous,old_config,templates,
                            executable_bytes,dependency_bytes),)

if __name__=='__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('Interrupted. Completed cases remain cached; re-run to resume.',file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print('PVT_RUNNER_ERROR: '+str(exc),file=sys.stderr)
        sys.exit(1)
