"""Cuts the parts and materials a scene does not need, and counts what it removed.

The Advanced sub-tab asked three questions - Remove Hidden Objects, Merge Static Meshes,
Simplify Materials - and threw the answers away: nothing read those checkboxes, so a user
could tick all three, press Preview, see "Yes" and get a file identical to the one they
started with. This module is that backend.

Two rules hold here, and both exist because the cheap version loses data:

* parts are only merged when their materials are the same pixels and the same factors.
  Concatenating two parts with different textures in trimesh drops one of them without
  saying so (measured: the merged mesh comes back with no material), so a part that has
  no partner to batch with is left alone and counted in the report.
* a hidden object is only removed when the file actually marks it hidden, or when it has
  nothing to render (no faces, no area). A format that carries no visibility flag says
  so, instead of quietly deleting the first thing that looked unused.
"""

import hashlib
import json
import os
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from PIL import Image

from .format_converter import FormatConverter
from .texture_optimizer import TEXTURE_SLOTS

try:
    import trimesh
    TRIMESH_AVAILABLE = True
except ImportError:
    TRIMESH_AVAILABLE = False

# A part these readers hand back with no faces has nothing for a renderer to draw, which
# is the one kind of invisible every format here can agree on.
_EMPTY = 'no faces to draw'


def material_key(geometry) -> Tuple:
    """What a shader actually sees for this part: textures by content, factors, no name.

    Two materials that differ only in the name an artist typed are the same material to a
    renderer, and this key is what makes that visible to the optimiser. The image bytes
    are hashed because matching sizes is far more common than matching pixels.
    """
    visual = getattr(geometry, 'visual', None)
    material = getattr(visual, 'material', None)
    if material is None:
        return ('no material',)
    slots = []
    for slot in TEXTURE_SLOTS:
        image = getattr(material, slot, None)
        if isinstance(image, Image.Image):
            slots.append((slot, image.mode, hashlib.md5(image.tobytes()).hexdigest()))
    factors = getattr(material, 'baseColorFactor', None)
    return (type(material).__name__, tuple(sorted(slots)),
            tuple(factors) if factors is not None else None)


def _gltf_header(path: str) -> Optional[dict]:
    """The JSON description inside a .gltf or .glb, or None when it is not readable.

    GLB keeps its header as the first chunk, so the node names and extras a DCC wrote
    survive even though trimesh only hands meshes back.
    """
    try:
        with open(path, 'rb') as handle:
            blob = handle.read()
    except OSError:
        return None
    if blob[:4] == b'glTF':
        if len(blob) < 20 or blob[16:20] != b'JSON':
            return None
        length = struct.unpack('<I', blob[12:16])[0]
        if len(blob) < 20 + length:
            return None
        text = blob[20:20 + length]
    else:
        text = blob
    try:
        return json.loads(text.decode('utf-8', errors='replace'))
    except ValueError:
        return None


def _is_hidden(value) -> bool:
    """How the many ways of writing `true` in a JSON extras block arrive."""
    if value is True:
        return True
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in ('true', 'yes', '1')


def _flagged_in_header(header: dict) -> List[str]:
    """Names of the nodes and meshes whose glTF extras say hidden."""
    names = []
    for section in ('nodes', 'meshes'):
        for entry in header.get(section) or []:
            if _is_hidden((entry.get('extras') or {}).get('hidden')) and entry.get('name'):
                names.append(entry['name'])
    return names


def _flagged_in_collada(path: str) -> Tuple[List[str], str]:
    """Node names a .dae points at a visibility target named or id'd 'hidden'.

    COLLADA stores visibility as an IDREF, so the element the reference lands on has to be
    looked up: a node pointing at a real object is not hidden. References that resolve to
    nothing are counted and reported instead of guessed at.
    """
    try:
        tree = ET.parse(path)
    except (OSError, ET.ParseError) as error:
        return [], (f'the Collada file could not be read to look for visibility flags '
                    f'({type(error).__name__})')

    elements = list(tree.iter())
    by_id = {element.get('id'): element for element in elements if element.get('id')}

    hidden, unresolved = [], []
    for element in elements:
        if not element.tag.endswith('node'):
            continue
        reference = element.get('visibility')
        if not reference:
            continue
        target = by_id.get(reference)
        if target is None:
            unresolved.append(reference)
            continue
        named = 'hidden' in reference.lower() or 'hidden' in (target.get('name') or '').lower()
        if named and element.get('name'):
            hidden.append(element.get('name'))

    note = 'the file\'s own visibility flags'
    if unresolved:
        note += (f'; {len(unresolved)} visibility reference(s) point at an id that is not '
                 f'in the file, so those nodes were left in')
    return hidden, note


