#!/usr/bin/env python3
"""Export and test the repository resistor-trim core without editing the DUT or PDK."""
import argparse
import concurrent.futures
import csv
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid

import numpy as np

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / 'Bandgap_Core_Res.sch'
PDK = Path(os.environ.get('GF180_PDK_PATH', str(Path(os.environ.get('PDK_ROOT', '/foss/pdks'))/'gf180mcuD')))
BUILD = ROOT / 'generated/unprepared'
PORTS = 'avdd avss vref b0 b1 b2 b3 b4 b5 b6 dvss dvdd'
TARGET = 1.194
IDS = ('xm7', 'xm20', 'xsupinj', 'xn1', 'xm16', 'xm18')
FIELDS = ['code', 'avdd_V', 'dvdd_V', 'vref_V', 'vq3_V', 'analog_idd_A',
          'digital_idd_A', 'error_mV'] + [x + '_A' for x in IDS]
ERRORS = re.compile(r'error:|error on line|timestep too small|simulation(?:s)? aborted|'
                    r'no such vector|unknown parameter|fatal error', re.I)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def create(path, content):
    """Do not silently overwrite a hand-edited bench or snapshot."""
    if path.exists() and path.read_text() != content:
        raise RuntimeError(f'{path} already exists with different content; use a new bench folder')
    if not path.exists():
        path.write_text(content)


def bits(code):
    if not 0 <= code < 128:
        raise ValueError('7-bit code must be in 0..127')
    return [(code >> i) & 1 for i in range(7)]


def sweep_control(output):
    lines = ['.control', 'set noaskquit', 'set num_threads=1', 'set numdgt=15',
             'set wr_singlescale', 'unset wr_vecnames', 'set appendwrite',
             'save all ' + ' '.join(f'@m.x1.{x}.m0[id]' for x in IDS),
             'echo ' + ' '.join(FIELDS) + f' > {output}',
             'foreach supply 3.3 5', 'alter VDD dc = $supply',
             'foreach code ' + ' '.join(map(str, range(128)))]
    for i in range(7):
        lines += [f'let bit_value = 3.3*(floor($code/{2**i})-2*floor($code/{2**(i+1)}))',
                  f'alter VBIT{i} dc = $&bit_value']
    lines += ['op', 'let vr = v(vref)', 'let vq = v(x1.vq3)',
              'let ia = -i(vdd)', 'let idig = -i(vdvdd)',
              f'let err = 1000*(v(vref)-{TARGET})']
    for i, dev in enumerate(IDS):
        lines.append(f'let cur{i} = @m.x1.{dev}.m0[id]')
    lines += ['let code_value = $code', 'let supply_value = $supply', 'let digital_value = 3.3',
              'setscale code_value', f'wrdata {output} supply_value digital_value vr vq ia idig err ' +
              ' '.join(f'cur{i}' for i in range(6)),
              'destroy $curplot', 'end', 'end', 'echo TRIM_SWEEP_COMPLETE', '.endc']
    return '\n'.join(lines) + '\n'


def export(sch):
    # Tcl braces protect the search path; prepare() rejects unsupported whitespace.
    library = f':{BUILD}:{ROOT.parent}:{PDK}/libs.tech/xschem'
    cmd = ['xschem', '-x', '-r', '-n', '-q', '-s', '--rcfile',
           str(PDK/'libs.tech/xschem/xschemrc'),
           '--tcl', f'append XSCHEM_LIBRARY_PATH {{{library}}}',
           '-o', str(BUILD), str(sch)]
    p = subprocess.run(cmd, cwd=ROOT.parent, text=True, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, timeout=60)
    (BUILD/(sch.stem+'.xschem.log')).write_text(p.stdout)
    if p.returncode or re.search(r'Error: undriven|shorted output|symbol not found', p.stdout, re.I):
        raise RuntimeError(f'Xschem export failed: {p.stdout}')


