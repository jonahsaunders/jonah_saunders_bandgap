v {xschem version=3.4.8RC file_version=1.3}
G {}
K {}
V {}
S {}
F {}
E {}
T {TB04_TEMPERATURE: Temperature drift and accuracy} 220 50 0 0 0.5 0.5 {}
T {135 corner combinations x 7 supplies; -40 to 125 C in 1 C steps.} 220 90 0 0 0.27 0.27 {}
T {DUT: your Bandgap_Core.sym + Bandgap_Core.sch in this folder.
Output bank and OTA capacitor are already inside the core; no extra load added.} 220 120 0 0 0.27 0.27 {}
T {MODELS: nominal bootstrap and the existing MIM compatibility model.
TEST: invokes this test's resumable corner sweep using Python 3 and ngspice.
Run python3 run_bandgap.py --configure after extraction. Settings: bandgap_config.json.} 220 610 0 0 0.27 0.27 {}
T {Results: Configured output_directory / selected profile /
Each bench writes its own TBxx_UPLOAD_THIS.txt report.
The 3.0 V and 5.5 V cases remain separately labeled stress tests.} 220 700 0 0 0.27 0.27 {}
N 550 220 620 220 {lab=avdd}
N 550 240 680 240 {lab=vref}
N 550 260 620 260 {lab=GND}
N 620 260 620 300 {lab=GND}
N 900 180 900 210 {lab=avdd}
N 900 270 900 300 {lab=GND}
C {lab_pin.sym} 620 220 0 1 {name=p1 lab=avdd}
C {lab_pin.sym} 680 240 0 1 {name=p2 lab=vref}
C {gnd.sym} 620 300 0 0 {name=l1 lab=GND}
C {vsource.sym} 900 240 0 0 {name=VDD value="DC \{VDD_RUN\} AC 0" savecurrent=false}
C {lab_pin.sym} 900 180 0 0 {name=p3 lab=avdd}
C {gnd.sym} 900 300 0 0 {name=l2 lab=GND}
C {code.sym} 240 420 0 0 {name=MODELS only_toplevel=true value="* TB_PVT_MODELS_BEGIN
.include /foss/pdks/gf180mcuD/libs.tech/ngspice/design.ngspice
.lib /foss/pdks/gf180mcuD/libs.tech/ngspice/sm141064.ngspice typical
.lib /foss/pdks/gf180mcuD/libs.tech/ngspice/sm141064.ngspice bjt_typical
.lib /foss/pdks/gf180mcuD/libs.tech/ngspice/sm141064.ngspice res_typical
* GF180 2p0fF MIM fit, charge-form ngspice compatibility implementation.
* Derived from GlobalFoundries PDK Authors (2022), Apache-2.0:
* https://github.com/google/globalfoundries-pdk-libs-gf180mcu_fd_pr
* Same geometry, voltage/temperature coefficients, leakage and corner factors.
* Differential C(V)=C0*(1+a*V+b*V^2) is implemented as
* Q(V)=C0*(V+a*V^2/2+b*V^3/3), so dQ/dV exactly equals C(V).
* This avoids ngspice's poorly scaled unity-capacitor C-expression expansion.
* Do not also include mimcap_typical: it would redefine cap_mim_2f0fF.
.param mim_corner_2p0fF=1 mc_c_cox_2p0fF=0
.subckt cap_mim_2f0fF  1 2  c_length=l  c_width=w dtemp=0 par=1
.param gleak='9.51e-10/5*10000'
.param c_cox='1.99e-3*mim_corner_2p0fF'
.param c_capsw='2.383e-10*mim_corner_2p0fF'
.param c_vcr1='0+(c_width>5u||c_length>5u)*8.742e-6+(c_width<=5u||c_length<=5u)*(-81e-6)'
.param c_vcr2='0+(c_width>5u||c_length>5u)*9.188e-6+(c_width<=5u||c_length<=5u)*(16.7e-6)'

.param c_tnom=25
.param c_tc1=1.46e-5
.param c_tc2=-5.55e-8
.param c_AREA='c_length*c_width'
.param c_PERI='2*(c_length+c_width)'

.param c_c0='(c_cox*c_AREA+c_capsw*c_PERI)*(1+c_tc1*(temper +dtemp -c_tnom)+c_tc2*(temper+dtemp-c_tnom)*(temper+dtemp-c_tnom))'
*
c_cap 1 2 Q='c_c0*(v(1,2)+c_vcr1*v(1,2)*v(1,2)/2+c_vcr2*v(1,2)*v(1,2)*v(1,2)/3)*(1+mc_c_cox_2p0fF)'
r_leak 1 2 r='1/(gleak*c_AREA)' tc1=c_tc1 tc2=c_tc2 dtemp=dtemp
.ends cap_mim_2f0fF
* Bootstrap nominal process; runner selects each corner independently. Mismatch disabled. MIM compatibility model above is intentional.
.options tnom=25 numdgt=15 method=trap
.param sw_stat_global=0 sw_stat_mismatch=0 fnoicor=0
.param VDD_RUN=5
.temp 25
* TB_PVT_MODELS_END
"}
C {code.sym} 530 420 0 0 {name=TEST only_toplevel=true format="@value" value=".control
set noaskquit
echo BANDGAP_SINGLE_RUNNER_V9_TB04_TEMPERATURE
shell python3 \"/foss/designs/chipalooza-bandgap/Jonah_Saunders_Bandgap/run_bandgap.py\" --deck \"/headless/.xschem/simulations/TB04_TEMPERATURE.spice\" --test TB04_TEMPERATURE
echo RUNNER_RETURNED_CHECK_REPORT_AND_ERRORS
.endc
"}
C {/foss/designs/chipalooza-bandgap/Jonah_Saunders_Bandgap/Bandgap_Core.sym} 400 240 0 0 {name=x1}
