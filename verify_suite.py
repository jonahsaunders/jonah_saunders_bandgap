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

    def test_one_json_and_nine_controls(self):
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

if __name__=='__main__':unittest.main(verbosity=2)
