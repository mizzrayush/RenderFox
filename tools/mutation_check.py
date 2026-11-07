"""Run a list of one-defect-at-a-time source mutations and prove the named test catches each.

A contract suite that passes proves the code agrees with itself. It does not prove the
suite would notice if the code were wrong. This runner makes the suite answer that: it
rewrites one real line of the product, runs the suite, and demands that a specific test
fails by name - then puts the file back byte for byte and checks the checksum.

Usage:
    python -X utf8 tools/mutation_check.py tests/test_foo_contract.py spec.py

spec.py must define MUTATIONS as a list of dicts:
    file    path to the product file (relative to the repo root)
    suite   optional test file to run for this one, overriding the one given on the command line
    find    the exact source line to replace, including its indentation
    replace the defective line
    expect  a substring of the test name that must fail
    note    why this defect matters (printed in the report)
    which   optional 1-based number, for a line the file says more than once

A mutation that no test catches is a hole in the suite, not a defect in the product. A
mutation that kills the suite before it reports is the same hole in a worse disguise: PyQt6
aborts the process on an exception raised inside a slot, so no FAIL or ERROR line is ever
printed and a reader who only counts named failures sees a clean run. Both are called out.

The third disguise is the runner's own: a suite name that does not resolve makes python exit 2
before any test runs, which is indistinguishable from a suite killed by a mutation, so every
entry in the list comes back CRASHED and the advice printed under it points at tests that
already reach the defect. The suite paths are therefore checked before anything is planted, and
a run that cannot start says so and plants nothing (exit 2).
"""

import argparse
import hashlib
import os
import re
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def load_mutations(path):
    namespace = {'__file__': os.path.abspath(path)}
    with open(path, encoding='utf-8') as handle:
        source = handle.read()
    exec(compile(source, path, 'exec'), namespace)
    mutations = namespace['MUTATIONS']
    for item in mutations:
        for key in ('file', 'find', 'replace', 'expect'):
            if key not in item:
                raise ValueError(f'mutation {item.get("note", item)} is missing {key!r}')
    return mutations


def swap(text, find, replace, which=None):
    """Replace one exact line. Refuses to guess when the anchor is not unique."""
    lines = text.split('\n')
    hits = [i for i, line in enumerate(lines) if line == find]
    if not hits:
        raise ValueError(f'anchor not found: {find!r}')
    if which is None and len(hits) > 1:
        raise ValueError(f'anchor matched {len(hits)} times; say which one: {find!r}')
    if which is not None and which > len(hits):
        raise ValueError(f'asked for #{which} of {len(hits)} matches: {find!r}')
    lines[hits[(which or 1) - 1]] = replace
    return '\n'.join(lines)


