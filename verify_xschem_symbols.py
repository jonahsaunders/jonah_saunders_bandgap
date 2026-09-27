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