def prepare():
    global BUILD, PDK
    PDK = PDK.expanduser().resolve()
    # ngspice control-language filenames and Tcl search paths have quoting limits.
    for path in (ROOT, PDK):
        if re.search(r'\s|[{}:$;"\\\\]', str(path)):
            raise RuntimeError('Use checkout and PDK paths without whitespace or Tcl/SPICE metacharacters')
    for path in (SOURCE, ROOT.parent/'Bandgap_Core_Res.sym',
                 ROOT.parent/'TB10_RESISTOR_TRIM.sch', ROOT/'preserved_mim.lib',
                 PDK/'libs.tech/xschem/xschemrc',
                 PDK/'libs.tech/ngspice/design.ngspice',
                 PDK/'libs.tech/ngspice/sm141064.ngspice'):
        if not path.is_file():
            raise FileNotFoundError(f'Required input missing: {path}')
    BUILD = ROOT/'generated'/('prepare_'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:6])
    BUILD.mkdir(parents=True, exist_ok=False)
    (BUILD/'manual_results').mkdir()
    inputs = [SOURCE, ROOT.parent/'Bandgap_Core_Res.sym',
              ROOT.parent/'TB10_RESISTOR_TRIM.sch', ROOT/'preserved_mim.lib']
    input_hashes = {str(p): digest(p) for p in inputs}
    for path in inputs:
        shutil.copyfile(path, BUILD/path.name)
    modeldir = PDK/'libs.tech/ngspice'
    entry_hashes = {str(modeldir/f): digest(modeldir/f)
                    for f in ['design.ngspice', 'sm141064.ngspice']}
    modeltext = f'.include {modeldir}/design.ngspice\n'
    modeltext += ''.join(f'.lib {modeldir}/sm141064.ngspice {c}\n'
                         for c in ['typical', 'bjt_typical', 'res_typical'])
    modeltext += f'.include {BUILD}/preserved_mim.lib\n'
    modeltext += '.param sw_stat_global=0 sw_stat_mismatch=0 fnoicor=0\n'
    modeltext += '.options tnom=25 numdgt=15 method=gear maxord=2 reltol=1e-5 vntol=1e-7 abstol=1e-13 itl4=200\n.temp 25\n'
    create(BUILD/'gf180_models.lib', modeltext)
    # Read by Xschem's tcleval format, so .control is INLINE in the exported deck.
    # A SPICE .include of a control file strips $ variables in the tested ngspice.
    setup = f'.include {BUILD}/gf180_models.lib\n' + sweep_control(BUILD/'manual_results/trim_sweep.txt')
    create(BUILD/'manual_setup.spice', setup)
    (ROOT/'generated/manual_setup.spice').write_text(setup)
    export(BUILD/'Bandgap_Core_Res.sch')
    raw = (BUILD/'Bandgap_Core_Res.spice').read_text()
    header = f'**.subckt Bandgap_Core_Res {PORTS}\n'
    if header not in raw:
        raise RuntimeError('Unexpected DUT pin order')
    body = raw.split(header, 1)[1].split('**.ends', 1)[0]
    create(BUILD/'Bandgap_Core_Res.inc',
           f'.subckt Bandgap_Core_Res {PORTS}\n'+body+'.ends Bandgap_Core_Res\n')
    export(BUILD/'TB10_RESISTOR_TRIM.sch')
    bench = (BUILD/'TB10_RESISTOR_TRIM.spice').read_text()
    if '.control' not in bench or 'alter VDD dc = $supply' not in bench or 'TRIM_SWEEP_COMPLETE' not in bench:
        raise RuntimeError('Xschem did not inline the trim controls correctly')
    for path, sha in {**input_hashes, **entry_hashes}.items():
        if digest(path) != sha:
            raise RuntimeError(f'Input changed during preparation: {path}')
    files = ['Bandgap_Core_Res.sch', 'Bandgap_Core_Res.sym', 'Bandgap_Core_Res.inc',
             'Bandgap_Core_Res.spice', 'preserved_mim.lib', 'gf180_models.lib',
             'TB10_RESISTOR_TRIM.sch', 'TB10_RESISTOR_TRIM.spice', 'manual_setup.spice']
    manifest = dict(build=str(BUILD), source=str(SOURCE), source_sha256=digest(SOURCE),
                    model_root=str(modeldir), inputs=input_hashes,
                    files={f:digest(BUILD/f) for f in files},
                    installed_model_entry_hashes=entry_hashes,
                    model_note='Native installed MOS/BJT/resistor models; verbatim inherited embedded MIM; no nwell workaround.')
    save_json(BUILD/'prepared.json', manifest)
    save_json(ROOT/'generated/prepared.json', manifest)
    print(f'Prepared snapshot: {BUILD}', flush=True)


