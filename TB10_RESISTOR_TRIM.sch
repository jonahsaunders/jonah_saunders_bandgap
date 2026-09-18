v {xschem version=3.4.8RC file_version=1.3}
G {}
K {}
V {}
S {}
F {}
E {}
T {TB10: 7-bit resistor-trim sweep} 200 20 0 0 0.5 0.5 {}
T {TT / 25 C: all 128 codes at AVDD=3.3 V and 5 V; DVDD stays 3.3 V.
Bit 1 bypasses its resistor. Bit 0 includes it. Target VREF=1.194 V.} 200 70 0 0 0.28 0.28 {}
T {No extra output load. Both grounds are connected to 0 in this bench.
TB10 runner: DC calibration plus selected-code startup/restart. Not reliability signoff.} 200 720 0 0 0.28 0.28 {}
C {Bandgap_Core_Res.sym} 500 400 0 0 {name=x1}
C {lab_pin.sym} 340 220 0 0 {name=p0 lab=avdd}
C {lab_pin.sym} 340 580 0 0 {name=p1 lab=0}
C {lab_pin.sym} 660 400 0 0 {name=p2 lab=vref}
C {lab_pin.sym} 580 180 0 0 {name=p3 lab=dvdd}
C {lab_pin.sym} 580 620 0 0 {name=p4 lab=0}
C {lab_pin.sym} 340 300 0 0 {name=p10 lab=b0}
C {lab_pin.sym} 340 340 0 0 {name=p11 lab=b1}
C {lab_pin.sym} 340 380 0 0 {name=p12 lab=b2}
C {lab_pin.sym} 340 420 0 0 {name=p13 lab=b3}
C {lab_pin.sym} 340 460 0 0 {name=p14 lab=b4}
C {lab_pin.sym} 340 500 0 0 {name=p15 lab=b5}
C {lab_pin.sym} 340 540 0 0 {name=p16 lab=b6}
C {vsource.sym} 900 220 0 0 {name=VDD value=3.3 savecurrent=false}
N 900 160 900 190 {lab=avdd}
N 900 250 900 280 {lab=0}
C {gnd.sym} 900 280 0 0 {name=g0 lab=0}
C {lab_pin.sym} 900 160 0 0 {name=p30 lab=avdd}
C {vsource.sym} 1120 220 0 0 {name=VDVDD value=3.3 savecurrent=false}
N 1120 160 1120 190 {lab=dvdd}
N 1120 250 1120 280 {lab=0}
C {gnd.sym} 1120 280 0 0 {name=g1 lab=0}
C {lab_pin.sym} 1120 160 0 0 {name=p31 lab=dvdd}
C {vsource.sym} 900 480 0 0 {name=VBIT0 value=0 savecurrent=false}
N 900 420 900 450 {lab=b0}
N 900 510 900 540 {lab=0}
C {gnd.sym} 900 540 0 0 {name=g2 lab=0}
C {lab_pin.sym} 900 420 0 0 {name=p32 lab=b0}
C {vsource.sym} 1040 480 0 0 {name=VBIT1 value=0 savecurrent=false}
N 1040 420 1040 450 {lab=b1}
N 1040 510 1040 540 {lab=0}
C {gnd.sym} 1040 540 0 0 {name=g3 lab=0}
C {lab_pin.sym} 1040 420 0 0 {name=p33 lab=b1}
C {vsource.sym} 1180 480 0 0 {name=VBIT2 value=0 savecurrent=false}
N 1180 420 1180 450 {lab=b2}
N 1180 510 1180 540 {lab=0}
C {gnd.sym} 1180 540 0 0 {name=g4 lab=0}
C {lab_pin.sym} 1180 420 0 0 {name=p34 lab=b2}
C {vsource.sym} 1320 480 0 0 {name=VBIT3 value=0 savecurrent=false}
N 1320 420 1320 450 {lab=b3}
N 1320 510 1320 540 {lab=0}
C {gnd.sym} 1320 540 0 0 {name=g5 lab=0}
C {lab_pin.sym} 1320 420 0 0 {name=p35 lab=b3}
C {vsource.sym} 1460 480 0 0 {name=VBIT4 value=0 savecurrent=false}
N 1460 420 1460 450 {lab=b4}
N 1460 510 1460 540 {lab=0}
C {gnd.sym} 1460 540 0 0 {name=g6 lab=0}
C {lab_pin.sym} 1460 420 0 0 {name=p36 lab=b4}
C {vsource.sym} 1600 480 0 0 {name=VBIT5 value=0 savecurrent=false}
N 1600 420 1600 450 {lab=b5}
N 1600 510 1600 540 {lab=0}
C {gnd.sym} 1600 540 0 0 {name=g7 lab=0}
C {lab_pin.sym} 1600 420 0 0 {name=p37 lab=b5}
C {vsource.sym} 1740 480 0 0 {name=VBIT6 value=0 savecurrent=false}
N 1740 420 1740 450 {lab=b6}
N 1740 510 1740 540 {lab=0}
C {gnd.sym} 1740 540 0 0 {name=g8 lab=0}
C {lab_pin.sym} 1740 420 0 0 {name=p38 lab=b6}
C {code.sym} 900 650 0 0 {name=MODELS only_toplevel=true value="* TB_PVT_MODELS_BEGIN
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
.options tnom=25 numdgt=15 method=gear maxord=2 reltol=1e-5 vntol=1e-7 abstol=1e-13 itl4=200
.param sw_stat_global=0 sw_stat_mismatch=0 fnoicor=0
.param VDD_RUN=5
.temp 25
* TB_PVT_MODELS_END
"}
C {code.sym} 530 420 0 0 {name=TEST only_toplevel=true format="@value" value=".control
set noaskquit
echo Run run_bandgap.py --configure before simulating from Xschem.
shell python3 run_bandgap.py --deck TB10_RESISTOR_TRIM.spice --test TB10_RESISTOR_TRIM
echo RUNNER_RETURNED_CHECK_REPORT_AND_ERRORS
quit
.endc
"}
