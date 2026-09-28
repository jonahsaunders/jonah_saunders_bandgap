"""Render review charts from saved summary.json; never invoke SPICE."""
from pathlib import Path
import json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

root=Path(__file__).resolve().parent
data=json.loads((root/'summary.json').read_text())['derived']
BLUE='#176B9B'; ORANGE='#BC5928'; GRAY='#A6B2BC'; RED='#A64142'; GREEN='#267A61'
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,
                     'axes.spines.right':False,'axes.labelcolor':'#253448','text.color':'#253448',
                     'xtick.color':'#546273','ytick.color':'#546273','axes.titleweight':'bold'})

def create(title,count=1):
    fig,axes=plt.subplots(1,count,figsize=(10.4,4.25),squeeze=False)
    fig.suptitle(title,x=.09,ha='left',fontsize=15,fontweight='bold')
    fig.subplots_adjust(left=.09,right=.97,bottom=.23,top=.78,wspace=.35)
    for ax in axes[0]:
        ax.grid(axis='y',color='#E4E8EC',lw=.7);ax.set_axisbelow(True)
    return fig,axes[0]

def finish(fig,test,note):
    fig.text(.09,.045,note,fontsize=9,color='#546273',va='bottom')
    fig.savefig(root/f'{test}.png',dpi=160,facecolor='white')
    plt.close(fig)

def values(stat):return [stat['minimum'],stat['median'],stat['maximum']]
def bars(ax,labels,vals,ylabel,colors=None):
    rect=ax.bar(labels,vals,color=colors or BLUE,width=.58)
    ax.set_ylabel(ylabel)
    upper=max(vals)*1.25 if max(vals)>0 else 1
    ax.set_ylim(0,upper)
    for r,v in zip(rect,vals):
        label=f'{v:,.0f}' if float(v).is_integer() else f'{v:.3g}'
        ax.text(r.get_x()+r.get_width()/2,v+upper*.025,label,ha='center',fontsize=10)

fig,(ax,)=create('TB01 · PSRR across nominal supplies')
keys=['psrr_1hz_db','psrr_1khz_db','psrr_1mhz_db','psrr_min_1hz_1mhz_db']
x=np.arange(4); stats=[data['TB01'][k] for k in keys]
mid=np.array([s['median'] for s in stats]);low=np.array([s['minimum'] for s in stats]);high=np.array([s['maximum'] for s in stats])
ax.errorbar(x,mid,yerr=[mid-low,high-mid],fmt='o',capsize=8,color=BLUE,lw=2,markersize=7,label='Median and min–max range')
ax.set_xticks(x,['1 Hz','1 kHz','1 MHz','Worst in 1 Hz–1 MHz'])
ax.set(ylabel='PSRR (dB)',ylim=(40,91),xlim=(-.45,3.45))
ax.axhline(60,color=ORANGE,ls='--',lw=1,label='Original full-band requirement: 60 dB')
ax.legend(frameon=False,fontsize=9,loc='upper right')
finish(fig,'TB01','2,025 nominal cases; untrimmed core. AC values alone do not establish DC accuracy or trimmed-core performance.')

fig,(ax,)=create('TB02 · Reference change over 3.3–5.0 V')
bars(ax,['Minimum','Median','Maximum'],values(data['TB02']['nominal_span_percent']),'Total VREF change (%)')
ax.axhline(.1,color=ORANGE,ls='--',lw=1.3);ax.set_ylim(0,.12)
ax.text(2.45,.102,'0.1% budget',ha='right',color=ORANGE,fontsize=9)
finish(fig,'TB02','405 completed sweeps; untrimmed core. Percentages use the report’s 1.194 V normalization.')

fig,(ax,)=create('TB03 · Startup and restart outcomes at nominal supplies')
a=data['TB03'];parts=[[a['startup_ready'],a['restart_ready']],[a['valid_references']-a['startup_ready'],a['valid_references']-a['restart_ready']],
    [a['accuracy_invalid']]*2,[a['nominal_unresolved']]*2]
left=np.zeros(2)
for vals,label,color in zip(parts,['Ready','Timing miss with valid reference','Settled reference outside band','Unresolved execution'],[BLUE,ORANGE,GRAY,RED]):
    ax.barh(['Startup','Restart'],vals,left=left,label=label,color=color,height=.5)
    for i,v in enumerate(vals):
        if v>90:ax.text(left[i]+v/2,i,f'{v:,}',ha='center',va='center',color='white' if color==BLUE else '#253448')
    left+=np.array(vals)
ax.set(xlabel='Planned nominal-supply cases',xlim=(0,2100));ax.invert_yaxis()
ax.legend(frameon=False,fontsize=8,ncol=2,loc='lower center',bbox_to_anchor=(.5,1.05))
finish(fig,'TB03','7 startup timing misses; 0 restart timing misses among 1,091 valid-reference cases. 40 nominal executions unresolved.')

fig,(ax,)=create('TB04 · Untrimmed temperature coefficient')
a=data['TB04']
bars(ax,['Typical\n3.3 V','Typical\n5 V','Nominal-grid\nmedian','Nominal-grid\nworst'],
     [a['typical']['3.3']['TC_box_ppm_per_C'],a['typical']['5']['TC_box_ppm_per_C'],a['tc_box_ppm_C']['median'],a['tc_box_ppm_C']['maximum']],
     'Box TC (ppm/°C)')
for label in ax.texts[:2]:
    label.set_y(3.5);label.set_color('white')
