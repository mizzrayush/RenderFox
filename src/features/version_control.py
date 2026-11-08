"""
Asset Version Control - Time-Based Versioning & Visual Diff Viewer

This module provides Git-like version control for 3D assets with visual comparison.

Features:
- Automatic version snapshots on save
- Version history timeline with thumbnails
- Visual diff between versions (geometry changes)
- Rollback to any previous version
- Performance comparison (polygon reduction tracking)
- Branching for experiments
- Commit messages and metadata

Author: RenderFox Team
Date: October 2025
"""

import os
import shutil
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import trimesh
import numpy as np
import logging

from ..utils.app_paths import output_dir
from ..utils.thumbnail_renderer import generate_3d_thumbnail

MAX_FILE_SIZE = 500 * 1024 * 1024  # 500 MB

logger = logging.getLogger(__name__)

# What a row says about a number the file does not have. Kept here so the timeline column, the
# details pane and the HTML export all describe one absence in the same words.
NO_FACES = 'no faces'
NO_WATERTIGHT = 'no faces to close'
NOT_COMPARABLE = 'not comparable - one version of this file has no faces'
NO_GEOMETRY = ('the file holds neither a triangle mesh nor a point cloud, so there is nothing '
               'to measure')


def _normalise(loaded):
    """One triangle mesh from whatever `trimesh.load` answered, or None if there is no mesh.

    Imported on call rather than at the top of the module because `format_converter` drags
    pymeshlab in: measured here at 1.54 s against 0.007 s for this module's own imports.
    """
    from ..processing.format_converter import as_trimesh
    return as_trimesh(loaded)


def _delta(now, then):
    """Subtract a recorded count from a new one; None when either side does not have a number."""
    return None if now is None or then is None else now - then


def _measure_model(model_path: Path) -> Optional[Dict]:
    """The facts a version row can honestly record for one file.

    `trimesh.load` answers with three different objects and this backend was written against
    one of them. Measured on this machine: an .obj carrying `mtllib`/`usemtl` - which is what
    the app's own repair writes, `repaired_model.obj.mtl` beside it - answers `Scene`, a file
    whose faces have been deleted answers `PointCloud`, and an empty or garbled .obj answers a
    `Scene` with no geometries. `len(loaded.faces)` raised on the first two, `save_version`
    logged the exception and returned None, and the pane read that as "no changes".

    Returns None when there is no geometry at all, which is a fact to refuse on rather than an
    error. A `PointCloud` has vertices and no faces: measured here, `faces`, `is_watertight`
    and `volume` all raise `AttributeError` on it, so its face counts are recorded as absent.
    """
    loaded = trimesh.load(str(model_path))
    mesh = _normalise(loaded)
    if mesh is not None:
        return {'mesh': mesh,
                'polygon_count': len(mesh.faces),
                'vertex_count': len(mesh.vertices),
                'is_watertight': bool(mesh.is_watertight)}
    if isinstance(loaded, trimesh.PointCloud):
        return {'mesh': None,
                'polygon_count': None,
                'vertex_count': len(loaded.vertices),
                'is_watertight': None}
    return None


def describe_polygon_count(version: Dict) -> str:
    """The polygon count of one row, in words the row's own facts support."""
    count = version.get('polygon_count')
    return NO_FACES if count is None else f"{count:,}"


def describe_watertight(version: Dict) -> str:
    closed = version.get('is_watertight')
    if closed is None:
        return NO_WATERTIGHT
    return 'Yes' if closed else 'No'


def describe_volume(value, signed: bool = False) -> str:
    """One volume from a comparison, or the fact that the surface is not closed.

    Measured here: trimesh answers `is_volume` False for an open mesh, and an open surface has
    no volume rather than a volume of nothing - which is what the comparison table's 0.0000 was.
    """
    if value is None:
        return NO_WATERTIGHT
    return f"{value:+.4f}" if signed else f"{value:.4f}"


def describe_metrics(version: Dict) -> str:
    """The timeline's Metrics column for one row, with its delta against the parent."""
    polygons = version.get('polygon_count')
    vertices = version.get('vertex_count')
    if polygons is None:
        text = f"V: {vertices:,}, {NO_FACES}"
    else:
        text = f"P: {polygons:,}, V: {vertices:,}"
    delta = version.get('polygons_delta')
    if delta:
        text += f" ({delta:+,})"
    return text