def failing_tests(stderr):
    """Every test the run said went wrong, by name - a raised exception counts too."""
    names = []
    for line in stderr.splitlines():
        match = re.match(r'^(?:FAIL|ERROR):\s+(\S+)', line)
        if match:
            # subTest adds a " (key=value)" suffix that is not part of the test name
            names.append(match.group(1).split(')')[0].strip())
    return names


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('suite', help='test file to run against each mutation')
    parser.add_argument('spec', help='python file defining MUTATIONS')
    parser.add_argument('--list', action='store_true', help='only check every anchor is unique')
    parser.add_argument('--only', help='run just these numbers, e.g. --only 22 or --only 22,26')
    parser.add_argument('--verbose', action='store_true', help='print the failure text')
    args = parser.parse_args()

    mutations = load_mutations(os.path.join(ROOT, args.spec) if not os.path.isabs(args.spec) else args.spec)
    if args.list:
        for item in mutations:
            path = os.path.join(ROOT, item['file'])
            original = open(path, 'rb').read().decode('utf-8')
            swap(original.replace('\r\n', '\n'), item['find'], item['replace'], item.get('which'))
            print(f'anchor ok: {item["file"]}: {item["note"]}')
        print(f'{len(mutations)} anchors are unique')
        return 0

    if args.only:
        wanted = {int(one) for one in args.only.split(',') if one.strip().isdigit()}
        mutations = [dict(item, number=index) for index, item in enumerate(mutations, 1)
                     if index in wanted]

    # Ask whether the suite is there before anything is planted. A name that does not resolve is
    # not a neutral mistake: python answers "can't open file" with exit 2, which this runner reads
    # as a suite that died on a mutation, so every entry in the list comes back CRASHED and the
    # advice it prints - "the test must reach the defect directly" - sends the reader into tests
    # that already do. Measured with a mistyped suite name: three entries reported as crash-only
    # on a machine where all three are caught by a named test.
    suites = {args.suite} | {one['suite'] for one in mutations if one.get('suite')}
    missing = sorted(one for one in suites if not os.path.exists(os.path.join(ROOT, one)))
    if missing:
        print(f'suite not found: {", ".join(missing)} - nothing was planted')
        return 2

    cache = {}
    survived = []
    crashed = []
    broken_restore = []
    for position, item in enumerate(mutations, 1):
        index = item.get('number', position)
        path = os.path.join(ROOT, item['file'])
        if path not in cache:
            raw = open(path, 'rb').read()
            cache[path] = (raw, hashlib.sha256(raw).hexdigest())
        raw, digest = cache[path]
        text = raw.decode('utf-8')
        crlf = '\r\n' in text
        body = text.replace('\r\n', '\n')
        number = f'[{index:02d}]'
        try:
            mutated = swap(body, item['find'], item['replace'], item.get('which'))
        except ValueError as error:
            print(f'{number} ANCHOR {item["file"]}: {error}')
            broken_restore.append(f'{number} anchor: {error}')
            continue
        if crlf:
            mutated = mutated.replace('\n', '\r\n')
        open(path, 'wb').write(mutated.encode('utf-8'))

        suite = item.get('suite') or args.suite
        proc = subprocess.run([sys.executable, '-X', 'utf8', os.path.join(ROOT, suite)],
                              capture_output=True, text=True, encoding='utf-8', errors='replace',
                              cwd=ROOT)
        names = failing_tests(proc.stderr)
        caught = [name for name in names if item['expect'] in name]

        open(path, 'wb').write(raw)
        if hashlib.sha256(open(path, 'rb').read()).hexdigest() != digest:
            broken_restore.append(f'{number} {item["file"]} did not restore byte-exactly')

        if args.verbose:
            report = proc.stderr.splitlines()
            keep = [i for i, one in enumerate(report) if one.startswith(('FAIL:', 'ERROR:'))]
            for i in keep:
                print(chr(10).join(report[i:i + 14]))
                print('-' * 70)
        label = f'{number} {item["note"]}'
        if caught:
            print(f'{label}\n      caught by {len(caught)} test(s): ' + ', '.join(sorted(set(caught))[:4]))
        elif proc.returncode != 0 or 'OK' not in proc.stderr:
            # a suite that never reaches its report line detected the defect too, but not in
            # a way anyone can read: PyQt6 aborts the process on an exception raised inside a
            # slot, so the crash stands in for a named failure and hides which test owns it
            print(f'{label}\n      CRASHED - the suite died (exit {proc.returncode:#x}) without '
                  f'reporting; no named test, so the test must reach the defect directly')
            crashed.append(label)
        else:
            print(f'{label}\n      SURVIVED - no test named {item["expect"]!r} failed '
                  f'({len(names)} failures: {", ".join(names[:6]) or "none"})')
            survived.append(label)

    print('-' * 70)
    if broken_restore:
        print('RESTORE FAILURES (check these files by hand):')
        for line in broken_restore:
            print('  ' + line)
    if crashed:
        print(f'{len(crashed)} defect(s) were detected only by killing the suite:')
        for line in crashed:
            print('  ' + line)
    if survived:
        print(f'{len(survived)} of {len(mutations)} defects went unnoticed:')
        for line in survived:
            print('  ' + line)
    if survived or crashed:
        return 1
    print(f'all {len(mutations)} defects were caught by a named test')
    return 0


if __name__ == '__main__':
    sys.exit(main())
