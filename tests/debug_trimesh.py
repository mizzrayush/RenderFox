import trimesh
import inspect

print(f"Trimesh version: {trimesh.__version__}")

try:
    mesh = trimesh.creation.icosphere()
    if hasattr(mesh, 'simplify_quadric_decimation'):
        print("simplify_quadric_decimation exists")
        sig = inspect.signature(mesh.simplify_quadric_decimation)
        print(f"Signature: {sig}")
        print(f"Docstring: {mesh.simplify_quadric_decimation.__doc__}")
    else:
        print("simplify_quadric_decimation NOT found")
except Exception as e:
    print(f"Error: {e}")
