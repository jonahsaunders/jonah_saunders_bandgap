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
This is a DC calibration sweep, not a startup or reliability signoff.} 200 720 0 0 0.28 0.28 {}
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
C {code.sym} 900 650 0 0 {name=MODELS_AND_TEST only_toplevel=true
format="tcleval([read_data_nonewline [abs_sym_path trim_testbench/generated/manual_setup.spice]])"
value="Run python3 trim_testbench/run_trim.py --prepare-only before netlisting.\nGenerated setup resolves model and result paths for this checkout."}
