"""Read the existing reports only; do not launch or modify any simulation."""
from pathlib import Path
from collections import Counter, defaultdict
import hashlib
import json
import statistics

root=Path(__file__).resolve().parents[3] / 'results'
out=Path(__file__).resolve().parent/'summary.json'
data={}
reports={}

def load(label,rel):
    p=root/rel
    rows=[];summary=None;coverage=None
    digest=hashlib.sha256()
    with p.open('rb') as stream:
        for raw in stream:
            digest.update(raw)
            line=raw.decode('utf-8',errors='replace')
            if line.startswith('CASE '):rows.append(json.loads(line[5:]))
            elif line.startswith('SUMMARY '):summary=json.loads(line[8:])
            elif line.startswith('COVERAGE '):coverage=json.loads(line[9:])
    reports[label]=dict(report='results/'+Path(rel).as_posix(),sha256=digest.hexdigest(),bytes=p.stat().st_size,
                        recorded_cases=len(rows),status_counts=dict(Counter(r['status'] for r in rows)),summary=summary,
                        fingerprint=rows[0].get('fingerprint') if rows else None,
                        errors=dict(Counter(r.get('error','unspecified') for r in rows if r['status']!='complete')))
    return rows

def stat(values):
    values=list(values)
    return dict(n=len(values),minimum=min(values),median=statistics.median(values),maximum=max(values))

def nominal(rows):return [r for r in rows if r['status']=='complete' and r.get('range')=='nominal']
def tt(rows,v=3.3):
    return [r for r in rows if all(r.get(k)==value for k,value in dict(mos='typical',bjt='bjt_typical',res='res_typical',mim='mimcap_typical',temperature_C=25,vdd_V=v).items())]

