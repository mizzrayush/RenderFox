"""Is any deliberately-defective line still applied? Run this before committing.

tools/mutation_check.py puts each file back after it probes one defect, but a sweep
that crashed mid-entry, or a second sweep started by hand, can leave a product file
holding the replacement line. Committing that ships a bug that was only ever meant to
be borrowed for a test, and no suite catches it - the suite is what made it red.

An entry is "applied" when its `find` line has vanished from the file and its
`replace` line is present. Reading both halves avoids the false alarm of a sentence
that legitimately occurs twice in the file.

Usage:  python -X utf8 tools/check_mutations_absent.py [--staged] [tools/mutations_*.py ...]
        --staged reads the staged blob instead of the file on disk, which is the
        question to ask immediately before committing.
Exits 1 and names the file, the entry and both lines if anything looks applied.
"""

import glob
import importlib.util
import os
import subprocess
import sys


def load_entries(path):
    spec = importlib.util.spec_from_file_location(
        "mutations_" + os.path.basename(path).replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, "MUTATIONS", [])


def staged_names():
    return subprocess.run(['git', 'diff', '--cached', '--name-only'],
                          capture_output=True, text=True).stdout.split()


def main(argv):
    use_staged = '--staged' in argv
    argv = [a for a in argv if a != '--staged']
    lists = argv[1:] or sorted(glob.glob("tools/mutations_*.py"))
    staged = staged_names() if use_staged else []
    cache = {}

    def body(product):
        if product not in cache:
            if use_staged:
                cache[product] = subprocess.run(
                    ['git', 'show', f':{product}'], capture_output=True,
                    text=True, encoding='utf-8', errors='replace').stdout
            elif os.path.exists(product):
                with open(product, encoding='utf-8') as handle:
                    cache[product] = handle.read()
        return cache.get(product)

    applied = []
    considered = 0
    for path in lists:
        for index, entry in enumerate(load_entries(path), start=1):
            product = entry["file"]
            if use_staged and product not in staged:
                continue
            considered += 1
            text = body(product)
            if text is None:
                applied.append((path, index, product, "<missing file>", ""))
                continue
            find = entry["find"].rstrip("\n")
            replace = entry["replace"].rstrip("\n")
            if find in text:
                continue
            if replace in text.splitlines():
                applied.append((path, index, product, find, replace))

    print(f"mutation lists read: {len(lists)}; "
          f"{'staged blobs' if use_staged else 'worktree files'} checked: {considered}")
    if applied:
        print(f"DEFECTIVE LINES APPLIED: {len(applied)}")
        for path, index, product, find, replace in applied:
            print(f"  {path} entry {index} -> {product}")
            print(f"    gone:  {find!r}")
            print(f"    there: {replace!r}")
        return 1
    print("clean: every find line is in place in every file the lists touch")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