ax.axhline(10,color=ORANGE,ls='--',lw=1);ax.text(3.45,11,'10 ppm/°C target',ha='right',color=ORANGE,fontsize=9)
finish(fig,'TB04','675 nominal-supply sweeps; −40 to 125°C in 1°C steps. Box TC uses the mean voltage of each sweep.')

fig,axes=create('TB05 · Repaired untrimmed loop-probe core',2)
a=data['TB05'];bars(axes[0],['AC measured','DC gate\nrejected'],[a['nominal_completed'],a['nominal_unresolved']],'Nominal cases',[BLUE,ORANGE])
s=a['main_pm_deg'];axes[1].errorbar([0],[s['median']],yerr=[[s['median']-s['minimum']],[s['maximum']-s['median']]],fmt='o',capsize=12,color=BLUE,lw=2)
axes[1].set(xticks=[0],xticklabels=['MAIN loop'],ylabel='Conditional phase margin (°)',ylim=(87,90),xlim=(-.6,.6))
axes[1].text(0,89.4,f"{s['minimum']:.2f}–{s['maximum']:.2f}°",ha='center',fontsize=12)
finish(fig,'TB05','Latest repaired-core rerun. BIAS has no unity crossing; no conventional phase margin or whole-network signoff.')

fig,axes=create('TB06 · Monte Carlo at 25°C / 3.3 V before trim',3)
for ax,mode in zip(axes,['global','mismatch','combined']):
    d=data['TB06']['one_condition_25C_3p3V'][mode]
    ax.hist(d['values_V'],bins=np.linspace(1.08,1.34,34),color=BLUE,alpha=.85)
    ax.axvspan(1.194*.995,1.194*1.005,color=GREEN,alpha=.18)
    ax.set(title=f"{mode.capitalize()}\nσ = {d['sample_sigma_mV']:.2f} mV",xlabel='VREF (V)',xlim=(1.08,1.34),ylim=(0,105))
    ax.text(.97,.9,f"{d['accuracy_pass']}/100 in band",transform=ax.transAxes,ha='right',fontsize=9)
axes[0].set_ylabel('Samples')
finish(fig,'TB06','100 seeds per mode at this one condition. Shading: original 1.194 V ±0.5% band. These are untrimmed samples.')

fig,axes=create('TB07 · Integrated output noise',2)
for ax,key,title in zip(axes,['noise_low_band_uV','noise_wide_band_uV'],['0.1–10 Hz','1 Hz–1 MHz']):
    bars(ax,['Min','Median','Max'],values(data['TB07'][key]),'Output noise (µV RMS)')
    ax.set_title(title)
axes[0].axhline(100,color=ORANGE,ls='--',lw=1);axes[0].set_ylim(0,120)
axes[0].text(2.4,103,'100 µV budget',ha='right',fontsize=9,color=ORANGE)
finish(fig,'TB07','2,025 nominal-supply cases; untrimmed core. The 100 µV goal applies to the 0.1–10 Hz band only.')

fig,axes=create('TB08 · Analog current and device-voltage screening',2)
a=data['TB08'];bars(axes[0],['Min','Median','Max'],values(a['analog_current_uA']),'Analog current (µA)')
axes[0].axhline(60,color=ORANGE,ls='--',lw=1);axes[0].set_ylim(0,75)
flagged=sum(a['flagged_devices'].values())
bars(axes[1],['No voltage\nflag','Voltage\nflag'],[a['nominal_completed']-flagged,flagged],'Nominal cases',[BLUE,ORANGE])
finish(fig,'TB08','Flagged device: XMSU_SENSE. Maximum terminal magnitude 5.003951 V vs a configured 5.000 V screen; not reliability signoff.')

fig,(ax,)=create('TB09 · Recovery misses with a valid DC reference')
a=data['TB09'];kinds=['ramp','brownout','cycles','step']
bars(ax,['Ramp','Brownout','Repeated\ninterruptions','Supply step'],[a['valid_miss_by_kind'][k] for k in kinds],
     'Nominal cases missing recovery',ORANGE)
finish(fig,'TB09','292 misses among 12,961 completed nominal cases with valid DC references. Offset-invalid cases and aborts excluded here.')

fig,axes=create('TB10 · Two completed DC studies with different calibration goals',2)
a=data['TB10_dc_screen'];b=data['TB10_dense_tc']
bars(axes[0],['In voltage\nband','Outside\nband'],[a['fixed_code_accuracy_pass'],a['fixed_code_points']-a['fixed_code_accuracy_pass']],
     'Held-code points',[BLUE,ORANGE]);axes[0].set_title('Voltage calibration: 1.194 V ±0.5%',fontsize=11)
bars(axes[1],['Best','Median','Worst'],[b['tc_min_ppm_C'],b['tc_median_ppm_C'],b['tc_max_ppm_C']],'Box TC (ppm/°C)')
axes[1].set_title('Minimum-drift calibration: near 1.18 V',fontsize=11)
axes[1].axhline(10,color=ORANGE,ls='--',lw=1);axes[1].set_ylim(0,12)
axes[1].text(2.4,10.3,'10 ppm/°C goal',ha='right',color=ORANGE,fontsize=9)
finish(fig,'TB10','45 process combinations, typical MIM, 3.3/5 V. Left: 3 temperatures. Right: 1°C steps. Neither study includes startup.')
print('Rendered 10 charts from the saved report-review data. No simulator was invoked.')