names=['PSRR','LINE_REGULATION','STARTUP_RESTART','TEMPERATURE','LOOP_STABILITY','MONTE_CARLO','NOISE','POWER_DEVICE_LIMITS','SUPPLY_DISTURBANCE']
for i,name in enumerate(names,1):
    label=f'TB{i:02d}'
    rel=f'full/{label}_{name}_UPLOAD_THIS.txt'
    if i==5:rel=f'recheck_2026-09-28/full/{label}_{name}_UPLOAD_THIS.txt'
    rows=load(label,rel)
    nom=nominal(rows)
    metrics=[r['metrics'] for r in nom]
    item=dict(nominal_completed=len(nom),nominal_unresolved=sum(r.get('range')=='nominal' and r['status']!='complete' for r in rows))
    if i==1:
        item.update({field:stat(m[field] for m in metrics) for field in ['psrr_1hz_db','psrr_1khz_db','psrr_1mhz_db','psrr_min_1hz_1mhz_db']})
        worst=min(nom,key=lambda r:r['metrics']['psrr_min_1hz_1mhz_db'])
        item.update(worst_case_id=worst['case_id'],worst_frequency_Hz=worst['metrics']['psrr_min_frequency_Hz'],
                    original_target_pass=sum(bool(m['psrr_pass']) for m in metrics),dc_accuracy_valid=sum(bool(m['op_valid']) for m in metrics),
                    revised_ac_budget_met=sum(m['psrr_1khz_db']>=55 and m['psrr_min_1hz_1mhz_db']>=45 for m in metrics),
                    typical_3p3V=tt(rows)[0]['metrics'])
    elif i==2:
        good=[r for r in rows if r['status']=='complete']
        item=dict(sweeps=len(good),nominal_span_mV=stat(r['metrics']['nominal']['vref_span_mV'] for r in good),
                  nominal_span_percent=stat(r['metrics']['nominal']['span_percent_of_1p194V'] for r in good),
                  nominal_accuracy_pass=sum(r['metrics']['nominal']['all_points_within_0p5pct_of_1p194V'] for r in good),
                  revised_line_budget_met=sum(r['metrics']['nominal']['span_percent_of_1p194V']<=.1 for r in good),
                  stress_span_mV=stat(r['metrics']['full_stress_sweep']['vref_span_mV'] for r in good))
    elif i==3:
        valid=[r for r in nom if r['metrics']['pre_valid'] and r['metrics']['final_valid']]
        timing=[r for r in valid if not r['metrics']['start_ready_300us'] or not r['metrics']['restart_ready_300us']]
        item.update(valid_references=len(valid),accuracy_invalid=len(nom)-len(valid),
                    startup_ready=sum(bool(r['metrics']['start_ready_300us']) for r in valid),
                    restart_ready=sum(bool(r['metrics']['restart_ready_300us']) for r in valid),
                    timing_miss_case_ids=[r['case_id'] for r in timing],
                    nominal_start_peak_V=max(m['start_peak_v'] for m in metrics),
                    nominal_restart_peak_V=max(m['restart_peak_v'] for m in metrics))
    elif i==4:
        item.update(tc_normalized_ppm_C=stat(m['TC_normalized_to_1p194V_ppm_per_C'] for m in metrics),
                    tc_box_ppm_C=stat(m['TC_box_ppm_per_C'] for m in metrics),
                    tc_only_pass=sum(m['TC_pass'] for m in metrics),accuracy_pass=sum(m['accuracy_pass'] for m in metrics),
                    joint_pass=sum(m['temperature_accuracy_pass'] for m in metrics),
                    max_analog_current_uA=max(m['max_IDD_uA'] for m in metrics),
                    max_absolute_error_percent=max(m['max_absolute_error_percent'] for m in metrics),
                    typical={str(v):tt(rows,v)[0]['metrics'] for v in [3.3,5]})
    elif i==5:
        ok=[r for r in rows if r['status']=='complete']
        item.update(main_pm_deg=stat(m['loops']['main']['phase_margin_deg'] for m in metrics),
                    main_gain_margin_dB=stat(m['loops']['main']['minimum_gain_margin_dB'] for m in metrics),
                    bias_statuses=dict(Counter(m['loops']['bias']['status'] for m in metrics)),
                    bias_headroom_dB=stat(m['loops']['bias']['low_frequency_positive_feedback_gain_headroom_dB'] for m in metrics),
                    bias_min_abs_1_plus_L=min(m['loops']['bias']['minimum_sampled_abs_1_plus_L'] for m in metrics),
                    all_main_pm_min=min(r['metrics']['loops']['main']['phase_margin_deg'] for r in ok),
                    all_bias_headroom_min=min(r['metrics']['loops']['bias']['low_frequency_positive_feedback_gain_headroom_dB'] for r in ok),
                    max_dc_probe_error_V=max(abs(r['metrics'][field]) for r in ok for field in ['main_dc_error_v','bias_dc_error_v']),
                    accuracy_gate_rejections=sum('operating point outside' in r.get('error','') for r in rows))
    elif i==6:
        item['one_condition_25C_3p3V']={}
        for mode in ['global','mismatch','combined']:
            cohort=[r for r in nom if r['mc_mode']==mode and r['temperature_C']==25 and r['vdd_V']==3.3]
            values=[r['metrics']['op_vref_v'] for r in cohort]
            item['one_condition_25C_3p3V'][mode]=dict(n=len(values),mean_V=statistics.mean(values),
                values_V=values,
                sample_sigma_mV=statistics.stdev(values)*1000,accuracy_pass=sum(r['metrics']['op_reference_in_target'] for r in cohort),
                vref_min_V=min(values),vref_max_V=max(values),
                max_required_correction_mV=max(abs(r['metrics']['required_output_correction_mV']) for r in cohort))
    elif i==7:
        item.update(dc_accuracy_valid=sum(m['op_reference_in_target'] for m in metrics),
                    noise_low_band_uV=stat(m['bands'][0]['output_rms_uV'] for m in metrics),
                    noise_wide_band_uV=stat(m['bands'][1]['output_rms_uV'] for m in metrics))
    elif i==8:
        flags=[(r,d) for r in nom for d in r['metrics']['devices'] if d['voltage_screen_flag']]
        item.update(analog_current_uA=stat(m['op_idd_ua'] for m in metrics),
                    current_pass=sum(m['idd_within_limit'] for m in metrics),dc_accuracy_valid=sum(m['op_reference_in_target'] for m in metrics),
                    flagged_devices=dict(Counter(d['name'] for r,d in flags)),
                    max_flagged_device_voltage_V=max(d['max_abs_terminal_V'] for r,d in flags))
    elif i==9:
        valid=[r for r in nom if r['metrics']['op_reference_in_target']]
        misses=[r for r in valid if not r['metrics']['all_events_ready']]
        item.update(dc_accuracy_valid=len(valid),accuracy_invalid=len(nom)-len(valid),
                    valid_recovery_pass=sum(r['metrics']['all_events_ready'] for r in valid),
                    valid_recovery_miss=len(misses),valid_miss_by_kind=dict(Counter(r['scenario']['kind'] for r in misses)),
                    valid_miss_by_supply=dict(Counter(str(r['vdd_V']) for r in misses)),
                    max_overshoot_mV=max(m['max_recovery_overshoot_mV'] for m in metrics),
                    max_overshoot_accuracy_valid_mV=max(r['metrics']['max_recovery_overshoot_mV'] for r in valid))
        item['by_scenario']={}
        for kind in sorted({r['scenario']['kind'] for r in nom}):
            c=[r for r in nom if r['scenario']['kind']==kind]
            v=[r for r in c if r['metrics']['op_reference_in_target']]
            item['by_scenario'][kind]=dict(completed=len(c),dc_valid=len(v),ready=sum(r['metrics']['all_events_ready'] for r in v))
    data[label]=item

