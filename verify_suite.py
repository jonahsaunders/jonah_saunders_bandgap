#!/usr/bin/env python3
"""Software checks only; no ngspice/PDK or electrical signoff implied."""
import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import run_bandgap as rb
import prepare_reruns as pr

HERE=Path(__file__).resolve().parent

class SuiteChecks(unittest.TestCase):
    def test_selected_run_reports_partial_coverage_in_separate_root(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);old=root/'old';old.mkdir();sentinel=old/'baseline.txt';sentinel.write_text('keep this')
            config=json.loads((HERE/'bandgap_config.json').read_text())
            config['output_directory']=str(old)
            config_path=root/'config.json';config_path.write_text(json.dumps(config))
            c,_=rb.load_config(config_path,rb.TESTS[0],'full')
            planned=list(rb.cases(c,rb.TESTS[0]))
            ids=root/'cases.txt';ids.write_text(planned[0]['case_id']+'\n')
            model=root/'models.spice'
            model.write_text(''.join('.lib '+section+'\n' for values in rb.ALLOWED.values() for section in values))
            executable=root/'simulator';executable.write_bytes(b'not executed')
            def case_result(case,**kwargs):return dict(case,status='complete',resumed=False,metrics={})
            argv=['run_bandgap.py','--test',rb.TESTS[0],'--deck',str(root/'input.spice'),
                  '--config',str(config_path),'--profile','full','--case-ids-file',str(ids),
                  '--results-root',str(root/'new')]
            with mock.patch.object(rb.sys,'argv',argv),mock.patch.object(rb,'prepare_source',return_value=('',[model])), \
                 mock.patch.object(rb,'model_dependencies',return_value=[model]), \
                 mock.patch.object(rb.shutil,'which',return_value=str(executable)), \
                 mock.patch.object(rb,'compatible_legacy_fingerprints',return_value=()), \
                 mock.patch.object(rb,'run_case',side_effect=case_result), \
                 mock.patch.object(rb,'summarize',return_value=dict(execution_failed_or_timed_out=0)), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(rb.main(),0)
            report=(root/'new/full'/f'{rb.TESTS[0]}_UPLOAD_THIS.txt').read_text()
            self.assertIn('INCOMPLETE_FULL_GRID_SELECTED_CASES_ONLY',report)
            summary=json.loads(next(l[8:] for l in report.splitlines() if l.startswith('SUMMARY ')))
            self.assertEqual(summary['planned_cases'],2835)
            self.assertEqual(summary['selected_cases'],1)
            self.assertTrue(summary['selected_cases_complete'])
            self.assertFalse(summary['full_grid_complete'])
            self.assertEqual(sentinel.read_text(),'keep this')
            self.assertEqual(len(list(old.iterdir())),1)

    def test_prepare_reruns_keeps_sources_and_refuses_existing_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'old';source.mkdir();project=root/'project';project.mkdir()
            for name in ('run_bandgap.py','plot_bandgap.py','bandgap_config.json'):
                (project/name).write_text('original source\n')
            rows=[dict(case_id='failed',status='failed',range='nominal'),
                  dict(case_id='offset',status='complete',range='nominal',metrics=dict()),
                  dict(case_id='timing',status='complete',range='nominal',metrics=dict(
                      pre_valid=1,final_valid=1,start_ready_300us=0,restart_ready_300us=1,
                      op_reference_in_target=True,all_events_ready=False))]
            for test in ('TB03_STARTUP_RESTART','TB09_SUPPLY_DISTURBANCE'):
                (source/(test+'_UPLOAD_THIS.txt')).write_text(''.join('CASE '+json.dumps(r)+'\n' for r in rows))
            before={p.name:p.read_bytes() for p in source.iterdir()}
            output=root/'new';counts=pr.prepare(source,output,project)
            self.assertEqual(set(counts.values()),{2})
            self.assertEqual(before,{p.name:p.read_bytes() for p in source.iterdir()})
            self.assertEqual((output/'selections/TB03_STARTUP_RESTART.txt').read_text(),'failed\ntiming\n')
            with self.assertRaisesRegex(ValueError,'already exists'):pr.prepare(source,output,project)
            self.assertIn('--results-root "$ROOT"',(output/'run_selected.sh').read_text())

    def test_explicit_case_selection(self):
        planned=[dict(case_id=k) for k in ('a','b','c')]
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'selection.txt'
            path.write_text('# known failures\nc\na\n')
            self.assertEqual([r['case_id'] for r in rb.select_cases(planned,path)],['a','c'])
            self.assertEqual(rb.select_cases(planned,path,1),[planned[0]])
            for bad in ('a\na\n','missing\n','# empty\n'):
                path.write_text(bad)
                with self.assertRaises(ValueError):rb.select_cases(planned,path)

    def config(self,test=rb.POWER,profile='smoke'):
        return rb.load_config(HERE/'bandgap_config.json',test,profile)[0]

    def test_one_json_and_ten_controls(self):
        self.assertEqual([p.name for p in HERE.glob('*.json')],['bandgap_config.json'])
        _,templates=rb.load_config(HERE/'bandgap_config.json',rb.MC)
        self.assertEqual(set(templates),set(rb.TESTS))

    def test_full_corner_grids(self):
        expected={rb.TESTS[0]:2835,rb.TESTS[1]:405,rb.TESTS[2]:2835,rb.TC:945,rb.LG:2835,rb.MC:6300,rb.NOISE:2835,rb.POWER:2835,rb.DISTURB:33210}
        for test,n in expected.items():
            c=self.config(test,'full');rb.validate_config(c);cases=list(rb.cases(c,test))
            self.assertEqual(len(cases),n,test)
            self.assertEqual(len({v['case_id'] for v in cases}),len(cases),test)

    def test_loop_smoke_profile(self):
        # The default profile is user-configurable; exercise smoke explicitly.
        c,_=rb.load_config(HERE/'bandgap_config.json',rb.LG,'loop_smoke')
        self.assertEqual(c['_profile'],'loop_smoke');self.assertEqual(len(list(rb.cases(c,rb.LG))),1)

    def test_mc_same_seed_across_temperature_and_voltage(self):
        c=self.config(rb.MC,'full');c['mc_samples']=2
        cs=list(rb.cases(c,rb.MC))
        for mode in c['mc_modes']:
            for seed in [c['mc_seed_start'],c['mc_seed_start']+1]:
                self.assertEqual(len([x for x in cs if x['seed']==seed and x['mc_mode']==mode]),21)
        self.assertTrue(all(x['mos']=='statistical' for x in cs))

    def test_noise_integral_white_and_one_over_f(self):
        rows=[[1,2e-9,4e-18],[10,2e-9,4e-18],[100,2e-9,4e-18]]
        self.assertAlmostEqual(rb.integrate_psd(rows,2,90)/math.sqrt(4e-18*88),1,places=12)
        rows=[[1,1,1],[10,math.sqrt(.1),.1],[100,.1,.01]]
        self.assertAlmostEqual(rb.integrate_psd(rows,2,90)/math.sqrt(math.log(45)),1,places=12)

    def test_recovery_requires_staying_in_band(self):
        c=self.config();c['transient_max_step_s']=.0001
        target=c['reference_target_V'];rows=[[i*.0001,5,target,40] for i in range(11)]
        rows[7][2]=1.0
        m=rb.recovery_metrics(rows,0,.001,c)
        self.assertAlmostEqual(m['settling_time_s'],.0008);self.assertFalse(m['ready_by_deadline'])
        rows[-1][2]=1.0
        self.assertIsNone(rb.recovery_metrics(rows,0,.001,c)['settling_time_s'])

    def test_disturbance_points_and_recovery_windows(self):
        c=self.config(rb.DISTURB,'full');c.update(mos_corners=['typical'],bjt_corners=['bjt_typical'],res_corners=['res_typical'],mim_corners=['mimcap_typical'],temperatures_C=[25])
        kinds=set()
        for case in rb.cases(c,rb.DISTURB):
            pts,edges,stop=rb.disturbance_waveform(case,c);kinds.add(case['scenario']['kind'])
            self.assertTrue(all(b[0]>a[0] for a,b in zip(pts,pts[1:])))
            self.assertTrue(all(t+c['recovery_observe_s']<=stop+1e-12 for t in edges))
            self.assertEqual(pts[-1][1],case['vdd_V'])
        self.assertEqual(kinds,{'ramp','brownout','cycles','step'})

    def test_missing_completion_and_nonfinite_noise_rejected(self):
        c=self.config(rb.NOISE);c['_case']=next(rb.cases(c,rb.NOISE))
        with self.assertRaises(ValueError):rb.read_result('op_vref_v = 1.194\nop_idd_ua = 40\n',rb.NOISE,c)
        with self.assertRaises(ValueError):rb.blocks('BEGIN_NOISE_DATA\n1 nan nan\nEND_NOISE_DATA')

    def test_disconnected_loop_rejected(self):
        with self.assertRaises(ValueError):rb.validate_loop_dut_connection('X1 avdd vref 0 Bandgap_Core\nVLG_MAIN lg_main_e lg_main_f 0')
        rb.validate_loop_dut_connection('X1 avdd vref 0 lg_main_e lg_main_f lg_bias_e lg_bias_f Bandgap_Core_LoopProbe\nVLG_MAIN lg_main_e lg_main_f 0')

    def test_device_mapping_uses_actual_instance(self):
        source='Xsomething avdd vref 0 Bandgap_Core\n.subckt Bandgap_Core avdd vref avss\nXM1 vref gate avss avss nfet_03v3 w=1u l=1u\n.ends Bandgap_Core\n'
        dev=rb.mos_devices(source)[0]
        self.assertEqual(dev['path'],'xsomething.xm1');self.assertEqual(dev['nodes'],['vref','xsomething.gate','0','0'])

    def test_nested_model_hash_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            d=Path(directory);(d/'a.spice').write_text(".lib typical\n.include 'b.spice'\n.endl\n")
            (d/'b.spice').write_text('.param a=1\n')
            self.assertEqual(set(rb.model_dependencies([d/'a.spice'])),{d/'a.spice',d/'b.spice'})

    def test_config_rejects_bad_inputs(self):
        for key,value in [('mc_samples',0),('noise_stop_Hz',.01),('recovery_observe_s',1e-6),('brownout_levels_V',[5.5])]:
            c=self.config();c[key]=value
            with self.assertRaises(ValueError,msg=key):rb.validate_config(c)


    def trim_config(self):
        return rb.load_config(HERE/'bandgap_config.json',rb.TRIM,'trim_nominal')[0]

    def trim_rows(self):
        return [[code,v,3.3,1.194,.708,25e-6,1e-10,0,0,0,0,1e-7,1e-6,1e-6]
                for v in (3.3,5.) for code in range(128)]

    def trim_parse(self,rows):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'table.txt'
            path.write_text(' '.join(rb.TRIM_FIELDS)+'\n'+'\n'.join(' '.join(map(str,row)) for row in rows)+'\n')
            return rb.trim_read_sweep(path,self.trim_config())

    def test_trim_nominal_bundle(self):
        c=self.trim_config();rb.validate_config(c)
        cases=list(rb.cases(c,rb.TRIM))
        self.assertEqual(c['_profile'],'trim_nominal')
        self.assertEqual(len(cases),1)
        self.assertEqual(cases[0]['dc_operating_points'],256)
        self.assertEqual(cases[0]['startup_runs'],2)
        c['trim_startup']=False
        self.assertEqual(next(rb.cases(c,rb.TRIM))['startup_runs'],0)

    def test_trim_full_grid_and_default(self):
        c,_=rb.load_config(HERE/'bandgap_config.json',rb.TRIM,'full')
        rb.validate_config(c)
        cs=list(rb.cases(c,rb.TRIM))
        self.assertEqual(len(cs),405)
        self.assertEqual(len({x['case_id'] for x in cs}),405)
        self.assertEqual(sum(x['dc_operating_points'] for x in cs),362880)
        self.assertEqual(sum(x['calibration_dc_operating_points'] for x in cs),51840)
        self.assertEqual(sum(x['startup_runs'] for x in cs),2835)
        self.assertEqual({x['temperature_C'] for x in cs},{-40,25,125})
        self.assertTrue(all(x['calibration_temperature_C']==25 and x['calibration_supply_V']==3.3 for x in cs))
        self.assertEqual(rb.load_config(HERE/'bandgap_config.json',rb.TRIM)[0]['_profile'],'full')
        self.assertFalse(rb.summarize_trim([])['full_PVT_qualified'])

    def test_trim_smoke_still_calibrates_at_3p3(self):
        c=self.config(rb.TRIM,'smoke');rb.validate_config(c)
        case=next(rb.cases(c,rb.TRIM))
        self.assertEqual(case['supply_voltages_V'],[5.0])
        self.assertEqual(case['calibration_dc_operating_points'],128)
        self.assertEqual(case['startup_runs'],1)

    def test_trim_full_supply_table_and_stress_groups(self):
        c=self.config(rb.TRIM,'full')
        rows=[dict(zip(rb.TRIM_FIELDS,r)) for r in self.trim_rows()[:128]]
        data=[dict(r,avdd_V=v,range=rb.trim_supply_range(v,c),self_sustaining_op=True,
                   bits_b6_to_b0=format(r['code'],'07b'))
              for v in c['supply_voltages_V'] for r in rows]
        m=rb.trim_dc_metrics(data,c,70)
        self.assertEqual(len(m['fixed_code_results']),7)
        self.assertEqual(sum(p['range']=='stress' for p in m['fixed_code_results']),2)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'sweep.txt'
            path.write_text(' '.join(rb.TRIM_FIELDS)+'\n'+''.join(
                ' '.join(str(r[k]) for k in rb.TRIM_FIELDS)+'\n' for r in data))
            self.assertEqual(len(rb.trim_read_sweep(path,c)),896)
            path.write_text(path.read_text().rsplit('\n',2)[0]+'\n')
            with self.assertRaises(ValueError):rb.trim_read_sweep(path,c)

    def test_trim_temperature_does_not_recalibrate_code(self):
        c=self.trim_config();c.update(temperatures_C=[-40],trim_startup=False)
        case=next(rb.cases(c,rb.TRIM))
        source=('.lib /pdk/mos typical\n.lib /pdk/bjt bjt_typical\n.lib /pdk/res res_typical\n'
                '.param mim_corner_2p0fF=1\n.temp 25\nVDD avdd 0 5\n')
        decks=[]
        def simulate(deck,config,ngspice,marker):
            text=deck.read_text();decks.append(text)
            optimum=70 if '.temp 25\n' in text else 100
            rows=[]
            for v in config['supply_voltages_V']:
                for code in range(128):
                    err=code-optimum
                    rows.append([code,v,3.3,1.194+err*.001,.708,25e-6,1e-10,err,0,0,0,1e-7,1e-6,1e-6])
            (deck.parent/'trim_sweep.txt').write_text(' '.join(rb.TRIM_FIELDS)+'\n'+
                ''.join(' '.join(map(str,row))+'\n' for row in rows))
            return []
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(rb,'trim_simulate',side_effect=simulate):
            result=rb.run_trim_case(case,root=Path(tmp),source=source,config=c,
                                    fingerprint='test',ngspice='unused',retry_failed=False)
        self.assertEqual(result['status'],'complete',result)
        m=result['metrics']
        self.assertEqual(m['calibration_code'],70)
        self.assertEqual(m['dc']['3.3']['best_code'],100)
        self.assertEqual([r['code'] for r in m['fixed_code_results']],[70,70])
        self.assertFalse(m['fixed_code_accuracy_pass'])
        self.assertIsNone(m['startup_pass'])
        self.assertEqual(len(decks),2)
        self.assertIn('.temp -40\n',decks[0]);self.assertIn('foreach supply 3.3\n',decks[1])

    def test_trim_unhealthy_evaluation_point_is_not_execution_failure(self):
        rows=self.trim_parse(self.trim_rows())
        for row in rows:
            if row['avdd_V']==5.:row['self_sustaining_op']=False
        m=rb.trim_dc_metrics(rows,self.trim_config(),70)
        self.assertIsNone(m['dc']['5.0']['best_code'])
        self.assertTrue(m['fixed_code_accuracy_pass'])
        self.assertFalse(m['fixed_code_self_sustaining_pass'])

    def test_trim_summary_preserves_partial_data_without_passing_unresolved(self):
        c=self.trim_config()
        case=next(rb.cases(c,rb.TRIM))
        m=rb.trim_dc_metrics(self.trim_parse(self.trim_rows()),c,70)
        m.update(startup_pass=False,trim_gate_screen_pass=False,startup=[
            dict(avdd_V=3.3,range='nominal',status='COMPLETE',events=[dict(status='PASS')]),
            dict(avdd_V=5.,range='nominal',status='UNRESOLVED')])
        result=dict(case,status='failed',metrics=m)
        s=rb.summarize_trim([result])
        self.assertEqual(s['simulation_complete'],0)
        self.assertEqual(s['execution_failed_or_timed_out'],1)
        self.assertEqual(s['completed_DC_points'],256)
        self.assertEqual(s['completed_startup_runs'],1)
        self.assertEqual(s['unresolved_startup_runs'],1)
        self.assertEqual(s['nominal']['startup_pass_count'],1)
        self.assertEqual(s['startup_pass_count'],0)

    def test_trim_timing_constraints(self):
        for key,value in [('trim_dvdd_V',5),('trim_transient_max_step_s',2e-6),
                          ('trim_tail_window_s',1e-6),('trim_startup_off_limit_A',float('nan'))]:
            c=self.trim_config();c[key]=value
            with self.assertRaises(ValueError,msg=key):rb.validate_config(c)

    def test_trim_bit_codes(self):
        for code in range(128):
            self.assertEqual(sum(v<<i for i,v in enumerate(rb.trim_bits(code))),code)
        self.assertEqual(rb.trim_bits(70),[0,1,1,0,0,0,1])
        for code in (-1,128,3.5,True):
            with self.assertRaises(ValueError):rb.trim_bits(code)

    def test_trim_source_pins(self):
        source='x1 avdd 0 vref b0 b1 b2 b3 b4 b5 b6 0 dvdd Bandgap_Core_Res\n'
        source+='.subckt Bandgap_Core_Res '+rb.TRIM_PORTS+'\n.ends Bandgap_Core_Res\n'
        source+='VDD avdd 0 3.3\nVDVDD dvdd 0 3.3\n'
        source+=''.join(f'VBIT{i} b{i} 0 0\n' for i in range(7))
        rb.validate_trim_source(source)
        with self.assertRaises(ValueError):rb.validate_trim_source(source.replace('b0 b1','b1 b0',1))
        with self.assertRaises(ValueError):rb.validate_trim_source(source.replace('Bandgap_Core_Res','Bandgap_Core'))

    def test_trim_full_precision_and_digital_drive(self):
        c=self.trim_config();control=rb.trim_sweep_control(c)
        self.assertIn('wrdata ',control);self.assertIn('setscale code_value',control)
        self.assertNotIn('echo $code',control)
        source='VDD avdd 0 5\nVDVDD dvdd 0 3.3\n'+''.join(f'VBIT{i} b{i} 0 0\n' for i in range(7))
        for supply in (3.3,5):
            deck,_=rb.trim_startup_deck(source,supply,70,c)
            self.assertIn('11u 3.3 6m 3.3',deck)
            self.assertIn('EBIT1 b1 0 dvdd 0 1',deck)
            self.assertIn('EBIT0 b0 0 dvdd 0 0',deck)
            self.assertIn('tran 1e-07 6m 0 1e-07',deck)

    def test_trim_complete_sweep(self):
        rows=self.trim_parse(self.trim_rows())
        self.assertEqual(len(rows),256)
        self.assertTrue(all(r['self_sustaining_op'] for r in rows))

    def test_trim_incomplete_and_invalid_sweeps(self):
        for fault in ('missing','duplicate','nan','fraction','digital'):
            rows=self.trim_rows()
            if fault=='missing':rows.pop()
            elif fault=='duplicate':rows[1]=rows[0]
            elif fault=='nan':rows[0][3]=float('nan')
            elif fault=='fraction':rows[0][0]=.5
            else:rows[0][2]=5
            with self.assertRaises(ValueError,msg=fault):self.trim_parse(rows)

    def test_trim_assistance_not_mistaken_for_pass(self):
        rows=self.trim_rows();rows[0][8]=2e-9
        self.assertFalse(self.trim_parse(rows)[0]['self_sustaining_op'])

    def test_trim_code_is_held_across_supplies(self):
        rows=self.trim_rows()
        for row in rows:
            optimum=70 if row[1]==3.3 else 71
            row[7]=row[0]-optimum;row[3]=1.194+row[7]*1e-3
        m=rb.trim_dc_metrics(self.trim_parse(rows),self.trim_config())
        self.assertEqual(m['calibration_code'],70)
        self.assertEqual(m['dc']['5.0']['best_code'],71)
        self.assertEqual([r['code'] for r in m['fixed_code_results']],[70,70])

    def trim_trace(self,late_failure=False,incomplete=False):
        c=self.trim_config()
        _,cols=rb.trim_startup_deck('',3.3,70,c)
        times=[0,.000120,.000200,.000300,.0039,.004,.004501,.0046,.0047,.0059,.006]
        rows=[]
        for time in times:
            d={key:0. for key in cols}
            d.update(avdd=3.3,dvdd=3.3,vref=1.194,vq3=.708)
            d.update({dev:1e-6 for dev in rb.TRIM_IDS[3:]})
            if late_failure and time==.0059:d['vref']=1.
            rows.append([time]+[d[key] for key in cols])
        if incomplete:rows.pop()
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'trace.txt'
            path.write_text('time '+' '.join(cols)+'\n'+'\n'.join(' '.join(map(str,row)) for row in rows)+'\n')
            return rb.trim_startup_metrics(path,cols,c)[0]

    def test_trim_readiness_requires_staying_in_band(self):
        m=self.trim_trace()
        self.assertTrue(all(e['status']=='PASS' for e in m['events']))
        m=self.trim_trace(late_failure=True)
        self.assertEqual(m['events'][1]['status'],'FAIL')
        self.assertIsNone(m['events'][1]['settle_after_ramp_us'])
        with self.assertRaises(ValueError):self.trim_trace(incomplete=True)

    def test_trim_error_detector(self):
        for message in ('Error: no such vector vr','doAnalyses: TRAN: Timestep too small','simulation aborted'):
            self.assertIsNotNone(rb.TRIM_ERRORS.search(message))
        self.assertIsNone(rb.TRIM_ERRORS.search('Dynamic gmin stepping completed'))

    def test_configure_all_ten_is_repeatable(self):
        import contextlib
        import io
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            for test in rb.TESTS:shutil.copyfile(HERE/(test+'.sch'),folder/(test+'.sch'))
            with contextlib.redirect_stdout(io.StringIO()):
                rb.configure(folder,folder/'netlists')
            first={p.name:p.read_text() for p in folder.glob('*.sch')}
            with contextlib.redirect_stdout(io.StringIO()):
                rb.configure(folder,folder/'netlists')
            self.assertEqual(first,{p.name:p.read_text() for p in folder.glob('*.sch')})
            trim=first[rb.TRIM+'.sch']
            self.assertIn('C {tcleval([file join [file dirname [xschem get schname]] Bandgap_Core_Res.sym])}',trim)
            self.assertIn('--test TB10_RESISTOR_TRIM',trim)
            self.assertIn('quit\n.endc',trim)
            self.assertNotIn('trim_testbench/',trim)

    def test_configure_repairs_legacy_symbols_and_keeps_them_portable(self):
        import contextlib
        import io
        import re
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'moved project with spaces';folder.mkdir()
            for test in rb.TESTS:
                text=(HERE/(test+'.sch')).read_text()
                # Model an older checkout, including an obsolete/wrong core alias.
                text,count=re.subn(r'C \{[^\n{}]*Bandgap_Core[^\n{}]*\}',
                                   'C {/old/location/Bandgap_Core(1).sym}',text)
                self.assertEqual(count,1,test)
                (folder/(test+'.sch')).write_text(text)
            with contextlib.redirect_stdout(io.StringIO()):
                rb.configure(folder,folder/'netlists')
            for test in rb.TESTS:
                core=('Bandgap_Core_Res' if test==rb.TRIM else
                      'Bandgap_Core_LoopProbe' if test==rb.LG else 'Bandgap_Core')
                reference='C {tcleval([file join [file dirname [xschem get schname]] '+core+'.sym])}'
                self.assertIn(reference,(folder/(test+'.sch')).read_text(),test)
                self.assertIn(reference,(HERE/(test+'.sch')).read_text(),test)

if __name__=='__main__':unittest.main(verbosity=2)
