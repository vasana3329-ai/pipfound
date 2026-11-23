#!/usr/bin/env python3
"""Run every Python suite in isolated homes; persist exact per-suite results."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--python', default=sys.executable)
    p.add_argument('--output', type=Path)
    p.add_argument('--timeout', type=int, default=240)
    p.add_argument('--only', nargs='*')
    args = p.parse_args()
    root = Path(__file__).resolve().parent
    out = args.output or Path(tempfile.mkdtemp(prefix='pipfound-tests-'))
    out.mkdir(parents=True, exist_ok=True)
    suites = args.only or ['selfcheck.py'] + sorted(x.name for x in root.glob('*_test.py'))
    if len(suites) != len(set(suites)):
        raise ValueError('Duplicate suites')
    results = []
    for suite in suites:
        home = out / (Path(suite).stem + '-home')
        tmp = home / 'tmp'
        tmp.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, HOME=str(home), TMPDIR=str(tmp), PIPFOUND_NOTIFY='0', PYTHONDONTWRITEBYTECODE='1')
        for key in list(env):
            if key.startswith('PIPFOUND_') and key != 'PIPFOUND_NOTIFY':
                env.pop(key)
        start = time.monotonic()
        try:
            run = subprocess.run([args.python, str(root / suite)], cwd=root, env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, timeout=args.timeout)
            text, rc = run.stdout, run.returncode
        except subprocess.TimeoutExpired as exc:
            text = exc.stdout or b''
            if isinstance(text, bytes):
                text = text.decode(errors='replace')
            text += '\nTIMEOUT\n'
            rc = 124
        log = out / (suite + '.log')
        log.write_text(text, encoding='utf-8')
        item = dict(suite=suite, exit_code=rc, seconds=round(time.monotonic()-start, 2), log=str(log))
        results.append(item)
        report = dict(python=args.python, expected=suites, results=results)
        (out / 'results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print('PASS' if rc == 0 else 'FAIL', suite, item['seconds'], flush=True)
        if rc:
            print(text[-6000:], flush=True)
    assert len(results) == len(suites)
    passed = sum(x['exit_code'] == 0 for x in results)
    print(json.dumps(dict(total=len(results), passed=passed, failed=len(results)-passed,
                          report=str(out/'results.json'))), flush=True)
    return 0 if passed == len(results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
