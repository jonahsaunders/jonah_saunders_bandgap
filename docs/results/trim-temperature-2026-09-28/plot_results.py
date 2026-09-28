"""Rebuild the published chart from its checked-in selected-code temperature data.

Usage: python3 docs/results/trim-temperature-2026-09-28/plot_results.py
Requires Matplotlib. Does not invoke the simulator or change testbench settings.
"""
from pathlib import Path
from collections import defaultdict
import csv
import statistics
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

root = Path(__file__).resolve().parent
with (root / 'selected_curves.csv').open(newline='') as stream:
    rows = list(csv.DictReader(stream))
groups = defaultdict(list)
for row in rows:
    key = tuple(row[k] for k in ('mos', 'bjt', 'res', 'mim', 'code'))
    groups[key, float(row['avdd_V'])].append(row)
curves = {}
for (key, supply), data in groups.items():
    data.sort(key=lambda row: float(row['temperature_C']))
    temperatures = [float(row['temperature_C']) for row in data]
    values = [float(row['vref_V']) for row in data]
    assert temperatures == list(range(-40, 126))
    tc = (max(values)-min(values))/statistics.mean(values)/165*1e6
    curves[key, supply] = (temperatures, values, tc)
corners = sorted({key for key, supply in curves})
assert len(corners) == 45 and len(curves) == 90 and len(rows) == 14940
worst_tc = {key: max(curves[key, supply][2] for supply in (3.3, 5.0)) for key in corners}
worst = max(corners, key=lambda key: worst_tc[key])
nominal = next(key for key in corners if key[:3] == ('typical','bjt_typical','res_typical'))
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,
                     'axes.labelcolor':'#253448','text.color':'#253448','xtick.color':'#546273','ytick.color':'#546273'})
fig, axes = plt.subplots(1,2,figsize=(11.8,4.7),gridspec_kw={'width_ratios':[1.5,1]})
for key in corners:
    for supply in (3.3, 5.0):
        temperatures, values, _ = curves[key, supply]
        shift = [(value-values[65])*1e6 for value in values]
        special = key in (nominal, worst)
        color = '#156DAD' if key == nominal else '#B85120' if key == worst else '#7F9AA5'
        label = ('Typical process' if key == nominal else 'Worst TC process') if special and supply == 3.3 else None
        axes[0].plot(temperatures, shift, color=color, lw=1.8 if special else .75,
                     alpha=1 if special else .22, ls='-' if supply == 3.3 else '--',
                     label=label, zorder=3 if special else 1)
axes[0].axhline(0,color='#8C98A6',lw=.6,zorder=0)
axes[0].set(xlabel='Temperature (°C)',ylabel='Change from the value at 25°C (µV)',xlim=(-40,125),
            title='Temperature drift after selecting one trim code')
axes[0].set_xticks([-40,0,25,75,125])
axes[0].legend(frameon=False,loc='upper left',fontsize=9)
axes[1].scatter([curves[key,3.3][1][65] for key in corners], [worst_tc[key] for key in corners],
                s=34,color='#7F9AA5',alpha=.75,edgecolors='none')
for key,color in [(nominal,'#156DAD'),(worst,'#B85120')]:
    axes[1].scatter([curves[key,3.3][1][65]],[worst_tc[key]],s=60,color=color,zorder=4)
axes[1].set(xlabel='Output at 25°C, 3.3 V supply (V)',ylabel='Worst of the two supplies (ppm/°C)',
            title='Output voltage is allowed to vary',ylim=(0,6))
axes[1].set_xticks([1.175,1.180,1.185,1.190])
for ax in axes:
    ax.grid(axis='y',color='#E4E8EC',lw=.7)
    ax.set_axisbelow(True)
fig.suptitle('Trimming for minimum temperature drift',fontsize=17,fontweight='bold',x=.075,ha='left')
fig.text(.075,.90,'45 process combinations · −40 to 125°C in 1°C steps · one code held across both supplies',fontsize=10)
fig.text(.075,.025,'Solid: 3.3 V supply   Dashed: 5 V supply   |   Typical MIM; mismatch and extracted layout not included.',fontsize=9,color='#546273')
fig.subplots_adjust(left=.075,right=.98,bottom=.17,top=.79,wspace=.32)
fig.savefig(root/'temperature_drift_after_trim.png',dpi=180,facecolor='white')
plt.close(fig)
print(f'Chart rebuilt from {len(rows):,} points; typical {worst_tc[nominal]:.2f}, worst {worst_tc[worst]:.2f} ppm/°C.')
