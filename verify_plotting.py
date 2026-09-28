#!/usr/bin/env python3
"""Regression checks for plot aggregation and bounded large-sweep figures."""
import unittest
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import plot_bandgap as pb

class PlotChecks(unittest.TestCase):
    def tearDown(self):plt.close('all')

    def test_corner_reducer_direction(self):
        cases=[dict(temperature_C=25,vdd_V=3.3,metric=v) for v in (1.18,1.48)]
        for reducer,expected in [('min',1.18),('max',1.48)]:
            fig,ax=plt.subplots()
            pb.by_temperature(ax,cases,'vdd_V',lambda c:c['metric'],[25],reducer=reducer)
            self.assertEqual(list(ax.lines[0].get_ydata()),[expected])

    def test_startup_plot_uses_actual_largest_peak(self):
        cases=[]
        for i,peak in enumerate((1.18,1.48)):
            cases.append(dict(case_id=str(i),status='complete',temperature_C=25,vdd_V=3.3,
                metrics=dict(start_peak_v=peak,restart_peak_v=peak+.02,final_vref_v=1.194,
                             final_idd_ua=30,start_ready_300us=1,restart_ready_300us=1)))
        figs=pb.figures_tb03('TB03_STARTUP_RESTART',{},cases,{}, {})
        overshoot=next(f for f in figs if 'overshoot' in f.axes[0].get_title(loc='left'))
        self.assertEqual(list(overshoot.axes[0].lines[0].get_ydata()),[1.48])
        self.assertEqual(list(overshoot.axes[1].lines[0].get_ydata()),[1.50])

    def test_large_loop_sweep_has_bounded_pages_and_keeps_extremes(self):
        cases=[]
        for i in range(1600):
            loop=dict(phase_margin_deg=80+i*.001,minimum_sampled_abs_1_plus_L=.2+i*.001,
                      unity_crossings=[],curve_samples=[dict(frequency_Hz=f,gain_dB=g,phase_deg=p,real=r,imag=im)
                      for f,g,p,r,im in [(1,20,-90,0,-10),(100,0,-100,-.17,-.98),(1e6,-40,-180,-.01,0)]])
            cases.append(dict(case_id=f'case_{i:04}',status='complete',metrics=dict(
                loops=dict(main=loop,bias=dict(loop,phase_margin_deg=None)),op_vref_v=1.194,main_dc_error_v=0,bias_dc_error_v=0)))
        cases[1200]['metrics']['loops']['main']['phase_margin_deg']=30
        selected=pb.select_loop_cases(cases,'main')
        self.assertLessEqual(len(selected),12)
        self.assertIn(cases[1200],selected)
        figs=pb.figures_tb05('TB05_LOOP_STABILITY',{},cases,{}, {})
        for fig in figs:
            self.assertLessEqual(max(fig.get_size_inches()),12)
            for ax in fig.axes:self.assertLess(len(ax.get_yticklabels()),40)

if __name__=='__main__':unittest.main(verbosity=2)