def dc_deck(output):
    text = '* Resistor trim: 256 deterministic operating points\n'
    text += f'.include {BUILD}/gf180_models.lib\n.include {BUILD}/Bandgap_Core_Res.inc\n'
    text += 'VDD avdd 0 3.3\nVDVDD dvdd 0 3.3\n'
    text += ''.join(f'VBIT{i} b{i} 0 0\n' for i in range(7))
    text += 'X1 avdd 0 vref b0 b1 b2 b3 b4 b5 b6 0 dvdd Bandgap_Core_Res\n'
    return text + sweep_control(output) + '.end\n'


def simulate(deck, timeout):
    logfile = deck.with_suffix('.log')
    env = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1')
    p = subprocess.run(['ngspice','-n','-b','-o',str(logfile),str(deck)],cwd=deck.parent,
                       stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=timeout,env=env)
    log = logfile.read_text() if logfile.exists() else ''
    if p.returncode or ERRORS.search(log):
        raise RuntimeError(f'Incomplete/error simulation: {logfile}\n{p.stdout}\n{log[-1800:]}')
    return log


def read_sweep(path):
    data = np.loadtxt(path,skiprows=1,ndmin=2)
    if data.shape != (256,len(FIELDS)) or not np.isfinite(data).all():
        raise RuntimeError(f'Incomplete/nonfinite sweep: {data.shape}')
    if set((int(x[0]),x[1]) for x in data) != {(c,v) for c in range(128) for v in (3.3,5.)}:
        raise RuntimeError('Missing or duplicate trim codes')
    rows = [dict(zip(FIELDS,map(float,row))) for row in data]
    for row in rows:
        row['code'] = int(row['code'])
        row['bits_b6_to_b0'] = format(row['code'],'07b')
        row['self_sustaining_op'] = all(abs(row[x+'_A'])<=1e-9 for x in IDS[:3]) and all(abs(row[x+'_A'])>1e-8 for x in IDS[3:])
    return rows


def startup_deck(vdd,code):
    text = f'* Fixed trim code {code}, digital-first startup and analog restart\n'
    text += f'.include {BUILD}/gf180_models.lib\n.include {BUILD}/Bandgap_Core_Res.inc\n'
    text += f'VDD avdd 0 PWL(0 0 20u 0 120u {vdd} 4m {vdd} 4001u 0 4500u 0 4501u {vdd} 6m {vdd})\n'
    text += 'VDVDD dvdd 0 PWL(0 0 1u 0 11u 3.3 6m 3.3)\n'
    text += ''.join(f'EBIT{i} b{i} 0 dvdd 0 {b}\n' for i,b in enumerate(bits(code)))
    text += 'X1 avdd 0 vref b0 b1 b2 b3 b4 b5 b6 0 dvdd Bandgap_Core_Res\n'
    vectors = {'avdd':'v(avdd)','dvdd':'v(dvdd)','vref':'v(vref)','vq3':'v(x1.vq3)',
               'analog_idd':'-i(vdd)','digital_idd':'-i(vdvdd)'}
    vectors.update({d:f'@m.x1.{d}.m0[id]' for d in IDS})
    vectors.update({f'b{i}':f'v(b{i})' for i in range(7)})
    vectors.update({f'b{i}_b':f'v(x1.b{i}_b)' for i in range(7)})
    vectors.update({f'rbit{i}top':f'v(x1.rbit{i}top)' for i in range(7)})
    text += '.control\nset noaskquit\nset num_threads=1\nset numdgt=15\nset wr_singlescale\nset wr_vecnames\n'
    text += 'save all '+' '.join(f'@m.x1.{d}.m0[id]' for d in IDS)+'\ntran 100n 6m 0 100n\n'
    for key,expr in vectors.items():
        text += f'let out_{key} = {expr}\n'
    text += 'wrdata trace.txt '+' '.join('out_'+k for k in vectors)+'\necho STARTUP_COMPLETE\n.endc\n.end\n'
    return text,list(vectors)


