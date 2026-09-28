#!/usr/bin/env python3
"""Check portable core lookup with Xschem and configured GF180 symbol libraries.

Only generates netlists in a temporary directory; never runs simulations or
changes the source project. Run from the same environment used for Xschem.
"""
import contextlib
import difflib
import io
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile

import run_bandgap as rb


HERE = Path(__file__).resolve().parent
CORE_REFERENCE = re.compile(r'C \{[^\n{}]*Bandgap_Core[^\n{}]*\}')


def core_name(test):
    return ('Bandgap_Core_Res' if test == rb.TRIM else
            'Bandgap_Core_LoopProbe' if test == rb.LG else 'Bandgap_Core')


def circuit_text(deck):
    # Source-path comments and Python launchers do not affect the DUT circuit.
    text = re.sub(r'^\s*\.control\b.*?^\s*\.endc\b[^\n]*', '', deck,
                  flags=re.M | re.S | re.I)
    return '\n'.join(line.strip() for line in text.splitlines()
                     if line.strip() and not line.lstrip().startswith('*'))


def core_statements(deck, name):
    """Keep device parameters and connectivity, including continuation lines."""
    deck = re.sub(r'\n\s*\+\s*', ' ', deck)
    active = False
    ports = None
    body = {}
    for line in deck.splitlines():
        tokens = line.lower().split()
        if not tokens or tokens[0].startswith('*'):
            continue
        if tokens[0] == '.subckt':
            active = tokens[1] == name.lower()
            if active:
                if ports is not None:
                    raise AssertionError(f'Duplicate subcircuit {name}')
                ports = tokens[2:]
        elif tokens[0] == '.ends':
            active = False
        elif active:
            if tokens[0] in body:
                raise AssertionError(f'Duplicate statement {tokens[0]} in {name}')
            body[tokens[0]] = tokens
    if ports is None or not body:
        raise AssertionError(f'Missing or empty subcircuit {name}')
    return ports, body


def verify_loop_equivalence(core_deck, probe_deck):
    """The two gate cuts must be the only differences from the current core."""
    ports, core = core_statements(core_deck, 'Bandgap_Core')
    probe_ports, probe = core_statements(probe_deck, 'Bandgap_Core_LoopProbe')
    if ports != ['avdd', 'vref', 'avss'] or probe_ports != ports + [
            'vgn2', 'lg_main_f', 'vbn_i', 'lg_bias_f']:
        raise AssertionError('Core/probe port order changed')
    for gate, device in [('lg_main_f', 'xm3'), ('lg_bias_f', 'xn2')]:
        # An f port connected elsewhere can silently change the measured loop.
        uses = [(name, i) for name, tokens in probe.items()
                for i, token in enumerate(tokens) if token == gate]
        if uses != [(device, 2)]:
            raise AssertionError(f'{gate} must connect only to {device} gate: {uses}')
    if 'vgn2' not in probe.get('xc1', [])[1:3]:
        raise AssertionError('C1 must remain on MAIN e (vgn2)')
    close = {'lg_main_f': 'vgn2', 'lg_bias_f': 'vbn_i'}
    closed = {name: [close.get(t, t) for t in tokens] for name, tokens in probe.items()}
    if closed != core:
        changed = sorted(name for name in set(core) | set(closed)
                         if core.get(name) != closed.get(name))
        raise AssertionError('Closed loop-probe differs from Bandgap_Core: ' + ', '.join(changed))
    return len(core)


def netlist(project, output, cwd, test, launcher_paths=None):
    output.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ['xschem', '-n', '-x', '-q', '-r', '-s', '-o', str(output),
         '-N', test + '.spice', str(project / (test + '.sch'))],
        cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=60)
    if result.returncode or re.search(r'symbol not found|(?m:^Error:)', result.stdout, re.I):
        raise RuntimeError(f'{test}: Xschem failed\n{result.stdout}')
    deck = (output / (test + '.spice')).read_text()
    controls = re.findall(r'^\.control\s*\n(.*?)^\.endc\s*$', deck, re.M | re.S | re.I)
    if len(controls) != 1 or 'RUNNER_RETURNED_CHECK_REPORT_AND_ERRORS' not in controls[0]:
        raise AssertionError(f'{test}: incomplete simulation launcher')
    if launcher_paths:
        runner, decks = launcher_paths
        command = next(line for line in controls[0].splitlines() if line.startswith('shell '))
        expected = ['shell', 'python3', str(runner), '--deck', str(decks / (test + '.spice')),
                    '--test', test]
        if shlex.split(command) != expected:
            raise AssertionError(f'{test}: launcher paths did not survive quoting: {command}')
    core = core_name(test)
    if not re.search(r'^\.subckt ' + core + r'\s', deck, re.M | re.I):
        raise AssertionError(f'{test}: missing core subcircuit {core}')
    return circuit_text(deck)


def main():
    if not shutil.which('xschem'):
        raise SystemExit('xschem is required; run in your configured GF180 environment')
    with tempfile.TemporaryDirectory(prefix='bandgap-symbols-') as tmp:
        root = Path(tmp)
        project = root / 'checkout'
        project.mkdir()
        for path in HERE.iterdir():
            if path.suffix in ('.sch', '.sym', '.json', '.py'):
                shutil.copyfile(path, project / path.name)

        # A stale same-named library in the working directory must not win.
        unrelated = root / 'unrelated working directory'
        unrelated.mkdir()
        for core in ('Bandgap_Core', 'Bandgap_Core_LoopProbe', 'Bandgap_Core_Res'):
            (unrelated / (core + '.sym')).write_text('not a valid symbol\n')

        baseline = root / 'absolute reference baseline'
        shutil.copytree(project, baseline)
        for test in rb.TESTS:
            path = baseline / (test + '.sch')
            text, count = CORE_REFERENCE.subn(
                lambda m: 'C {' + str(baseline / (core_name(test) + '.sym')) + '}',
                path.read_text())
            assert count == 1, test
            path.write_text(text)
        expected = {test: netlist(baseline, root / 'baseline netlists', unrelated, test)
                    for test in rb.TESTS}
        count = verify_loop_equivalence(expected['TB01_PSRR'], expected[rb.LG])
        print(f'PASS: closed loop-probe matches all {count} core statements; '
              'only M3/N2 gates are cut and C1 stays on MAIN e', flush=True)

        launcher_paths = None
        for stage in ('fresh checkout', 'moved checkout', 'configured then moved'):
            if stage == 'moved checkout':
                project = project.rename(root / 'moved project with spaces')
            elif stage == 'configured then moved':
                launcher_paths = (project / 'run_bandgap.py', root / 'configured netlists')
                with contextlib.redirect_stdout(io.StringIO()):
                    rb.configure(project, root / 'configured netlists')
                project = project.rename(root / 'moved again after configure')
            for test in rb.TESTS:
                actual = netlist(project, root / stage / 'netlists', unrelated, test, launcher_paths)
                if actual != expected[test]:
                    diff = '\n'.join(difflib.unified_diff(expected[test].splitlines(),
                                                         actual.splitlines()))
                    raise AssertionError(f'{stage}: {test} circuit changed\n{diff}')
            print(f'PASS: {stage}: all ten core symbols resolve; circuits match', flush=True)
    print('PASS: 40 Xschem netlists; no simulations performed')


if __name__ == '__main__':
    main()
