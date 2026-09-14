#!/usr/bin/env python3
"""TB08-only ground-vector fix for Bandgap_Test_Suite_9 (2026-09-06).

Place beside the ORIGINAL run_bandgap.py and bandgap_config.json.
Do not replace run_bandgap.py: keeping it intact preserves other benches' cache
fingerprints. The fixed runner accepts the original CLI arguments and defaults
to TB08_POWER_DEVICE_LIMITS. Its own hash is added to TB08's run fingerprint.

First run:
  python3 run_bandgap_tb08_fixed.py --deck /headless/.xschem/simulations/TB08_POWER_DEVICE_LIMITS.spice --profile smoke
Then:
  python3 run_bandgap_tb08_fixed.py --deck /headless/.xschem/simulations/TB08_POWER_DEVICE_LIMITS.spice --profile full

Optional Xschem launcher update (only the TB08 TEST block is modified):
  python3 run_bandgap_tb08_fixed.py --configure
Run the original path configuration first if the project has moved. Re-running
original run_bandgap.py --configure restores the original launcher; in that case
run this script's --configure again. A backup of the TB08 schematic is kept.

Cause: ngspice maps the GND alias to reference node 0, which is not a saved
voltage vector. Control expressions must never request v(gnd) or v(0).
The fix canonicalizes the reference aliases and uses v(node), -v(node), or a
zero-valued vector as appropriate. No circuit device or limit is changed.
"""
import hashlib
import importlib.util
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
TEST = 'TB08_POWER_DEVICE_LIMITS'


def ground_name(node):
    node = node.strip().lower()
    return '0' if node in ('0', 'gnd') else node


def voltage(a, b):
    a, b = ground_name(a), ground_name(b)
    if a == b:
        return '0*v(avdd)'  # retain the waveform shape, including GND-to-GND
    if b == '0':
        return 'v(' + a + ')'
    if a == '0':
        return '-v(' + b + ')'
    return 'v(' + a + ')-v(' + b + ')'


def configure():
    path = HERE / (TEST + '.sch')
    original = path.read_text()
    blocks = list(re.finditer(r'C \{code.sym\}[^\n]*\{name=TEST\b.*?\n"\}', original, re.S))
    if len(blocks) != 1:
        raise ValueError('Expected one TB08 TEST block; use the terminal command instead')
    match = blocks[0]
    block = match.group()
    if not re.search(r'--test\s+' + TEST + r'\b', block):
        raise ValueError('The TEST block does not launch TB08; no file was changed')
    if Path(__file__).name in block:
        print('TB08 already uses the ground-fixed runner.')
        return 0
    if block.count('run_bandgap.py') != 1:
        raise ValueError('Expected one run_bandgap.py launcher; use the terminal command instead')
    updated = block.replace('run_bandgap.py', Path(__file__).name, 1)
    backup = path.with_name(path.name + '.before_ground_fix')
    if not backup.exists():
        backup.write_text(original)
    temp = path.with_name(path.name + '.ground_fix_tmp')
    temp.write_text(original[:match.start()] + updated + original[match.end():])
    temp.replace(path)
    print('Updated only ' + path.name + '. Regenerate its netlist before simulating.')
    print('Other testbenches and run_bandgap.py are unchanged.')
    return 0


def load_fixed_runner():
    path = HERE / 'run_bandgap.py'
    if not path.is_file():
        raise FileNotFoundError('Place this file beside the original run_bandgap.py and bandgap_config.json')
    spec = importlib.util.spec_from_file_location('_bandgap_tb08_base', path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    original_devices, original_load = runner.mos_devices, runner.load_config
    def devices(source):
        result = original_devices(source)
        for dev in result:
            dev['nodes'] = [ground_name(n) for n in dev['nodes']]
        return result
    patch_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    def config(path, test, profile=None):
        if test != TEST:
            raise ValueError('This fixed runner is only for TB08; use run_bandgap.py for other tests')
        settings, templates = original_load(path, test, profile)
        settings['_tb08_ground_fix_sha256'] = patch_hash
        return settings, templates
    runner.mos_devices = devices
    runner.voltage = voltage
    runner.load_config = config
    return runner


def main():
    if '--configure' in sys.argv[1:]:
        if sys.argv[1:] != ['--configure']:
            raise ValueError('Use --configure by itself; it only changes the existing TB08 launcher')
        return configure()
    if not any(arg == '--test' or arg.startswith('--test=') for arg in sys.argv[1:]):
        sys.argv += ['--test', TEST]
    runner = load_fixed_runner()
    print('TB08 ground fix active. Original runner and other testbench caches are preserved.', flush=True)
    return runner.main()


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('Interrupted. Completed matching cases remain cached.', file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print('TB08_FIXED_RUNNER_ERROR: ' + str(exc), file=sys.stderr)
        sys.exit(1)