def startup_result(path,columns):
    a = np.loadtxt(path,skiprows=1,ndmin=2)
    if a.shape[1] != len(columns)+1 or not np.isfinite(a).all() or a[-1,0] < .006-1e-10:
        raise RuntimeError('Startup trace incomplete/nonfinite')
    t,d = a[:,0],dict(zip(columns,a[:,1:].T))
    d['zero'] = np.zeros_like(t)
    good = np.abs(d['vref']-TARGET)<=TARGET*.005
    for dev in IDS[:3]:
        good &= np.abs(d[dev])<=1e-9
    for dev in IDS[3:]:
        good &= np.abs(d[dev])>1e-8
    events=[]
    for name,start,end in [('cold',120e-6,.004),('restart',.004501,.006)]:
        indexes=np.flatnonzero((t>=start)&(t<=end))
        bad=indexes[~good[indexes]]
        first=(bad[-1]+1) if len(bad) else indexes[0]
        settled=first<=indexes[-1] and t[indexes[-1]]-t[first]>=100e-6
        delay=float(t[first]-start) if settled else None
        tail=(t>=end-100e-6)&(t<=end)
        events.append(dict(event=name,settle_after_ramp_us=None if delay is None else delay*1e6,
                           status='PASS' if delay is not None and delay<=300e-6 else 'FAIL',
                           tail_vref_V=float(np.mean(d['vref'][tail])),
                           tail_startup_max_A={x:float(np.max(np.abs(d[x][tail]))) for x in IDS[:3]}))
    stress=[]
    for bit in range(7):
        high,low=f'rbit{bit}top', f'rbit{bit+1}top' if bit<6 else 'vq3'
        for name,gate,body in [(f'M{24+2*bit}',f'b{bit}_b','dvdd'),(f'M{25+2*bit}',f'b{bit}','zero')]:
            max_gate=max(float(np.max(np.abs(d[gate]-d[n]))) for n in [high,low,body])
            forward=max(float(np.max(d[n]-d[body])) for n in [high,low]) if body=='dvdd' else max(float(np.max(d[body]-d[n])) for n in [high,low])
            stress.append(dict(device=name,max_abs_gate_to_node_V=max_gate,
                               max_body_junction_forward_bias_V=forward,
                               above_3p63V_thin_oxide_screen=max_gate>3.63))
    return dict(events=events,trim_switch_stress=stress,rows=len(t)),t,d