def hidden_names(path: str) -> Tuple[List[str], str]:
    """Which parts this file marks invisible, and how that was decided."""
    extension = os.path.splitext(path)[1].lower().lstrip('.')
    if extension in ('gltf', 'glb'):
        header = _gltf_header(path)
        if header is None:
            return [], 'the glTF header could not be read'
        return _flagged_in_header(header), "the file's glTF extras"
    if extension == 'dae':
        return _flagged_in_collada(path)
    return [], (f'.{extension} exposes no visibility flag to the readers installed here')


def _no_geometry(mesh) -> bool:
    """A part a renderer has nothing to draw."""
    try:
        if mesh is None or mesh.faces is None or len(mesh.faces) == 0:
            return True
        return float(mesh.area) == 0.0
    except Exception:
        return False


@dataclass
class SceneResult:
    """One measurable change: what it was called, the count before, the count after."""
    label: str
    before: int
    after: int
    detail: str = ''

    def line(self) -> str:
        text = f'{self.label}: {self.before} -> {self.after}'
        if self.detail:
            text += f' ({self.detail})'
        return text


@dataclass
class SceneReport:
    results: List[SceneResult] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    output: Optional[str] = None
    output_note: str = ''
    stopped: bool = False

    def lines(self) -> List[str]:
        rows = [r.line() for r in self.results]
        rows += [f'removed {name}' for name in self.removed]
        rows += list(self.notes)
        rows += [f'failed: {why}' for why in self.errors]
        if self.output:
            rows.append(f'model written: {os.path.basename(self.output)}'
                        + (f' {self.output_note}' if self.output_note else ''))
        elif self.output_note:
            rows.append(f'model not written: {self.output_note}')
        return rows


@dataclass
class _Instance:
    node: str
    geometry: str
    mesh: object
    key: Tuple


