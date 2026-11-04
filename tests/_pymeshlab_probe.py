"""
Child-process probe for tests/test_pymeshlab_calls.py.

Every question the validator asks the installed PyMeshLab is answered here, in a
separate interpreter, and returned as one JSON document. Nothing about the
library leaks back into the test process.

That separation is not cosmetic. Probing filters with deliberately invalid enum
values and then letting the MeshSets go is enough to corrupt the parent heap: a
later, unrelated `load_new_mesh()` died with an access violation partway through
a different test. PyMeshLab is C++ with its own static state, so the safe shape
is one short-lived process that asks everything at once and exits before its
destructors can race anything (`os._exit` below).

Run: python tests/_pymeshlab_probe.py < spec.json   (JSON in on stdin, JSON out)
"""

import json
import os
import sys

BAD_VALUE = '@@not-a-real-value@@'

_V = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
_F = [[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]]


def parse_allowed(text):
    """Pull the accepted list out of an InvalidEnumException message."""
    if 'Possible values are' not in text:
        return None
    tail = text.split('Possible values are', 1)[1].rstrip('.').rstrip(';')
    return [part.strip().strip("'") for part in tail.split(';') if part.strip()]


def version_of(pymeshlab):
    """The installed build, so a report can be tied to the library it was checked against."""
    try:
        from importlib.metadata import version
        return version('pymeshlab')
    except Exception:
        return getattr(pymeshlab, '__version__', 'unknown')


def main():
    spec = json.load(sys.stdin)
    import numpy
    import pymeshlab

    vertex = numpy.array(_V, dtype=float)
    faces = numpy.array(_F, dtype='int32')

    def fresh_set():
        ms = pymeshlab.MeshSet()
        ms.add_mesh(pymeshlab.Mesh(vertex_matrix=vertex, face_matrix=faces))
        return ms

    out = {
        'ok': True,
        'version': version_of(pymeshlab),
        'filters': sorted(pymeshlab.filter_list()),
        'meshset_members': sorted(x for x in dir(pymeshlab.MeshSet) if not x.startswith('_')),
        'mesh_members': sorted(x for x in dir(pymeshlab.Mesh) if not x.startswith('_')),
        'params': {},
        'enums': {},
    }

    for name in spec.get('filters', []):
        try:
            out['params'][name] = sorted(fresh_set().filter_parameter_values(name))
        except Exception as error:
            # A filter that is absent reports a distinct message; anything else is
            # a real error worth surfacing rather than calling a missing filter.
            out['params'][name] = None if 'Failed to get default' in str(error) else 'ERROR: ' + str(error)[:200]

    for probe in spec.get('enums', []):
        key = f"{probe['filter']}|{probe['param']}"
        try:
            fresh_set().apply_filter(probe['filter'], **{probe['param']: BAD_VALUE})
            out['enums'][key] = 'no-error'
        except Exception as error:
            out['enums'][key] = parse_allowed(str(error))

    json.dump(out, sys.stdout, sort_keys=True)
    sys.stdout.flush()
    del out
    os._exit(0)


if __name__ == '__main__':
    main()
