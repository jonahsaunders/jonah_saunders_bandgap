#!/usr/bin/env python3
"""Software checks only; no ngspice/PDK or electrical signoff implied."""
import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
import run_bandgap as rb

HERE=Path(__file__).resolve().parent

class SuiteChecks(unittest.TestCase):
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
        return rb.load_config(HERE/'bandgap_config.json',rb.TRIM)[0]

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

    def test_trim_does_not_claim_full_pvt(self):
        c,_=rb.load_config(HERE/'bandgap_config.json',rb.TRIM,'full')
        with self.assertRaisesRegex(ValueError,'TT/25'):
            rb.validate_config(c)

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
            self.assertIn(str(folder/'Bandgap_Core_Res.sym'),trim)
            self.assertIn('--test TB10_RESISTOR_TRIM',trim)
            self.assertIn('quit\n.endc',trim)
            self.assertNotIn('trim_testbench/',trim)

if __name__=='__main__':unittest.main(verbosity=2)