class SceneOptimizer:
    """Removes, batches and dedupes the parts of one model file."""

    def __init__(self, converter: Optional[FormatConverter] = None):
        self.converter = converter or FormatConverter()

    def _instances(self, scene) -> List[_Instance]:
        """One entry per place a part is placed, with that node's transform applied.

        Walked from geometry -> nodes rather than the graph's node list: in this trimesh
        build nodes_geometry is a list of node names where other builds return
        (node, geometry) pairs, and this mapping has not moved. It also keeps two
        instances of the same part separate, which is what a scene with a duplicated prop
        needs before anything is deleted.
        """
        instances: List[_Instance] = []
        keys: Dict[str, Tuple] = {}
        for geometry_name, nodes in scene.graph.geometry_nodes.items():
            geometry = scene.geometry.get(geometry_name)
            if geometry is None:
                continue
            keys.setdefault(geometry_name, material_key(geometry))
            for node in nodes:
                matrix, _ = scene.graph.get(node)
                part = geometry.copy()
                if matrix is not None:
                    part.apply_transform(matrix)
                instances.append(_Instance(node, geometry_name, part, keys[geometry_name]))
        return instances

    def analyze(self, model_path: str) -> dict:
        """What the three switches would find, without writing anything."""
        if not TRIMESH_AVAILABLE:
            return {'error': 'trimesh is not installed'}
        scene, carried = self.converter.read_scene(model_path)
        if scene is None:
            return {'error': f'cannot read {os.path.basename(model_path)}: {carried}'}
        return self.analyze_scene(scene, model_path, carried)

    def analyze_scene(self, scene, model_path: str, carried: str = '') -> dict:
        """The same measurement for a scene that is already read.

        The Advanced preview wants a texture count and these numbers from one load;
        re-reading the file here would make the preview pay for the same bytes twice.
        """
        instances = self._instances(scene)
        flagged, how = hidden_names(model_path)
        names = {instance.node for instance in instances} | \
            {instance.geometry for instance in instances}
        groups: Dict[Tuple, List[_Instance]] = {}
        for instance in instances:
            groups.setdefault(instance.key, []).append(instance)
        batchable = [members for members in groups.values() if len(members) > 1]
        return {
            'read_with': carried,
            'parts': len(instances),
            'faces': sum(instance.mesh.faces.shape[0] for instance in instances),
            'material_names': len({getattr(getattr(i.mesh.visual, 'material', None), 'name',
                                          None) for i in instances}),
            'distinct_materials': len(groups),
            'batches': len(batchable),
            'parts_in_batches': sum(len(members) for members in batchable),
            'parts_after_merge': len(groups),
            'hidden_flagged': len(flagged),
            'hidden_matching_parts': len([name for name in flagged if name in names]),
            'hidden_source': how,
            'nothing_to_render': len([i for i in instances if _no_geometry(i.mesh)]),
        }

    def optimize(self, model_path: str, output_dir: str, remove_hidden: bool = True,
                 merge_static: bool = True, simplify_materials: bool = True,
                 write_model: bool = True,
                 progress: Optional[Callable[[int, int, str], None]] = None,
                 should_cancel: Optional[Callable[[], bool]] = None) -> SceneReport:
        """Apply the switches that are on and write the result, reporting the counts."""
        report = SceneReport()
        if not TRIMESH_AVAILABLE:
            report.errors.append('trimesh is not installed - it is the only reader here '
                                 'that keeps parts and materials apart')
            return report

        scene, carried = self.converter.read_scene(model_path)
        if scene is None:
            report.errors.append(f'cannot read {os.path.basename(model_path)}: {carried}')
            return report

        asked = [on for on in (remove_hidden, merge_static, simplify_materials) if on]
        if not asked:
            report.notes.append('all three switches are off, so nothing was changed and '
                                'no file was written')
            return report

        instances = self._instances(scene)
        started = len(instances)
        names_before = _material_names(instances)
        step = 0

        if remove_hidden:
            step += 1
            if progress is not None:
                progress(step, len(asked), 'looking for objects that cannot render')
            instances = self._remove_hidden(model_path, instances, report)
            report.results.append(SceneResult(
                'parts kept after the hidden pass', started, len(instances),
                f'{started - len(instances)} removed'))

        if should_cancel is not None and should_cancel():
            report.stopped = True
            return report

        if merge_static:
            step += 1
            if progress is not None:
                progress(step, len(asked), 'batching parts that share a material')
            before = len(instances)
            instances = self._merge_static(instances, report)
            report.results.append(SceneResult(
                'parts in the written file', before, len(instances),
                'only parts whose materials are the same pixels were combined'))

        if should_cancel is not None and should_cancel():
            report.stopped = True
            return report

        if simplify_materials:
            step += 1
            if progress is not None:
                progress(step, len(asked), 'giving matching materials one name')
            names_after = self._simplify_materials(instances)
            report.results.append(SceneResult(
                'material names', names_before, names_after,
                'parts stay where they are; a renderer that keys on the name now sees '
                'one material where the file had several'))

        if write_model and not report.stopped:
            output, note = self.converter.optimized_target(model_path, output_dir)
            rebuilt = trimesh.Scene([instance.mesh for instance in instances])
            ok, message = self.converter.write_scene(rebuilt, output)
            if ok:
                report.output = output
                report.output_note = note
            else:
                report.output_note = message
        return report

    @staticmethod
    def _remove_hidden(model_path: str, instances: List[_Instance],
                       report: SceneReport) -> List[_Instance]:
        """Drop the parts that cannot render, and name the rule that caught each one."""
        flagged, how = hidden_names(model_path)
        if flagged:
            report.notes.append(f'{len(flagged)} part(s) flagged hidden by {how}')
        else:
            report.notes.append(f'no hidden objects found: {how}')

        names = {instance.node for instance in instances} | \
            {instance.geometry for instance in instances}
        unmatched = [name for name in flagged if name not in names]
        if unmatched:
            report.notes.append(f'{len(unmatched)} flagged name(s) match no part this reader '
                                f'returned, so nothing was removed for them: '
                                f'{", ".join(unmatched[:6])}')

        kept = []
        for instance in instances:
            if instance.node in flagged or instance.geometry in flagged:
                report.removed.append(f'{instance.geometry} (flagged by the file)')
                continue
            if _no_geometry(instance.mesh):
                report.removed.append(f'{instance.geometry} ({_EMPTY})')
                continue
            kept.append(instance)
        return kept

    @staticmethod
    def _merge_static(instances: List[_Instance], report: SceneReport) -> List[_Instance]:
        """Batch the parts that already share a material; leave the rest alone."""
        groups: Dict[Tuple, List[_Instance]] = {}
        for instance in instances:
            groups.setdefault(instance.key, []).append(instance)

        merged: List[_Instance] = []
        for key, members in groups.items():
            if len(members) == 1:
                merged.append(members[0])
                continue
            try:
                combined = trimesh.util.concatenate([m.mesh for m in members])
            except Exception as error:
                report.errors.append(f'merge of {len(members)} parts failed: '
                                     f'{type(error).__name__}: {str(error)[:120]}')
                merged.extend(members)
                continue
            merged.append(_Instance(members[0].node, members[0].geometry, combined, key))
        return merged

    @staticmethod
    def _simplify_materials(instances: List[_Instance]) -> int:
        """Give parts that share their pixels one material name, and return the count."""
        first: Dict[Tuple, str] = {}
        for instance in instances:
            material = getattr(instance.mesh.visual, 'material', None)
            if material is None:
                continue
            name = getattr(material, 'name', None)
            if not name:
                continue
            chosen = first.setdefault(instance.key, name)
            try:
                material.name = chosen
            except Exception:
                continue
        return len(set(first.values())) or len(_material_names(instances))


def _material_names(instances: List[_Instance]) -> int:
    """How many different material names the parts carry."""
    names = {getattr(getattr(i.mesh.visual, 'material', None), 'name', None)
             for i in instances}
    return len({name for name in names if name})