def run(timeout,dc_only):
    global BUILD
    manifest=json.loads((ROOT/'generated/prepared.json').read_text())
    BUILD=Path(manifest['build'])
    for path,sha in {**manifest['inputs'], **manifest['installed_model_entry_hashes']}.items():
        if not Path(path).is_file() or digest(path)!=sha:
            raise RuntimeError(f'Input changed: {path}; run --prepare-only before --run-only')
    for name,sha in manifest['files'].items():
        if digest(BUILD/name)!=sha:
            raise RuntimeError(f'Prepared file changed: {name}; run --prepare-only again')
    out=ROOT/'runs'/('run_'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:6])
    out.mkdir(parents=True,exist_ok=False)
    save_json(out/'manifest.json',dict(prepared=manifest,runner_sha256=digest(__file__),
              ngspice=subprocess.check_output(['ngspice','--version'],text=True),
              scope='TT MOS/BJT/resistors/inherited MIM, 25 C, AVDD 3.3/5 V, DVDD 3.3 V, no external load',
              calibration='One code chosen at 25 C/3.3 V and retained at 5 V. Per-supply optima reported separately.'))
    deck=out/'TB10_RESISTOR_TRIM.spice'
    deck.write_text(dc_deck(out/'trim_sweep.txt'))
    print(f'Running 256 DC points: {out}',flush=True)
    log=simulate(deck,timeout)
    if 'TRIM_SWEEP_COMPLETE' not in log:
        raise RuntimeError('Missing sweep completion marker')
    rows=read_sweep(out/'trim_sweep.txt')
    with (out/'trim_sweep.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    summary={}
    for v in (3.3,5.):
        rr=[r for r in rows if r['avdd_V']==v]
        valid=[r for r in rr if r['self_sustaining_op']]
        if not valid:
            raise RuntimeError(f'No self-sustaining operating points at {v} V')
        best=min(valid,key=lambda r:abs(r['error_mV']))
        volts=np.array([r['vref_V'] for r in rr])
        summary[str(v)]=dict(best_code=best['code'],bits_b6_to_b0=best['bits_b6_to_b0'],
                           best_vref_V=best['vref_V'],best_error_mV=best['error_mV'],
                           min_vref_V=float(volts.min()),max_vref_V=float(volts.max()),
                           largest_sorted_gap_mV=float(np.max(np.diff(np.sort(volts)))*1e3),
                           upward_code_steps=int(np.count_nonzero(np.diff(volts)>1e-8)),
                           self_sustaining_codes=len(valid))
    code=summary['3.3']['best_code']
    held=[r for r in rows if r['code']==code]
    results=dict(dc=summary,calibration_code=code,fixed_code_results=held,startup=[])
    print(json.dumps(results,indent=2),flush=True)
    traces=[]
    if not dc_only:
        def job(v):
            case=out/f'startup_{str(v).replace(".","p")}V_code{code}'
            case.mkdir()
            content,cols=startup_deck(v,code)
            p=case/'TB10_TRIM_STARTUP.spice';p.write_text(content)
            save_json(case/'columns.json',['time_s']+cols)
            try:
                log=simulate(p,timeout)
                if 'STARTUP_COMPLETE' not in log: raise RuntimeError('Missing startup completion marker')
                metrics,t,d=startup_result(case/'trace.txt',cols)
                result=dict(avdd_V=v,code=code,status='COMPLETE',**metrics)
                save_json(case/'result.json',result)
                return result,(v,t,d)
            except (RuntimeError,subprocess.TimeoutExpired) as exc:
                result=dict(avdd_V=v,code=code,status='UNRESOLVED',error=str(exc))
                save_json(case/'result.json',result)
                return result,None
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            for result,trace in pool.map(job,[3.3,5.]):
                results['startup'].append(result)
                if trace: traces.append(trace)
                print(json.dumps(result),flush=True)
    save_json(out/'summary.json',results)
    plot(out,rows,traces)
    report=['# Resistor-trim testbench results','',f'Calibration target: {TARGET} V. TT / 25 C; DVDD=3.3 V.',
            '','All 128 codes tested at each analog supply. Bit 1 bypasses its segment.',
            '','| AVDD | Best code | VREF | Error | Range |','|---|---:|---:|---:|---:|']
    for v,s in summary.items():
        report.append(f'| {v} V | {s["best_code"]} | {s["best_vref_V"]:.9f} V | {s["best_error_mV"]:.6f} mV | {s["min_vref_V"]:.6f}–{s["max_vref_V"]:.6f} V |')
    report += ['',f'Fixed calibration code: **{code}** (`{code:07b}`, b6..b0), selected only at 3.3 V.',
               '']
    for r in held:
        report.append(f'- Same code at {r["avdd_V"]} V: VREF={r["vref_V"]:.9f} V; error={r["error_mV"]:.6f} mV.')
    for v,s in summary.items():
        report.append(f'- {v} V: {s["self_sustaining_codes"]}/128 self-sustaining DC points; {s["upward_code_steps"]} upward code steps; largest sorted voltage gap {s["largest_sorted_gap_mV"]:.6f} mV.')
    report += ['','## Selected-code startup / restart','',
               'DVDD ramps first and stays powered during analog shutdown/restart. Inputs track DVDD.',
               'PASS: within 1.194 V +/-0.5%, all three startup aids <=1 nA, bias branches >10 nA,',
               'settled within 300 us after the analog ramp and sustained to the end of the observation window.',
               'Final observation window is at least 100 us. Maximum transient step is 100 ns.','']
    for r in results['startup']:
        if r['status']!='COMPLETE': report.append(f'- {r["avdd_V"]} V: UNRESOLVED; see case log.');continue
        for e in r['events']:
            report.append(f'- {r["avdd_V"]} V {e["event"]}: {e["status"]}; settling {e["settle_after_ramp_us"]} us.')
    if dc_only: report.append('Not run (--dc-only).')
    report += ['','## Limits','',
               'No full PVT, Monte Carlo, post-layout, all-code startup, noise, PSRR, or DVDD-loss qualification.',
               'A completed analysis is not automatically an electrical pass. DC calibration is not startup proof.',
               'Trim-switch gate and body-junction voltage screens are in the startup result.json files; not foundry signoff.',
               'The original embedded MIM block is preserved verbatim; native resistor models are unchanged.',
               'No installed PDK changes or resistor-junction workaround were used.','',
               '[Trim plot](trim_sweep.png) · [CSV](trim_sweep.csv) · [Summary](summary.json)','']
    (out/'REPORT.md').write_text('\n'.join(report))
    print(f'REPORT: {out}/REPORT.md',flush=True)


def plot(out,rows,traces):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(2,1,figsize=(9,7),sharex=True)
    for v in (3.3,5.):
        rr=[r for r in rows if r['avdd_V']==v]
        code=np.array([r['code'] for r in rr]);volts=np.array([r['vref_V'] for r in rr])
        axes[0].plot(code,volts,label=f'AVDD {v} V')
        axes[1].plot(code[1:],-np.diff(volts)*1e3,label=f'AVDD {v} V')
    axes[0].axhline(TARGET,color='black',ls='--',lw=.8,label='1.194 V target')
    axes[0].set_ylabel('VREF (V)');axes[1].set_ylabel('Previous minus next (mV)')
    axes[1].set_xlabel('Bypass code (b6..b0); 1 = resistor bypassed')
    axes[0].set_title('Physical resistor trim: TT, 25 C, DVDD = 3.3 V')
    for ax in axes:ax.grid(alpha=.25);ax.legend()
    fig.tight_layout();fig.savefig(out/'trim_sweep.png',dpi=150);fig.savefig(out/'trim_sweep.svg');plt.close(fig)
    if traces:
        fig,axes=plt.subplots(2,1,figsize=(10,6),sharex=True)
        for v,t,d in traces:
            axes[0].plot(t*1e3,d['vref'],label=f'AVDD {v} V')
            axes[1].semilogy(t*1e3,np.maximum.reduce([np.abs(d[x]) for x in IDS[:3]])+1e-18,label=f'AVDD {v} V')
        axes[0].axhline(TARGET,color='black',ls='--',lw=.7);axes[0].set_ylabel('VREF (V)')
        axes[1].axhline(1e-9,color='black',ls='--',lw=.7);axes[1].set_ylabel('Largest startup-aid |I| (A)')
        axes[1].set_xlabel('Time (ms)')
        for ax in axes:ax.grid(alpha=.25);ax.legend()
        fig.tight_layout();fig.savefig(out/'startup.png',dpi=150);plt.close(fig)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    group=ap.add_mutually_exclusive_group()
    group.add_argument('--prepare-only',action='store_true')
    group.add_argument('--run-only',action='store_true')
    ap.add_argument('--dc-only',action='store_true')
    ap.add_argument('--timeout',type=float,default=180)
    ap.add_argument('--pdk-path',type=Path,help='Installed GF180MCUD directory (default: $GF180_PDK_PATH, $PDK_ROOT/gf180mcuD, or /foss/pdks/gf180mcuD)')
    args=ap.parse_args()
    if args.pdk_path:
        if args.run_only:ap.error('--pdk-path requires preparation; omit --run-only')
        PDK=args.pdk_path
    if not args.run_only:prepare()
    if not args.prepare_only:run(args.timeout,args.dc_only)