class AssetVersionControl:
    """
    Version control system for 3D assets.
    
    Provides Git-like functionality specifically designed for binary 3D files.
    Includes visual diff and performance tracking.
    """
    
    def __init__(self, library_path: str):
        """
        Initialize version control system.
        
        Args:
            library_path: Root path of the asset library
        """
        self.library_path = Path(library_path)
        self.versions_dir = self.library_path / '.versions'
        self.snapshots_dir = self.versions_dir / 'snapshots'
        self.thumbnails_dir = self.versions_dir / 'thumbnails'
        self.db_path = self.versions_dir / 'versions.db'
        
        # Create directories
        self.versions_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        self.thumbnails_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize database
        self._init_database()
    
    def _init_database(self):
        """Initialize SQLite database for version tracking."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        # Versions table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model_path TEXT NOT NULL,
                version_number INTEGER NOT NULL,
                file_hash TEXT NOT NULL,
                snapshot_path TEXT NOT NULL,
                thumbnail_path TEXT,
                timestamp TEXT NOT NULL,
                commit_message TEXT,
                author TEXT,
                branch TEXT DEFAULT 'main',
                parent_version_id INTEGER,
                
                -- Model metrics
                polygon_count INTEGER,
                vertex_count INTEGER,
                file_size INTEGER,
                is_watertight BOOLEAN,
                
                -- Diff metrics (compared to parent)
                polygons_delta INTEGER,
                vertices_delta INTEGER,
                volume_delta REAL,
                
                UNIQUE(model_path, version_number)
            )
        ''')
        
        # Tags table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS version_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version_id INTEGER NOT NULL,
                tag_name TEXT NOT NULL,
                FOREIGN KEY (version_id) REFERENCES versions (id),
                UNIQUE(version_id, tag_name)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def save_version(self, model_path: str, commit_message: str = "", 
                    author: str = "User", branch: str = "main", auto: bool = False) -> Optional[int]:
        """
        Create a new version snapshot of a model.
        
        Args:
            model_path: Path to the model file
            commit_message: Description of changes
            author: Author name
            auto: Whether this is an automatic save
            
        Returns:
            Version ID if saved, None if the file is not on disk, is already committed on this
            branch, or holds nothing measurable. `explain_no_commit` says which of those it was.
        """
        try:
            model_path = Path(model_path)
            
            if not model_path.exists():
                logger.error(f"Model not found: {model_path}")
                return None
            
            # Check file size
            file_size = model_path.stat().st_size
            if file_size > MAX_FILE_SIZE:
                raise ValueError(f"File too large ({file_size / 1024 / 1024:.1f} MB). Max allowed is 500 MB.")
            
            # Check disk space
            total, used, free = shutil.disk_usage(self.snapshots_dir)
            if free < file_size * 2:  # Ensure we have at least 2x file size available
                raise IOError(f"Insufficient disk space. Need {file_size / 1024 / 1024:.1f} MB, but only {free / 1024 / 1024:.1f} MB available.")
            
            # Calculate file hash
            file_hash = self._calculate_file_hash(model_path)
            
            # Check if this exact version already exists
            if self._is_duplicate_version(str(model_path), file_hash, branch):
                logger.info(f"No changes detected for {model_path.name}, skipping version save")
                return None
            
            # Measured before the file is copied. This used to sit two statements after
            # `shutil.copy2` as `len(mesh.faces)`, so a multi-material export - which is what the
            # app's own repair writes, `repaired_model.obj.mtl` beside the .obj - raised
            # `AttributeError` there, was caught at the bottom of this method, and left its
            # snapshot on disk with no row pointing at it: invisible to rollback, never deleted.
            try:
                metrics = _measure_model(model_path)
            except Exception as e:
                logger.error(f"Could not read {model_path.name} to measure it: {e}")
                return None
            if metrics is None:
                logger.error(f"Refusing to commit {model_path.name}: {NO_GEOMETRY}")
                return None

            metrics['file_size'] = file_size

            # Get next version number
            version_number = self._get_next_version_number(str(model_path))

            # Create snapshot
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            snapshot_name = f"{model_path.stem}_v{version_number}_{timestamp}{model_path.suffix}"
            snapshot_path = self.snapshots_dir / snapshot_name
            thumbnail_path = None

            try:
                shutil.copy2(model_path, snapshot_path)

                # Generate thumbnail (optional)
                thumbnail_path = self._generate_thumbnail(snapshot_path)

                # Get parent version for diff calculation
                parent_version = self._get_latest_version(str(model_path), branch)

                # Calculate diff if parent exists
                diff_metrics = {}
                if parent_version:
                    diff_metrics = self._calculate_diff(metrics, parent_version)

                # Save to database
                version_id = self._save_version_to_db(
                    model_path=str(model_path),
                    version_number=version_number,
                    file_hash=file_hash,
                    snapshot_path=str(snapshot_path),
                    thumbnail_path=thumbnail_path,
                    timestamp=datetime.now().isoformat(),
                    commit_message=commit_message if commit_message else f"Auto-save v{version_number}",
                    author=author,
                    branch=branch,
                    metrics=metrics,
                    diff_metrics=diff_metrics,
                    parent_version_id=parent_version['id'] if parent_version else None
                )
            except Exception:
                # Nothing past the copy may leave a file behind that no row names.
                if thumbnail_path:
                    Path(thumbnail_path).unlink(missing_ok=True)
                snapshot_path.unlink(missing_ok=True)
                raise

            logger.info(f"Version {version_number} saved for {model_path.name}")
            return version_id
            
        except (ValueError, IOError) as e:
            # Re-raise specific errors for UI handling
            raise e
        except Exception as e:
            logger.error(f"Error saving version: {e}")
            return None
    
    def explain_no_commit(self, model_path: str, branch: str = 'main') -> Dict:
        """Say, from the file and the rows, why `save_version` recorded nothing.

        `save_version` answers None for four different facts - no file on disk, bytes already
        committed, a file with no geometry, a write that did not finish - and the pane read all
        four as "No changes detected", which is one of them. It asks this instead of guessing,
        and gets its answers from the same helpers the commit asks, not from a second reading
        of what went wrong.

        Returns `{'kind', 'reason'}`, the shape the app's other engines refuse with.
        """
        path = Path(model_path)
        if not path.exists():
            return {'kind': 'no_file', 'reason': f'There is no file at {path} to commit.'}
        try:
            metrics = _measure_model(path)
        except Exception as e:
            return {'kind': 'unreadable', 'reason': f'The file could not be read: {e}'}
        if metrics is None:
            return {'kind': 'no_geometry', 'reason': f'Nothing was committed: {NO_GEOMETRY}.'}
        if self._is_duplicate_version(str(path), self._calculate_file_hash(path), branch):
            return {'kind': 'duplicate',
                    'reason': 'No changes detected. This file is already the newest version '
                              'committed on this branch.'}
        return {'kind': 'aborted',
                'reason': 'The commit did not finish. Its reason is in the log.'}

    def get_version_history(self, model_path: str, branch: str = 'main') -> List[Dict]:
        """
        Get version history for a model.
        
        Args:
            model_path: Path to the model
            branch: Branch name (default: 'main')
            
        Returns:
            List of version dictionaries, newest first
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM versions
            WHERE model_path = ? AND branch = ?
            ORDER BY version_number DESC
        ''', (str(model_path), branch))
        
        versions = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return versions
    
    def compare_versions(self, version1_id: int, version2_id: int) -> Dict:
        """
        Compare two versions and generate visual diff.
        
        Args:
            version1_id: First version ID
            version2_id: Second version ID
            
        Returns:
            Dictionary containing comparison data
        """
        try:
            # Get version info
            v1 = self._get_version_by_id(version1_id)
            v2 = self._get_version_by_id(version2_id)
            
            if not v1 or not v2:
                return {'error': 'Version not found'}
            
            # Load meshes
            mesh1 = _normalise(trimesh.load(v1['snapshot_path']))
            mesh2 = _normalise(trimesh.load(v2['snapshot_path']))

            no_mesh = [v['version_number'] for v, m in ((v1, mesh1), (v2, mesh2)) if m is None]
            if no_mesh:
                # A fact about the files, said once for both of them. This method used to reach
                # `len(mesh.faces)` on a Scene and hand the dialog the raw AttributeError as its
                # error string.
                names = ' and v'.join(str(n) for n in no_mesh)
                return {'error': f"v{names} "
                                 f"{'holds' if len(no_mesh) == 1 else 'hold'} no triangle mesh, "
                                 f"so there is nothing to compare"}

            # Calculate differences
            comparison = {
                'version1': {
                    'id': v1['id'],
                    'version_number': v1['version_number'],
                    'timestamp': v1['timestamp'],
                    'commit_message': v1['commit_message']
                },
                'version2': {
                    'id': v2['id'],
                    'version_number': v2['version_number'],
                    'timestamp': v2['timestamp'],
                    'commit_message': v2['commit_message']
                },
                'changes': {
                    'polygons': {
                        'v1': len(mesh1.faces),
                        'v2': len(mesh2.faces),
                        'delta': len(mesh2.faces) - len(mesh1.faces),
                        'percent': ((len(mesh2.faces) - len(mesh1.faces)) / len(mesh1.faces) * 100) if len(mesh1.faces) > 0 else 0
                    },
                    'vertices': {
                        'v1': len(mesh1.vertices),
                        'v2': len(mesh2.vertices),
                        'delta': len(mesh2.vertices) - len(mesh1.vertices),
                        'percent': ((len(mesh2.vertices) - len(mesh1.vertices)) / len(mesh1.vertices) * 100) if len(mesh1.vertices) > 0 else 0
                    },
                    'volume': {
                        # Not 0 for an open mesh: trimesh answers `is_volume` False there, and an
                        # open surface has no volume at all rather than an empty one. The dialog
                        # shows which of the two a cell means.
                        'v1': float(mesh1.volume) if mesh1.is_volume else None,
                        'v2': float(mesh2.volume) if mesh2.is_volume else None,
                        'delta': (float(mesh2.volume - mesh1.volume)
                                  if mesh1.is_volume and mesh2.is_volume else None)
                    },
                    'bounds': {
                        'v1': mesh1.bounds.tolist(),
                        'v2': mesh2.bounds.tolist()
                    }
                },
                'geometry_diff': self._calculate_geometry_diff(mesh1, mesh2)
            }
            
            return comparison
            
        except Exception as e:
            logger.error(f"Error comparing versions: {e}")
            return {'error': str(e)}
    
    def restore_version(self, version_id: int, target_path: Optional[str] = None) -> bool:
        """
        Restore a previous version.
        
        Args:
            version_id: Version ID to restore
            target_path: Optional target path (default: original model path)
            
        Returns:
            True if successful
        """
        try:
            version = self._get_version_by_id(version_id)
            
            if not version:
                logger.error(f"Version {version_id} not found")
                return False
            
            snapshot_path = Path(version['snapshot_path'])
            
            if not snapshot_path.exists():
                logger.error(f"Snapshot file not found: {snapshot_path}")
                return False
            
            # Determine target path
            if target_path is None:
                target_path = version['model_path']
            
            target_path = Path(target_path)
            
            # Create backup of current version before restoring
            if target_path.exists():
                self.save_version(str(target_path), commit_message="Auto-backup before restore", auto=True)
            
            # Copy snapshot to target
            shutil.copy2(snapshot_path, target_path)
            
            logger.info(f"Restored version {version['version_number']} to {target_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error restoring version: {e}")
            return False
    
    def create_branch(self, model_path: str, branch_name: str, 
                     from_version_id: Optional[int] = None) -> bool:
        """
        Create a new branch for experimental changes.
        
        Args:
            model_path: Model path
            branch_name: Name of new branch
            from_version_id: Optional version to branch from (default: latest)
            
        Returns:
            True if successful
        """
        try:
            # Check if branch already exists
            branches = self.get_branches(model_path)
            if branch_name in branches:
                logger.warning(f"Branch '{branch_name}' already exists")
                return False
            
            # Get source version
            if from_version_id:
                source_version = self._get_version_by_id(from_version_id)
            else:
                source_version = self._get_latest_version(model_path)
            
            if not source_version:
                logger.error("No source version to branch from")
                return False
            
            # Create a new version entry for the branch start
            # It points to the same snapshot but has a new branch name
            # We increment version number globally for the file
            version_number = self._get_next_version_number(model_path)
            
            # Copy metrics from source
            metrics = {
                'polygon_count': source_version['polygon_count'],
                'vertex_count': source_version['vertex_count'],
                'file_size': source_version['file_size'],
                'is_watertight': source_version['is_watertight']
            }
            
            self._save_version_to_db(
                model_path=model_path,
                version_number=version_number,
                file_hash=source_version['file_hash'],
                snapshot_path=source_version['snapshot_path'],
                thumbnail_path=source_version['thumbnail_path'],
                timestamp=datetime.now().isoformat(),
                commit_message=f"Created branch '{branch_name}' from v{source_version['version_number']}",
                author="System",
                branch=branch_name,
                parent_version_id=source_version['id'],
                metrics=metrics,
                diff_metrics={'polygons_delta': 0, 'vertices_delta': 0, 'volume_delta': 0}
            )
            
            logger.info(f"Created branch '{branch_name}' from version {source_version['version_number']}")
            return True
            
        except Exception as e:
            logger.error(f"Error creating branch: {e}")
            return False

    def get_branches(self, model_path: str) -> List[str]:
        """Get list of branches for a model."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT DISTINCT branch FROM versions
            WHERE model_path = ?
            ORDER BY branch
        ''', (str(model_path),))
        
        branches = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        if not branches:
            return ['main']
            
        return branches
    
    def add_tag(self, version_id: int, tag_name: str):
        """
        Add a tag to a version (e.g., 'release', 'approved', 'milestone').
        
        Args:
            version_id: Version ID
            tag_name: Tag name
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO version_tags (version_id, tag_name)
                VALUES (?, ?)
            ''', (version_id, tag_name))
            conn.commit()
            logger.info(f"Tag '{tag_name}' added to version {version_id}")
        except sqlite3.IntegrityError:
            logger.warning(f"Tag '{tag_name}' already exists for version {version_id}")
        finally:
            conn.close()
    
    def get_tagged_versions(self, model_path: str, tag_name: str) -> List[Dict]:
        """Get all versions with a specific tag."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT v.* FROM versions v
            JOIN version_tags t ON v.id = t.version_id
            WHERE v.model_path = ? AND t.tag_name = ?
            ORDER BY v.version_number DESC
        ''', (str(model_path), tag_name))
        
        versions = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return versions
    
    def export_version_timeline(self, model_path: str, output_path: str):
        """
        Export version history to HTML timeline.
        
        Args:
            model_path: Model path
            output_path: Output HTML file path
        """
        versions = self.get_version_history(model_path)
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Version Timeline - {Path(model_path).name}</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
                .timeline {{ position: relative; padding: 20px 0; }}
                .version {{ background: white; margin: 20px 0; padding: 15px; 
                           border-left: 4px solid #3498db; border-radius: 3px; }}
                .version-header {{ display: flex; justify-content: space-between; }}
                .version-number {{ font-size: 24px; font-weight: bold; color: #3498db; }}
                .timestamp {{ color: #7f8c8d; }}
                .metrics {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-top: 10px; }}
                .metric {{ background: #ecf0f1; padding: 8px; border-radius: 3px; }}
                .delta-positive {{ color: #e74c3c; }}
                .delta-negative {{ color: #27ae60; }}
            </style>
        </head>
        <body>
            <h1>📅 Version Timeline: {Path(model_path).name}</h1>
            <p>Total versions: {len(versions)}</p>
            <div class="timeline">
        """
        
        for version in versions:
            delta_polys = version.get('polygons_delta')
            delta_class = 'delta-positive' if delta_polys and delta_polys > 0 else \
                          'delta-negative' if delta_polys and delta_polys < 0 else ''
    
            
            html += f"""
            <div class="version">
                <div class="version-header">
                    <span class="version-number">v{version['version_number']}</span>
                    <span class="timestamp">{version['timestamp']}</span>
                </div>
                <p><strong>Message:</strong> {version['commit_message']}</p>
                <p><strong>Author:</strong> {version.get('author', 'Unknown')}</p>
                <div class="metrics">
                    <div class="metric">
                        <strong>Polygons:</strong> {describe_polygon_count(version)}
                        {f'<span class="{delta_class}"> ({delta_polys:+,})</span>' if delta_polys else ''}
                    </div>
                    <div class="metric">
                        <strong>Vertices:</strong> {version['vertex_count']:,}
                    </div>
                    <div class="metric">
                        <strong>File Size:</strong> {version['file_size'] / 1024:.1f} KB
                    </div>
                </div>
            </div>
            """
        
        html += """
            </div>
        </body>
        </html>
        """
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)
        
        logger.info(f"Version timeline exported to: {output_path}")
    
    def _calculate_file_hash(self, file_path: Path) -> str:
        """Calculate SHA256 hash of file."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    
    def _is_duplicate_version(self, model_path: str, file_hash: str, branch: str = 'main') -> bool:
        """Check if this exact version already exists in the branch."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT COUNT(*) FROM versions
            WHERE model_path = ? AND file_hash = ? AND branch = ?
        ''', (model_path, file_hash, branch))
        
        count = cursor.fetchone()[0]
        conn.close()
        
        return count > 0
    
    def _get_next_version_number(self, model_path: str) -> int:
        """Get next version number for a model."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT MAX(version_number) FROM versions
            WHERE model_path = ?
        ''', (model_path,))
        
        result = cursor.fetchone()[0]
        conn.close()
        
        return (result or 0) + 1
    
    def _get_latest_version(self, model_path: str, branch: str = None) -> Optional[Dict]:
        """Get the latest version of a model."""
        if branch:
            versions = self.get_version_history(model_path, branch)
        else:
            # Get absolute latest regardless of branch
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM versions
                WHERE model_path = ?
                ORDER BY version_number DESC LIMIT 1
            ''', (str(model_path),))
            row = cursor.fetchone()
            conn.close()
            return dict(row) if row else None
            
        return versions[0] if versions else None
    
    def _get_version_by_id(self, version_id: int) -> Optional[Dict]:
        """Get version info by ID."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM versions WHERE id = ?', (version_id,))
        row = cursor.fetchone()
        conn.close()
        
        return dict(row) if row else None
    
    def _generate_thumbnail(self, snapshot_path) -> Optional[str]:
        """Draw the version's picture with the app's one raster, or record that there is none.

        The file is named for the snapshot it depicts, which is also how `create_branch`
        points a new row at the source version's picture. The name this call used to build
        came from the model's stem and its version number, so two files called `chair.obj`
        in different folders both wrote `chair_v1.png`, and the second commit replaced the
        first row's picture with the other chair's.

        The window used to be opened here - `o3d.visualization.Visualizer` plus
        `capture_screen_image` - on the caller's thread, which for the Versions pane's Commit
        button is the interface thread, and its `destroy_window` sat after the capture, so any
        raise in between left the window alive.

        `rendered` is the raster's own verdict: a model it could not read still gets a file,
        a wireframe badge that looks like a crate, so recording that path would tell the
        timeline the version has a picture of the model when it has a picture of nothing.
        """
        thumb_path = self.thumbnails_dir / (Path(snapshot_path).stem + '.png')
        outcome = generate_3d_thumbnail(str(snapshot_path), str(thumb_path), size=256) or {}
        if not outcome.get('rendered'):
            thumb_path.unlink(missing_ok=True)
            logger.warning(f"No picture for {thumb_path.name}: "
                           f"{outcome.get('error', 'the raster gave no verdict')}")
            return None
        return str(thumb_path)
    
    def _calculate_diff(self, metrics: Dict, parent_version: Dict) -> Dict:
        """Subtract the parent row from the numbers just measured.

        A field is None when one side has no number for it: a point cloud has no faces, and a
        volume needs both meshes to be closed. The bare `except` this replaces returned 0 for
        all three whatever happened, so a commit whose parent snapshot had been deleted - or
        whose parent had been measured by a backend that could not read a Scene - reported "no
        change", and the pane's green and red colouring showed that guess as a fact.

        The counts come from the parent's row rather than from a second read of its file: the
        row is the number the timeline prints, and a delta that disagreed with the two numbers
        shown above it would be a third opinion, not a measurement.
        """
        diff = {
            'polygons_delta': _delta(metrics.get('polygon_count'),
                                     parent_version.get('polygon_count')),
            'vertices_delta': _delta(metrics.get('vertex_count'),
                                     parent_version.get('vertex_count')),
            'volume_delta': None,
        }

        mesh = metrics.get('mesh')
        if mesh is None or not mesh.is_volume:
            return diff
        try:
            parent_mesh = _normalise(trimesh.load(parent_version['snapshot_path']))
        except Exception as e:
            logger.warning(f"Volume change against v{parent_version['version_number']} "
                           f"not measured: its snapshot could not be read ({e})")
            return diff
        if parent_mesh is None or not parent_mesh.is_volume:
            return diff
        diff['volume_delta'] = float(mesh.volume - parent_mesh.volume)
        return diff
    
    def _calculate_geometry_diff(self, mesh1, mesh2) -> Dict:
        """Calculate detailed geometry differences."""
        diff = {
            'vertices_moved': 0,
            'vertices_added': max(0, len(mesh2.vertices) - len(mesh1.vertices)),
            'vertices_removed': max(0, len(mesh1.vertices) - len(mesh2.vertices)),
            'topology_changed': len(mesh1.faces) != len(mesh2.faces)
        }
        
        # Center of mass shift
        if hasattr(mesh1, 'center_mass') and hasattr(mesh2, 'center_mass'):
            shift = np.linalg.norm(mesh2.center_mass - mesh1.center_mass)
            diff['center_of_mass_shift'] = float(shift)
            
        # Bounding box change
        if hasattr(mesh1, 'bounds') and hasattr(mesh2, 'bounds'):
            bbox_diff = np.abs(mesh2.bounds - mesh1.bounds)
            diff['bbox_change'] = bbox_diff.tolist()
            
        return diff
    
    def _save_version_to_db(self, **kwargs) -> int:
        """Save version info to database."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        metrics = kwargs.get('metrics', {})
        diff_metrics = kwargs.get('diff_metrics', {})
        
        cursor.execute('''
            INSERT INTO versions (
                model_path, version_number, file_hash, snapshot_path, thumbnail_path,
                timestamp, commit_message, author, branch, parent_version_id,
                polygon_count, vertex_count, file_size, is_watertight,
                polygons_delta, vertices_delta, volume_delta
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            kwargs['model_path'],
            kwargs['version_number'],
            kwargs['file_hash'],
            kwargs['snapshot_path'],
            kwargs.get('thumbnail_path'),
            kwargs['timestamp'],
            kwargs['commit_message'],
            kwargs['author'],
            kwargs.get('branch', 'main'),
            kwargs.get('parent_version_id'),
            # No default for the three geometry facts. A count the file does not have is
            # recorded as NULL, which is the row saying "this file has no faces"; the 0 and
            # False this replaces were the row inventing a flat-shaded, open model out of a
            # point cloud, and a first version's delta of 0 claimed equality with a parent it
            # does not have.
            metrics.get('polygon_count'),
            metrics.get('vertex_count'),
            metrics.get('file_size', 0),
            metrics.get('is_watertight'),
            diff_metrics.get('polygons_delta'),
            diff_metrics.get('vertices_delta'),
            diff_metrics.get('volume_delta')
        ))
        
        version_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return version_id


if __name__ == "__main__":
    # Demo usage
    vcs = AssetVersionControl(output_dir())
    
    # Save version
    version_id = vcs.save_version("model.obj", commit_message="Initial version", author="Artist")
    
    # Get history
    history = vcs.get_version_history("model.obj")
    print(f"Total versions: {len(history)}")
    
    # Compare versions
    if len(history) >= 2:
        comparison = vcs.compare_versions(history[1]['id'], history[0]['id'])
        print(f"Polygon change: {comparison['changes']['polygons']['delta']}")
