"""Defects to plant in the sweep runner itself.

`tools/mutation_check.py` is the instrument every other list in this folder is read with, and
until this phase it was the one file in `tools/` that nobody could break on purpose. What it was
broken on is a run that never answered: entry 74 of `tools/mutations_hardware.py` disconnects a
measurement's error channel, and the sweep held for fourteen minutes - two psutil samples twenty
seconds apart showed the child's CPU time unchanged at 11.8 s while its thread count fell from 19
to 12 - because nothing in the runner said how long a planted suite may take. The same entry, run
alone with a deadline, answers in 119.4 s with two named failures against the 34-38 s that suite
costs clean. So the runner now bounds the wait and calls an unanswered entry HUNG.

Twelve defects, one line each, every one planted in `tools/mutation_check.py`. They are read by
`tests/test_mutation_harness_contract.py`, which parses the runner instead of running it - the
same reason the threading list reads the pane by parsing it: the question "does the sweep have a
deadline" cannot be answered by a sweep, since a sweep without one is exactly the case being asked
about. Nothing here starts a thread, builds a widget or waits for a delivery, so the whole list
costs about two seconds.

One thing is unusual about this list and is worth saying before someone reads the report and
worries: it mutates the file it is being run from. Python has the runner in memory already, so
the planted line reaches only the *next* process - which here is the test that parses the file,
and that is the whole point. Every entry still restores its file from the cached bytes, so the
runner puts itself back before it reads its own line again.

Run:
    python -X utf8 tools/mutation_check.py tests/test_mutation_harness_contract.py \
        tools/mutations_mutation_harness.py
( twelve entries; entries 10 and 11 share one line and are told apart by which half of the advice
  each one erases, so a live plant on that line is read from the entry number, not from the text )
"""

RUNNER = 'tools/mutation_check.py'

MUTATIONS = [
    # ---- the deadline a planted run is given -----------------------------------------------
    {
        'file': RUNNER,
        'find': "                                  errors='replace', cwd=ROOT, timeout=budget)",
        'replace': "                                  errors='replace', cwd=ROOT)",
        'expect': 'test_01',
        'note': 'the shape that held a sweep for fourteen minutes: the budget is computed, '
                'printed in the advice, and never handed to the process it is supposed to end',
    },
    {
        'file': RUNNER,
        'find': "    parser.add_argument('--timeout', type=int, default=SUITE_TIMEOUT,",
        'replace': "    parser.add_argument('--timeout', type=int, default=None,",
        'expect': 'test_01',
        'note': 'a sweep run without the flag waits forever again, and the number the constant '
                'names is only in force when someone remembers to type it',
    },
    {
        'file': RUNNER,
        'find': '        budget = item.get(\'timeout\', args.timeout)',
        'replace': '        budget = args.timeout',
        'expect': 'test_01',
        'note': 'an entry can no longer say that its suite legitimately needs longer, so the one '
                'escape hatch from a wrong default is gone and the honest answer becomes HUNG',
    },
    {
        'file': RUNNER,
        'find': 'SUITE_TIMEOUT = 900',
        'replace': 'SUITE_TIMEOUT = 60',
        'expect': 'test_01',
        'note': 'the shipped budget falls below a clean run of the suite it guards, so every '
                'entry of the slow lists answers HUNG and the sweep says nothing about defects',
    },

    # ---- what an unanswered run is called --------------------------------------------------
    {
        'file': RUNNER,
        'find': '        except subprocess.TimeoutExpired:',
        'replace': '        except OSError:',
        'expect': 'test_02',
        'note': 'the deadline is no longer caught where the run happens, so the exception reaches '
                'the top of the loop, the sweep dies mid-entry and the product keeps the planted '
                'line for the next person to find',
    },
    {
        'file': RUNNER,
        'find': '            proc, names, caught = None, [], []',
        'replace': '            proc, names, caught = subprocess.CompletedProcess([sys.executable], 0, \'\', \'OK\'), [], []',
        'expect': 'test_02',
        'note': 'a run that answered nothing is given an answer, which the verdict chain below '
                'reads as a suite that passed - the entry prints SURVIVED and the sweep exits 0',
    },
    {
        'file': RUNNER,
        'find': '            hung.append(label)',
        'replace': '            pass',
        'expect': 'test_02',
        'note': 'the hung entry is printed and then forgotten, so the summary can still claim '
                'every defect was caught while an unknown number of them went unanswered',
    },
    {
        'file': RUNNER,
        'find': '    if survived or crashed or hung:',
        'replace': '    if survived or crashed:',
        'expect': 'test_02',
        'note': 'a sweep with unanswered entries exits as though it had measured everything, '
                'which is how a harness that cannot be trusted reads as a green run',
    },

    # ---- what the advice printed under a hung entry tells the reader -----------------------
    {
        'file': RUNNER,
        'find': "                  f'the child was killed and the file restored, so ask for this entry alone '",
        'replace': "                  f'the child was killed, so ask for this entry alone '",
        'expect': 'test_03',
        'note': 'the reader is told a process was killed and not that the product was put back, '
                'which leaves them checking the tree by hand before the next entry',
    },
    {
        'file': RUNNER,
        'find': "                  f'with --only {index} and a longer --timeout')",
        'replace': "                  f'with --only {index} and a shorter --timeout')",
        'expect': 'test_03',
        'note': 'the advice names the deadline that was exceeded and points the wrong way, so '
                'following it makes the next sweep hang sooner',
    },
    {
        'file': RUNNER,
        'find': "                  f'with --only {index} and a longer --timeout')",
        'replace': "                  f'with --only on the suite and a longer --timeout')",
        'expect': 'test_03',
        'note': 'the advice no longer says which entry it just refused to answer for, and asking '
                'again means re-running the whole list to find the one number',
    },

    # ---- the verdict list a reader sees before they run anything ---------------------------
    {
        'file': RUNNER,
        'find': 'moving. That is answered as its own verdict, HUNG, with the child killed and the file restored,',
        'replace': 'moving. That is answered by ending the run, with the child killed and the file restored,',
        'expect': 'test_03',
        'note': 'this docstring is what `--help` prints, so the runner describes four disguises '
                'and names three verdicts - a reader cannot look up the word the report used',
    },
]
