"""Which pymeshlab filters survive a mesh that carries UVs, measured one process per case.

Run:  python tools/probe_backend_safety.py            full table
      python tools/probe_backend_safety.py --json     same table as JSON

Every case gets its own process on purpose: pymeshlab 2025.7 does not raise when a filter
fails badly, it takes the whole interpreter down with a segfault, and a crash inside a
worker thread of the app is a crash of the app. A single-process sweep would stop at the
first one and report nothing about the rest, which is the opposite of what this file is
for - the Pipeline engine routes its mesh nodes by the answers printed here.
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# (case name, filter name, extra kwargs) - each one is a filter src/processing/mesh_processor.py
# actually calls, copied from the call sites rather than from the MeshLab menu.
FILTERS = [
    ('quadric_target', 'meshing_decimation_quadric_edge_collapse',
     dict(targetfacenum=400, preserveboundary=True, autoclean=True)),
    ('quadric_planar', 'meshing_decimation_quadric_edge_collapse',
     dict(targetfacenum=400, planarquadric=True, planarweight=0.001, qualitythr=0.3,
          preserveboundary=True, autoclean=True)),
    ('quadric_preservenormal', 'meshing_decimation_quadric_edge_collapse',
     dict(targetfacenum=400, preservenormal=True, preserveboundary=True, autoclean=True)),
    ('clustering', 'meshing_decimation_clustering', dict(threshold=('pct', 5.0))),
    ('laplacian', 'apply_coord_laplacian_smoothing', dict(stepsmoothnum=5, boundary=True)),
    ('taubin', 'apply_coord_taubin_smoothing', dict(lambda_=0.5, mu=-0.53, stepsmoothnum=10)),
    ('depth_smooth', 'apply_coord_depth_smoothing', dict(stepsmoothnum=3, delta=('pct', 20.0))),
    ('isotropic_remesh', 'meshing_isotropic_explicit_remeshing',
     dict(targetlen=('pct', 5.0), iterations=2, adaptive=False, featuredeg=30.0, splitflag=True,
          collapseflag=True, swapflag=True, smoothflag=True, reprojectflag=True)),
    ('quad_remesh', 'meshing_tri_to_quad_by_smart_triangle_pairing', {}),
    ('sub_loop', 'meshing_surface_subdivision_loop', dict(iterations=1)),
    ('sub_catmull_clark', 'meshing_surface_subdivision_catmull_clark', dict(iterations=1)),
    ('sub_midpoint', 'meshing_surface_subdivision_midpoint', dict(iterations=1)),
    ('sub_butterfly', 'meshing_surface_subdivision_butterfly', dict(iterations=1)),
    ('weld_close', 'meshing_merge_close_vertices', dict(threshold=('pct', 1.0))),
    ('remove_duplicated_verts', 'meshing_remove_duplicate_vertices', {}),
    ('remove_null_faces', 'meshing_remove_null_faces', {}),
    ('remove_folded_faces', 'meshing_remove_folded_faces', {}),
    ('remove_duplicate_faces', 'meshing_remove_duplicate_faces', {}),
    ('remove_unreferenced', 'meshing_remove_unreferenced_vertices', {}),
    ('repair_non_manifold_edges', 'meshing_repair_non_manifold_edges', dict(method='Remove Faces')),
    ('repair_non_manifold_vertices', 'meshing_repair_non_manifold_vertices',
     dict(vertdispratio=0.1)),
    ('invert_face_orientation', 'meshing_invert_face_orientation',
     dict(forceflip=True, onlyselected=False)),
    ('re_orient_faces_coherently', 'meshing_re_orient_faces_coherently', {}),
    ('compute_vertex_normals', 'compute_normal_per_vertex', {}),
    ('uv_trivial', 'compute_texcoord_parametrization_triangle_trivial_per_wedge',
     dict(textdim=512, border=2, method='Basic')),
    ('uv_flat_plane', 'compute_texcoord_parametrization_flat_plane_per_wedge', {}),
    ('uv_harmonic', 'compute_texcoord_parametrization_harmonic', {}),
    ('uv_voronoi_atlas', 'generate_voronoi_atlas_parametrization', {}),
    ('uv_merge_wedge', 'apply_texcoord_merge_per_wedge', {}),
]

CHILD = r'''
import json, os, sys
sys.path.insert(0, %(root)r)
import numpy as np, trimesh, pymeshlab
path, filter_name, kwargs, give_uv, work = json.loads(sys.argv[1])
ms = pymeshlab.MeshSet()
ms.load_new_mesh(path)
if give_uv:
    ms.apply_filter('compute_texcoord_parametrization_triangle_trivial_per_wedge',
                    textdim=512, border=2, method='Basic')
    assert ms.current_mesh().has_wedge_tex_coord(), 'seeding UVs failed'
before = (ms.current_mesh().vertex_number(), ms.current_mesh().face_number())
fixed = dict(kwargs)
for key, value in list(fixed.items()):
    # json turns ('pct', 5.0) into ['pct', 5.0] on the way into the child, so both shapes count.
    if isinstance(value, (list, tuple)) and value[0] == 'pct':
        fixed[key] = pymeshlab.PercentageValue(value[1])
out = os.path.join(work, 'case.obj')
ms.apply_filter(filter_name, **fixed)
ms.save_current_mesh(out)
after = (ms.current_mesh().vertex_number(), ms.current_mesh().face_number())
has_uv = ms.current_mesh().has_wedge_tex_coord()
rows = len(ms.current_mesh().wedge_tex_coord_matrix()) if has_uv else 0
print('RESULT', json.dumps({'ok': True, 'before': before, 'after': after, 'uv': has_uv,
                            'uv_rows': rows, 'file_bytes': os.path.getsize(out)}))
''' % {'root': ROOT}


def run_case(name, filter_name, kwargs, give_uv, source, work):
    payload = json.dumps([source, filter_name, kwargs, give_uv, work])
    proc = subprocess.run([sys.executable, '-c', CHILD, payload],
                          capture_output=True, text=True, timeout=300)
    for line in proc.stdout.splitlines():
        if line.startswith('RESULT '):
            return {'case': name, 'uv_seeded': give_uv, 'status': 'ok',
                    **json.loads(line[len('RESULT '):])}
    err = (proc.stderr or proc.stdout).strip().splitlines()
    reason = err[-1][:150] if err else 'no output'
    status = 'CRASHED' if proc.returncode not in (0, 1) else 'raised'
    return {'case': name, 'uv_seeded': give_uv, 'status': status,
            'exit': proc.returncode, 'reason': reason}


def main():
    import trimesh
    work = tempfile.mkdtemp(prefix='rf_safety_')
    source = os.path.join(work, 'case_src.obj')
    trimesh.creation.icosphere(subdivisions=3, radius=1.0).export(source)
    open(os.path.join(work, 'case_src.mtl'), 'w').write('newmtl m\nKd 1 1 1\n')

    rows = []
    for name, filter_name, kwargs in FILTERS:
        for give_uv in (False, True):
            rows.append(run_case(name, filter_name, kwargs, give_uv, source, work))

    if '--json' in sys.argv:
        print(json.dumps(rows, indent=1))
        return
    print(f"{'case':28} {'UVs in':7} {'result':9} {'counts':18} uv rows / reason")
    for row in rows:
        counts = f"{row.get('before')} -> {row.get('after')}" if row['status'] == 'ok' else ''
        detail = f"{row.get('uv_rows', 0)} rows" if row['status'] == 'ok' else row.get('reason', '')
        print(f"{row['case']:28} {'yes' if row['uv_seeded'] else 'no':7} "
              f"{row['status']:9} {counts:18} {detail[:90]}")

    crashing = [r['case'] for r in rows if r['status'] == 'CRASHED' and r['uv_seeded']]
    losing_uv = [r['case'] for r in rows if r['status'] == 'ok' and r['uv_seeded'] and not r['uv']]
    print("\nfilters that take the process down when the mesh has UVs: "
          f"{', '.join(sorted(set(crashing))) or 'none'}")
    print("filters that run but drop the UVs: "
          f"{', '.join(sorted(set(losing_uv))) or 'none'}")


if __name__ == '__main__':
    main()