load('TB05_superseded','full/TB05_LOOP_STABILITY_UPLOAD_THIS.txt')
for label,rel in [('TB10_nominal','trim_nominal/TB10_RESISTOR_TRIM_UPLOAD_THIS.txt'),
                  ('TB10_partial_full','recheck_2026-09-28/full/TB10_RESISTOR_TRIM_UPLOAD_THIS.txt'),
                  ('TB10_dc_screen','trim_screen_2026-09-28/trim_screen/TB10_RESISTOR_TRIM_UPLOAD_THIS.txt')]:
    rows=load(label,rel)
    fixed=[p for r in rows for p in r.get('metrics',{}).get('fixed_code_results',[])]
    startup=[p for r in rows for p in r.get('metrics',{}).get('startup',[])]
    events=[e for s in startup for e in s.get('events',[])]
    data[label]=dict(recorded_bundles=len(rows),status_counts=dict(Counter(r['status'] for r in rows)),
        bundles_with_metrics=sum(bool(r.get('metrics')) for r in rows),
        dc_sweep_points=sum(r.get('dc_operating_points',0) for r in rows),
        extra_calibration_points=sum(r.get('calibration_dc_operating_points',0) for r in rows),
        fixed_code_points=len(fixed),fixed_code_accuracy_pass=sum(p.get('accuracy_pass',abs(p['error_mV'])<=1.194*.005*1000) for p in fixed),
        fixed_code_self_sustaining=sum(p['self_sustaining_op'] for p in fixed),
        selected_codes=sorted({r['metrics']['calibration_code'] for r in rows if r.get('metrics')}),
        startup_runs=len(startup),startup_status_counts=dict(Counter(s['status'] for s in startup)),
        event_status_counts=dict(Counter(e['status'] for e in events)),
        nominal_startup_counts=dict(Counter(s['status'] for s in startup if 3.3<=s['avdd_V']<=5)),
        nominal_event_status_counts=dict(Counter(e['status'] for s in startup if 3.3<=s['avdd_V']<=5 for e in s.get('events',[]))))
    if fixed:
        data[label].update(vref_V=stat(p['vref_V'] for p in fixed),
                           maximum_error_percent=max(abs(p['error_mV'])/1000/1.194*100 for p in fixed),
                           max_analog_current_uA=max(p['analog_idd_A'] for p in fixed)*1e6)
    if label=='TB10_dc_screen':
        data[label]['accuracy_misses']=[dict(case_id=r['case_id'],temperature_C=r['temperature_C'],**p) for r in rows for p in r['metrics']['fixed_code_results'] if not p['accuracy_pass']]
    if label=='TB10_nominal':
        data[label]['startup_events']=[dict(supply_V=s['avdd_V'],events=s.get('events',[])) for s in startup]

data['TB10_dense_tc']=json.loads((root/'trim_tc_2026-09-28/SUMMARY.json').read_text())
tc_summary_path=root/'trim_tc_2026-09-28/SUMMARY.json'
reports['TB10_dense_tc']=dict(report='results/trim_tc_2026-09-28/SUMMARY.json',
    sha256=hashlib.sha256(tc_summary_path.read_bytes()).hexdigest(),bytes=tc_summary_path.stat().st_size,
    summary=data['TB10_dense_tc'])
out.write_text(json.dumps(dict(sources=reports,derived=data),indent=2,allow_nan=False)+'\n',encoding='utf-8')
print(f'Reviewed {len(reports)} saved evidence sources; wrote {out}. No simulator was invoked.')
