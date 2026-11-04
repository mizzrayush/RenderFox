"""
Library backend for RenderFox Library tab.

- SQLite database for models, folders, collections, and metadata
- Async folder scanning with progress signals
- Trimesh-based geometry stats extraction (verts/faces/area/volume)
- Search and quick filters (recent, favorites, high poly, textured, broken)
- Import/Export and basic DB maintenance
- Thumbnail generation placeholder

Usage from UI (example):

    from src.core.library_manager import LibraryManager, LibraryScannerWorker, SearchQuery

    self.library = LibraryManager()
    self.library.library_changed.connect(self.refresh_ui)
    self.library.scan_progress.connect(lambda p, m: self.status_label.setText(m))

    # Add folder and scan
    self.library.add_folder(path)
    worker = LibraryScannerWorker(self.library)
    worker.start()

    # Import files directly
    self.library.import_files([".../file.obj", ".../file.ply"])  
    models = self.library.get_models()

"""
from __future__ import annotations

import os
import logging
import re
import json
import time
import sqlite3
import hashlib
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from src.processing.lod_generator import LODGenerator, LODSettings

# PyQt6 for signals and threads
from PyQt6.QtCore import QObject, pyqtSignal, QThread
from PyQt6.QtGui import QPixmap, QPainter, QColor, QFont, QBrush, QPen
from PyQt6.QtCore import Qt
from src.core.worker_base import SafeWorker

# Geometry stats via trimesh
try:
    import trimesh
    import numpy as np
except Exception:  # pragma: no cover
    trimesh = None
    np = None

SUPPORTED_MODEL_EXTS = {
    ".obj", ".ply", ".stl", ".gltf", ".glb", ".fbx", ".dae", ".x3d"
}

logger = logging.getLogger(__name__)


def _now_ts() -> int:
    return int(time.time())


def _file_hash(path: str, block_size: int = 1024 * 1024) -> str:
    """Fast-ish hash of file contents for change detection (first/last chunk + size)."""
    try:
        size = os.path.getsize(path)
        h = hashlib.sha1()
        h.update(str(size).encode("utf-8"))
        with open(path, "rb") as f:
            head = f.read(block_size)
            if head:
                h.update(head)
            if size > block_size:
                f.seek(max(0, size - block_size))
                tail = f.read(block_size)
                if tail:
                    h.update(tail)
        return h.hexdigest()
    except Exception:
        return ""


@dataclass
class SearchQuery:
    text: str = ""
    tags: List[str] = None
    author: str = ""
    file_type: str = ""  # ext like .obj or empty
    min_poly: int = 0
    max_poly: int = 10_000_000
    min_size_mb: float = 0.0
    max_size_mb: float = 1000.0
    date_from_ts: Optional[int] = None
    date_to_ts: Optional[int] = None
    sort_by: str = "name"  # name | date_added | file_size | poly_count | rating
    sort_desc: bool = False

    def __post_init__(self):
        if self.tags is None:
            self.tags = []


class LibraryManager(QObject):
    # Signals for UI
    library_changed = pyqtSignal()
    scan_progress = pyqtSignal(int, str)  # percent, message
    scan_finished = pyqtSignal(int, int)  # added, updated
    error_occurred = pyqtSignal(str)
    thumbnail_ready = pyqtSignal(str, str)  # model_path, thumbnail_path
    selected_for_work = pyqtSignal(str)  # file path selected for work

    def __init__(self, db_path: Optional[str] = None, thumbnails_dir: Optional[str] = None):
        super().__init__()
        base_dir = os.getcwd()
        out_dir = os.path.join(base_dir, "output")
        os.makedirs(out_dir, exist_ok=True)
        self.db_path = db_path or os.path.join(out_dir, "library.db")
        self.thumbs_dir = thumbnails_dir or os.path.join(out_dir, "thumbnails")
        os.makedirs(self.thumbs_dir, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    # ---------------------- DB setup ----------------------
    def _init_db(self):
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS models (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              path TEXT UNIQUE,
              name TEXT,
              ext TEXT,
              size_mb REAL,
              date_added INTEGER,
              date_modified INTEGER,
              file_hash TEXT,
              vertices INTEGER,
              faces INTEGER,
              edges INTEGER,
              watertight INTEGER,
              winding_consistent INTEGER,
              surface_area REAL,
              volume REAL,
              bounds TEXT,
              tags TEXT,
              description TEXT,
              author TEXT,
              license TEXT,
              rating INTEGER DEFAULT 3,
              favorite INTEGER DEFAULT 0,
              textured INTEGER DEFAULT 0,
              has_uv INTEGER DEFAULT 0,
              broken INTEGER DEFAULT 0,
              thumbnail TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS library_folders (
              path TEXT PRIMARY KEY,
              recursive INTEGER DEFAULT 1,
              is_active INTEGER DEFAULT 1
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS collections (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT UNIQUE,
              description TEXT,
              is_smart INTEGER DEFAULT 0,
              criteria TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS collection_items (
              collection_id INTEGER,
              model_id INTEGER,
              PRIMARY KEY (collection_id, model_id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS model_lods (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              model_id INTEGER,
              lod_level INTEGER,
              path TEXT,
              faces INTEGER,
              vertices INTEGER,
              size_mb REAL,
              FOREIGN KEY(model_id) REFERENCES models(id) ON DELETE CASCADE
            )
            """
        )
        
        # Migrate existing library_folders table to add is_active column if it doesn't exist
        try:
            cur.execute("SELECT is_active FROM library_folders LIMIT 1")
        except sqlite3.OperationalError:
            cur.execute("ALTER TABLE library_folders ADD COLUMN is_active INTEGER DEFAULT 1")
        
        # Migrate collections columns
        for col, col_type in [("description", "TEXT"), ("is_smart", "INTEGER DEFAULT 0"), ("criteria", "TEXT")]:
            try:
                cur.execute(f"SELECT {col} FROM collections LIMIT 1")
            except sqlite3.OperationalError:
                cur.execute(f"ALTER TABLE collections ADD COLUMN {col} {col_type}")
        
        self.conn.commit()

    # ---------------------- Folders ----------------------
    def add_folder(self, path: str, recursive: bool = True) -> bool:
        if not path:
            return False
        try:
            cur = self.conn.cursor()
            cur.execute(
                "INSERT OR REPLACE INTO library_folders(path, recursive) VALUES(?, ?)",
                (os.path.abspath(path), 1 if recursive else 0),
            )
            self.conn.commit()
            self.library_changed.emit()
            return True
        except Exception as e:
            self.error_occurred.emit(f"add_folder failed: {e}")
            return False

    def remove_folder(self, path: str) -> bool:
        try:
            cur = self.conn.cursor()
            cur.execute("DELETE FROM library_folders WHERE path=?", (os.path.abspath(path),))
            self.conn.commit()
            self.library_changed.emit()
            return True
        except Exception as e:
            self.error_occurred.emit(f"remove_folder failed: {e}")
            return False

    def list_folders(self) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute("SELECT path, recursive FROM library_folders ORDER BY path")
        return [dict(row) for row in cur.fetchall()]

    def get_folders(self) -> List[str]:
        """Get list of library folder paths (for UI compatibility)."""
        folders = self.list_folders()
        return [folder["path"] for folder in folders]

    def get_active_folders(self) -> List[Dict[str, Any]]:
        """Get list of active library folders only."""
        cur = self.conn.cursor()
        cur.execute("SELECT path, recursive, is_active FROM library_folders WHERE is_active = 1 ORDER BY path")
        return [dict(row) for row in cur.fetchall()]

    def get_inactive_folders(self) -> List[Dict[str, Any]]:
        """Get list of inactive (closed) library folders."""
        cur = self.conn.cursor()
        cur.execute("SELECT path, recursive, is_active FROM library_folders WHERE is_active = 0 ORDER BY path")
        return [dict(row) for row in cur.fetchall()]

    def close_folder(self, path: str) -> bool:
        """Close a folder (make it inactive) but preserve all data."""
        try:
            cur = self.conn.cursor()
            cur.execute("UPDATE library_folders SET is_active = 0 WHERE path = ?", (os.path.abspath(path),))
            if cur.rowcount > 0:
                self.conn.commit()
                self.library_changed.emit()
                return True
            return False
        except Exception as e:
            self.error_occurred.emit(f"close_folder failed: {e}")
            return False

    def open_folder(self, path: str) -> bool:
        """Open a folder (make it active) to show its models again."""
        try:
            cur = self.conn.cursor()
            cur.execute("UPDATE library_folders SET is_active = 1 WHERE path = ?", (os.path.abspath(path),))
            if cur.rowcount > 0:
                self.conn.commit()
                self.library_changed.emit()
                return True
            return False
        except Exception as e:
            self.error_occurred.emit(f"open_folder failed: {e}")
            return False

    def is_folder_active(self, path: str) -> bool:
        """Check if a folder is currently active."""
        try:
            cur = self.conn.cursor()
            cur.execute("SELECT is_active FROM library_folders WHERE path = ?", (os.path.abspath(path),))
            row = cur.fetchone()
            return bool(row[0]) if row else False
        except Exception:
            return False

    # ---------------------- Import/Scan ----------------------
    def import_files(self, file_paths: Sequence[str]) -> Tuple[int, int]:
        """Returns (newly indexed, already known) - see _add_or_update_model."""
        added, updated = 0, 0
        for fp in file_paths:
            ok, is_new = self._add_or_update_model(fp)
            if ok:
                if is_new:
                    added += 1
                else:
                    updated += 1
        if added or updated:
            self.library_changed.emit()
        return added, updated

    def scan(self) -> Tuple[int, int]:
        """Scan all registered folders and add/update models."""
        folders = self.list_folders()
        all_files: List[str] = []
        for f in folders:
            base = f["path"]
            rec = bool(f.get("recursive", 1))
            if not os.path.isdir(base):
                continue
            if rec:
                for root, _, files in os.walk(base):
                    for name in files:
                        if self._is_model_file(name):
                            all_files.append(os.path.join(root, name))
            else:
                try:
                    for name in os.listdir(base):
                        full = os.path.join(base, name)
                        if os.path.isfile(full) and self._is_model_file(name):
                            all_files.append(full)
                except Exception:
                    pass

        total = len(all_files)
        added, updated = 0, 0
        for i, fp in enumerate(all_files):
            pct = int((i + 1) * 100 / max(1, total))
            self.scan_progress.emit(pct, f"Scanning {os.path.basename(fp)} ({i+1}/{total})")
            ok, is_new = self._add_or_update_model(fp)
            if ok:
                if is_new:
                    added += 1
                else:
                    updated += 1
        if total == 0:
            self.scan_progress.emit(100, "No model files found in library folders")
        self.conn.commit()
        self.library_changed.emit()
        self.scan_finished.emit(added, updated)
        return added, updated

    def _is_model_file(self, filename: str) -> bool:
        ext = os.path.splitext(filename)[1].lower()
        return ext in SUPPORTED_MODEL_EXTS

    def _add_or_update_model(self, file_path: str) -> Tuple[bool, bool]:
        """Index one file as (recorded, row_was_new); re-importing a known file is (True, False)."""
        try:
            if not file_path:
                return False, False
            path = os.path.abspath(file_path)
            if not os.path.isfile(path) or not self._is_model_file(path):
                return False, False

            size_mb = os.path.getsize(path) / (1024 * 1024)
            mtime = int(os.path.getmtime(path))
            name = os.path.basename(path)
            ext = os.path.splitext(path)[1].lower()
            file_hash = _file_hash(path)

            # Check existing
            cur = self.conn.cursor()
            cur.execute("SELECT id, file_hash FROM models WHERE path=?", (path,))
            row = cur.fetchone()

            # Compute (lightweight) geometry stats
            stats = self._compute_geometry_stats(path)

            # Upsert
            if row is None:
                cur.execute(
                    """
                    INSERT INTO models (
                      path, name, ext, size_mb, date_added, date_modified, file_hash,
                      vertices, faces, edges, watertight, winding_consistent, surface_area,
                      volume, bounds, tags, description, author, license, rating, favorite,
                      textured, has_uv, broken, thumbnail
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '', '', '', 3, 0, ?, ?, 0, '')
                    """,
                    (
                        path,
                        name,
                        ext,
                        size_mb,
                        _now_ts(),
                        mtime,
                        file_hash,
                        stats.get("vertices"),
                        stats.get("faces"),
                        stats.get("edges"),
                        1 if stats.get("is_watertight") else 0,
                        1 if stats.get("is_winding_consistent") else 0,
                        stats.get("surface_area"),
                        stats.get("volume"),
                        json.dumps(stats.get("bounds")) if stats.get("bounds") is not None else None,
                        1 if stats.get("textured") else 0,
                        1 if stats.get("has_uv") else 0,
                    ),
                )
                model_id = cur.lastrowid
                # Thumbnail placeholder
                thumb = self._ensure_thumbnail_placeholder(path)
                cur.execute("UPDATE models SET thumbnail=? WHERE id=?", (thumb, model_id))
                self.thumbnail_ready.emit(path, thumb)
                self.conn.commit()
                return True, True
            else:
                model_id = row["id"]
                cur.execute(
                    """
                    UPDATE models SET
                      name=?, ext=?, size_mb=?, date_modified=?, file_hash=?,
                      vertices=?, faces=?, edges=?, watertight=?, winding_consistent=?,
                      surface_area=?, volume=?, bounds=?, textured=?, has_uv=?
                    WHERE id=?
                    """,
                    (
                        name,
                        ext,
                        size_mb,
                        mtime,
                        file_hash,
                        stats.get("vertices"),
                        stats.get("faces"),
                        stats.get("edges"),
                        1 if stats.get("is_watertight") else 0,
                        1 if stats.get("is_winding_consistent") else 0,
                        stats.get("surface_area"),
                        stats.get("volume"),
                        json.dumps(stats.get("bounds")) if stats.get("bounds") is not None else None,
                        1 if stats.get("textured") else 0,
                        1 if stats.get("has_uv") else 0,
                        model_id,
                    ),
                )
                # ensure thumbnail exists
                cur.execute("SELECT thumbnail FROM models WHERE id=?", (model_id,))
                trow = cur.fetchone()
                if trow and (not trow[0] or not os.path.exists(trow[0])):
                    thumb = self._ensure_thumbnail_placeholder(path)
                    cur.execute("UPDATE models SET thumbnail=? WHERE id=?", (thumb, model_id))
                    self.thumbnail_ready.emit(path, thumb)
                self.conn.commit()
                return True, False
        except Exception as e:
            self.error_occurred.emit(f"_add_or_update_model failed for {file_path}: {e}")
            return False, False

    def _compute_geometry_stats(self, file_path: str) -> Dict[str, Any]:
        stats: Dict[str, Any] = {
            "vertices": None,
            "faces": None,
            "edges": None,
            "is_watertight": False,
            "is_winding_consistent": False,
            "surface_area": None,
            "volume": None,
            "bounds": None,
            "textured": False,
            "has_uv": False,
        }
        if trimesh is None:
            return stats
        try:
            obj = trimesh.load(file_path)
            mesh = self._as_trimesh(obj)
            if mesh is None:
                return stats
            stats.update({
                "vertices": int(len(mesh.vertices)),
                "faces": int(len(mesh.faces)),
                "edges": int(len(mesh.edges)) if hasattr(mesh, "edges") else None,
                "is_watertight": bool(getattr(mesh, "is_watertight", False)),
                "is_winding_consistent": bool(getattr(mesh, "is_winding_consistent", False)),
                "surface_area": float(mesh.area) if hasattr(mesh, "area") else None,
                "volume": float(mesh.volume) if getattr(mesh, "is_volume", False) else None,
                "bounds": mesh.bounds.tolist() if hasattr(mesh, "bounds") else None,
            })
            vis = getattr(mesh, "visual", None)
            if vis is not None:
                try:
                    if getattr(vis, "uv", None) is not None:
                        stats["has_uv"] = True
                except Exception:
                    pass
                try:
                    kind = getattr(vis, "kind", None)
                    if kind == "texture":
                        stats["textured"] = True
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Failed to compute geometry stats for {file_path}: {e}")
        return stats

    @staticmethod
    def _as_trimesh(obj: Any):
        if trimesh is None:
            return None
        if isinstance(obj, trimesh.Trimesh):
            return obj
        if isinstance(obj, trimesh.Scene):
            try:
                dumped = obj.dump()
                if isinstance(dumped, (list, tuple)):
                    return trimesh.util.concatenate(dumped) if dumped else None
                if isinstance(dumped, dict):
                    return trimesh.util.concatenate(list(dumped.values())) if dumped else None
                if isinstance(dumped, trimesh.Trimesh):
                    return dumped
            except Exception as e:
                logger.debug(f"Failed to dump scene in _as_trimesh: {e}")
            try:
                geoms = list(obj.geometry.values()) if hasattr(obj, "geometry") else []
                return trimesh.util.concatenate(geoms) if geoms else None
            except Exception as e:
                logger.debug(f"Failed to extract geometry from scene: {e}")
                return None

    @property
    def db_connection(self):
        """Compatibility property for UI accessing db_connection."""
        return self.conn

    def get_collections(self) -> List[Dict[str, Any]]:
        """Alias for list_collections()."""
        return self.list_collections()

    def get_models_by_collection(self, collection_name: str) -> List[Dict[str, Any]]:
        """Alias for get_collection_items()."""
        return self.get_collection_items(collection_name)

    def check_integrity(self) -> Dict[str, Any]:
        """Verify database integrity and count valid/missing files."""
        try:
            cur = self.conn.cursor()
            cur.execute("SELECT id, path FROM models")
            rows = cur.fetchall()
            missing = 0
            valid = 0
            for r in rows:
                if not os.path.exists(r["path"]):
                    missing += 1
                else:
                    valid += 1
            return {"total": len(rows), "valid": valid, "missing": missing}
        except Exception as e:
            return {"total": 0, "valid": 0, "missing": 0, "error": str(e)}

    # ---------------------- Query/Search ----------------------
    def get_models(self, limit: int = 1000) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT m.* FROM models m
            WHERE NOT EXISTS (
                SELECT 1 FROM library_folders lf 
                WHERE lf.is_active = 0 AND (m.path LIKE lf.path || '%' OR m.path LIKE lf.path || '\\%')
            )
            ORDER BY m.date_added DESC LIMIT ?
            """, (limit,)
        )
        return [dict(row) for row in cur.fetchall()]

    def search_models(self, q: SearchQuery) -> List[Dict[str, Any]]:
        where: List[str] = [
            """NOT EXISTS (
                SELECT 1 FROM library_folders lf 
                WHERE lf.is_active = 0 AND (m.path LIKE lf.path || '%' OR m.path LIKE lf.path || '\\%')
            )"""
        ]
        params: List[Any] = []
        
        if q.text:
            where.append("(LOWER(m.name) LIKE ? OR LOWER(m.description) LIKE ? OR LOWER(m.tags) LIKE ?)")
            like = f"%{q.text.lower()}%"
            params += [like, like, like]
        if q.tags:
            for tag in q.tags:
                where.append("LOWER(m.tags) LIKE ?")
                params.append(f"%{tag.lower()}%")
        if q.author:
            where.append("LOWER(m.author) LIKE ?")
            params.append(f"%{q.author.lower()}%")
        if q.file_type:
            where.append("m.ext = ?")
            params.append(q.file_type.lower() if q.file_type.startswith(".") else f".{q.file_type.lower()}")
        if q.min_poly is not None:
            where.append("(m.faces IS NULL OR m.faces >= ?)")
            params.append(int(q.min_poly))
        if q.max_poly is not None:
            where.append("(m.faces IS NULL OR m.faces <= ?)")
            params.append(int(q.max_poly))
        where.append("m.size_mb >= ?")
        params.append(float(q.min_size_mb))
        where.append("m.size_mb <= ?")
        params.append(float(q.max_size_mb))
        if q.date_from_ts:
            where.append("m.date_added >= ?")
            params.append(int(q.date_from_ts))
        if q.date_to_ts:
            where.append("m.date_added <= ?")
            params.append(int(q.date_to_ts))

        where_sql = " WHERE " + " AND ".join(where)
        sort_map = {
            "name": "m.name",
            "date_added": "m.date_added",
            "file_size": "m.size_mb",
            "poly_count": "m.faces",
            "rating": "m.rating",
        }
        order_col = sort_map.get(q.sort_by, "m.name")
        order_dir = "DESC" if q.sort_desc else "ASC"
        sql = f"""
            SELECT m.* FROM models m
            {where_sql} ORDER BY {order_col} {order_dir} LIMIT 2000
        """
        cur = self.conn.cursor()
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]

    # Quick filters
    def get_recent(self, days: int = 7) -> List[Dict[str, Any]]:
        cutoff = _now_ts() - days * 86400
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT m.* FROM models m
            WHERE m.date_added >= ? AND NOT EXISTS (
                SELECT 1 FROM library_folders lf 
                WHERE lf.is_active = 0 AND (m.path LIKE lf.path || '%' OR m.path LIKE lf.path || '\\%')
            )
            ORDER BY m.date_added DESC
            """, (cutoff,)
        )
        return [dict(row) for row in cur.fetchall()]

    def get_favorites(self) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT m.* FROM models m
            WHERE m.favorite=1 AND NOT EXISTS (
                SELECT 1 FROM library_folders lf 
                WHERE lf.is_active = 0 AND (m.path LIKE lf.path || '%' OR m.path LIKE lf.path || '\\%')
            )
            ORDER BY m.name
            """
        )
        return [dict(row) for row in cur.fetchall()]

    def get_high_poly(self, face_threshold: int = 10_000) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT m.* FROM models m
            WHERE m.faces IS NOT NULL AND m.faces >= ? AND NOT EXISTS (
                SELECT 1 FROM library_folders lf 
                WHERE lf.is_active = 0 AND (m.path LIKE lf.path || '%' OR m.path LIKE lf.path || '\\%')
            )
            ORDER BY m.faces DESC
            """, (face_threshold,)
        )
        return [dict(row) for row in cur.fetchall()]

    def get_textured(self) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT m.* FROM models m
            WHERE m.textured=1 AND NOT EXISTS (
                SELECT 1 FROM library_folders lf 
                WHERE lf.is_active = 0 AND (m.path LIKE lf.path || '%' OR m.path LIKE lf.path || '\\%')
            )
            ORDER BY m.name
            """
        )
        return [dict(row) for row in cur.fetchall()]

    def get_broken(self) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT m.* FROM models m
            WHERE m.broken=1 AND NOT EXISTS (
                SELECT 1 FROM library_folders lf 
                WHERE lf.is_active = 0 AND (m.path LIKE lf.path || '%' OR m.path LIKE lf.path || '\\%')
            )
            ORDER BY m.date_modified DESC
            """
        )
        return [dict(row) for row in cur.fetchall()]

    # ---------------------- Metadata ----------------------
    def update_metadata(self, path: str, data: Dict[str, Any]) -> bool:
        try:
            cols = []
            params: List[Any] = []
            for key in ("name", "description", "tags", "author", "license", "rating", "favorite", "broken"):
                if key in data:
                    cols.append(f"{key}=?")
                    params.append(data[key])
            if not cols:
                return False
            params.append(os.path.abspath(path))
            sql = f"UPDATE models SET {', '.join(cols)} WHERE path=?"
            self.conn.execute(sql, params)
            self.conn.commit()
            self.library_changed.emit()
            return True
        except Exception as e:
            self.error_occurred.emit(f"update_metadata failed: {e}")
            return False

    def set_favorite(self, path: str, fav: bool) -> bool:
        return self.update_metadata(path, {"favorite": 1 if fav else 0})

    # ---------------------- Collections ----------------------
    def create_collection(self, name: str, description: Optional[str] = None) -> Optional[int]:
        try:
            cur = self.conn.cursor()
            cur.execute("INSERT OR IGNORE INTO collections(name, description) VALUES(?, ?)", (name, description or ""))
            self.conn.commit()
            self.library_changed.emit()
            cur.execute("SELECT id FROM collections WHERE name=?", (name,))
            row = cur.fetchone()
            return int(row[0]) if row else None
        except Exception as e:
            self.error_occurred.emit(f"create_collection failed: {e}")
            return None

    def delete_collection(self, name: str) -> bool:
        try:
            cur = self.conn.cursor()
            cur.execute("SELECT id FROM collections WHERE name=?", (name,))
            row = cur.fetchone()
            if not row:
                return False
            cid = int(row[0])
            cur.execute("DELETE FROM collection_items WHERE collection_id=?", (cid,))
            cur.execute("DELETE FROM collections WHERE id=?", (cid,))
            self.conn.commit()
            self.library_changed.emit()
            return True
        except Exception as e:
            self.error_occurred.emit(f"delete_collection failed: {e}")
            return False

    def list_collections(self) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM collections ORDER BY name")
        return [dict(row) for row in cur.fetchall()]

    def add_to_collection(self, path: str, collection_name: str) -> bool:
        try:
            cur = self.conn.cursor()
            cur.execute("SELECT id FROM models WHERE path=?", (os.path.abspath(path),))
            mrow = cur.fetchone()
            if not mrow:
                return False
            cur.execute("SELECT id FROM collections WHERE name=?", (collection_name,))
            crow = cur.fetchone()
            if not crow:
                cid = self.create_collection(collection_name)
            else:
                cid = int(crow[0])
            cur.execute("INSERT OR IGNORE INTO collection_items(collection_id, model_id) VALUES(?, ?)", (cid, int(mrow[0])))
            self.conn.commit()
            self.library_changed.emit()
            return True
        except Exception as e:
            self.error_occurred.emit(f"add_to_collection failed: {e}")
            return False

    def get_collection_items(self, collection_name: str) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT m.* FROM models m
            JOIN collections c ON c.name = ?
            JOIN collection_items ci ON ci.collection_id = c.id AND ci.model_id = m.id
            WHERE NOT EXISTS (
                SELECT 1 FROM library_folders lf 
                WHERE lf.is_active = 0 AND (m.path LIKE lf.path || '%' OR m.path LIKE lf.path || '\\%')
            )
            ORDER BY m.name
            """,
            (collection_name,),
        )
        return [dict(row) for row in cur.fetchall()]

    def close(self):
        """Close the database connection and release file locks."""
        try:
            if hasattr(self, 'conn') and self.conn:
                self.conn.close()
        except Exception:
            pass

    def check_integrity(self) -> Dict[str, Any]:
        """Alias for check_database_integrity."""
        return self.check_database_integrity()

    # ---------------------- Compatibility Aliases ----------------------
    def set_model_favorite(self, path: str, fav: bool) -> bool:
        """Alias for set_favorite."""
        return self.set_favorite(path, fav)

    def update_model_metadata(self, path: str, data: Dict[str, Any]) -> bool:
        """Alias for update_metadata."""
        return self.update_metadata(path, data)

    def add_model_to_collection(self, path: str, collection_name: str) -> bool:
        """Alias for add_to_collection."""
        return self.add_to_collection(path, collection_name)

    def remove_model(self, path: str, delete_file: bool = False) -> bool:
        """Remove a model from the library and optionally delete the file."""
        try:
            cur = self.conn.cursor()
            abs_path = os.path.abspath(path)
            
            # Get model ID
            cur.execute("SELECT id FROM models WHERE path=?", (abs_path,))
            row = cur.fetchone()
            if not row:
                return False
            
            model_id = row[0]
            
            # Remove from collections
            cur.execute("DELETE FROM collection_items WHERE model_id=?", (model_id,))
            
            # Remove from LODs
            cur.execute("DELETE FROM model_lods WHERE model_id=?", (model_id,))
            
            # Remove from models
            cur.execute("DELETE FROM models WHERE id=?", (model_id,))
            
            self.conn.commit()
            
            # Optionally delete file
            if delete_file and os.path.exists(abs_path):
                try:
                    os.remove(abs_path)
                except OSError as e:
                    logger.error(f"Failed to delete file {abs_path}: {e}")
                    # We still return True as the library entry is gone
            
            self.library_changed.emit()
            return True
            
        except Exception as e:
            self.error_occurred.emit(f"remove_model failed: {e}")
            return False

    # ---------------------- Maintenance ----------------------
    def cleanup_missing_files(self) -> int:
        cur = self.conn.cursor()
        cur.execute("SELECT id, path FROM models")
        rows = cur.fetchall()
        removed = 0
        for r in rows:
            if not os.path.exists(r["path"]):
                cur.execute("DELETE FROM models WHERE id=?", (int(r["id"]),))
                removed += 1
        if removed:
            self.conn.commit()
            self.library_changed.emit()
        return removed

    def clear_library(self) -> bool:
        """Clear all library data (models, collections, folders) from database."""
        try:
            cur = self.conn.cursor()
            
            # Clear all tables
            cur.execute("DELETE FROM collection_items")
            cur.execute("DELETE FROM collections")
            cur.execute("DELETE FROM models")
            cur.execute("DELETE FROM library_folders")
            
            # Reset auto-increment counters
            cur.execute("DELETE FROM sqlite_sequence WHERE name IN ('models', 'collections')")
            
            self.conn.commit()
            self.library_changed.emit()
            return True
        except Exception as e:
            self.error_occurred.emit(f"clear_library failed: {e}")
            return False

    def backup_database(self, dest_dir: Optional[str] = None) -> Optional[str]:
        try:
            dest_dir = dest_dir or os.path.join(os.getcwd(), "output")
            os.makedirs(dest_dir, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            target = os.path.join(dest_dir, f"library_backup_{ts}.db")
            self.conn.commit()
            with open(self.db_path, "rb") as src, open(target, "wb") as dst:
                dst.write(src.read())
            return target
        except Exception as e:
            self.error_occurred.emit(f"backup_database failed: {e}")
            return None

    def export_library(self, json_path: str) -> bool:
        try:
            data = {
                "export_ts": _now_ts(),
                "models": self.get_models(limit=10_000),
                "folders": self.list_folders(),
                "collections": self.list_collections(),
            }
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            self.error_occurred.emit(f"export_library failed: {e}")
            return False

    def vacuum(self) -> None:
        try:
            self.conn.execute("VACUUM")
            self.conn.commit()
        except Exception as e:
            self.error_occurred.emit(f"vacuum failed: {e}")

    def vacuum_database(self) -> bool:
        """Vacuum the database to reclaim space and optimize performance."""
        try:
            self.vacuum()
            return True
        except Exception as e:
            self.error_occurred.emit(f"vacuum_database failed: {e}")
            return False

    def optimize_database(self) -> bool:
        """Optimize the database by running ANALYZE and VACUUM."""
        try:
            self.conn.execute("ANALYZE")
            self.conn.execute("VACUUM")
            self.conn.commit()
            return True
        except Exception as e:
            self.error_occurred.emit(f"optimize_database failed: {e}")
            return False

    # ---------------------- Thumbnails ----------------------
    def _ensure_thumbnail_placeholder(self, model_path: str, force: bool = False) -> str:
        """Create a high quality shaded 3D visual thumbnail."""
        try:
            base = os.path.splitext(os.path.basename(model_path))[0]
            thumb_path = os.path.join(self.thumbs_dir, f"{base}.png")
            
            if force or not os.path.exists(thumb_path) or os.path.getsize(thumb_path) == 0:
                try:
                    from src.utils.thumbnail_renderer import generate_3d_thumbnail
                    success = generate_3d_thumbnail(model_path, thumb_path, size=256)
                    if success:
                        return thumb_path
                except Exception:
                    pass
            else:
                return thumb_path
                
            return thumb_path if os.path.exists(thumb_path) else ""
        except Exception as e:
            self.error_occurred.emit(f"thumbnail creation failed: {e}")
            return ""

    def refresh_thumbnail(self, model_path: str) -> str:
        """Rebuild one model's thumbnail and return its path ('' if nothing was written)."""
        return self._ensure_thumbnail_placeholder(model_path, force=True)

    def rebuild_all_thumbnails(self) -> int:
        """Rebuild all model thumbnails."""
        try:
            cur = self.conn.cursor()
            cur.execute("SELECT id, path FROM models")
            models = cur.fetchall()
            
            rebuilt = 0
            total = len(models)
            
            for i, model in enumerate(models):
                model_id, path = model
                if os.path.exists(path):
                    thumb_path = self._ensure_thumbnail_placeholder(path, force=True)
                    if thumb_path:
                        cur.execute("UPDATE models SET thumbnail = ? WHERE id = ?", (thumb_path, model_id))
                        rebuilt += 1
                        self.thumbnail_ready.emit(path, thumb_path)
                
                # Emit progress
                progress = int((i + 1) * 100 / total) if total > 0 else 100
                self.scan_progress.emit(progress, f"Rebuilding thumbnails... {i+1}/{total}")
            
            self.conn.commit()
            return rebuilt
        except Exception as e:
            self.error_occurred.emit(f"rebuild_all_thumbnails failed: {e}")
            return 0

    # ---------------------- Statistics Methods ----------------------
    def get_library_stats(self) -> Dict[str, Any]:
        """Get comprehensive library statistics."""
        try:
            cur = self.conn.cursor()
            
            # Basic counts
            cur.execute("SELECT COUNT(*) FROM models")
            total_models = cur.fetchone()[0]
            
            cur.execute("SELECT COUNT(*) FROM collections")
            total_collections = cur.fetchone()[0]
            
            cur.execute("SELECT COUNT(*) FROM library_folders")
            total_folders = cur.fetchone()[0]
            
            # Size statistics
            cur.execute("SELECT SUM(size_mb), AVG(size_mb) FROM models WHERE size_mb IS NOT NULL")
            size_row = cur.fetchone()
            total_size_gb = (size_row[0] or 0) / 1024
            avg_size_mb = size_row[1] or 0
            
            # Poly count statistics
            cur.execute("SELECT AVG(faces), MAX(faces), MIN(faces) FROM models WHERE faces IS NOT NULL")
            poly_row = cur.fetchone()
            avg_poly = int(poly_row[0] or 0)
            max_poly = poly_row[1] or 0
            min_poly = poly_row[2] or 0
            
            # File type distribution
            cur.execute("SELECT ext, COUNT(*) FROM models GROUP BY ext ORDER BY COUNT(*) DESC")
            file_types = [(row[0], row[1]) for row in cur.fetchall()]
            
            # Quality distribution
            cur.execute("SELECT rating, COUNT(*) FROM models GROUP BY rating ORDER BY rating DESC")
            quality_dist = [(row[0], row[1]) for row in cur.fetchall()]
            
            # Recent activity (last 30 days)
            thirty_days_ago = _now_ts() - (30 * 86400)
            cur.execute("SELECT COUNT(*) FROM models WHERE date_added >= ?", (thirty_days_ago,))
            recent_count = cur.fetchone()[0]
            
            # Favorites count
            cur.execute("SELECT COUNT(*) FROM models WHERE favorite = 1")
            favorites_count = cur.fetchone()[0]
            
            # Textured models count
            cur.execute("SELECT COUNT(*) FROM models WHERE textured = 1")
            textured_count = cur.fetchone()[0]
            
            # Broken models count
            cur.execute("SELECT COUNT(*) FROM models WHERE broken = 1")
            broken_count = cur.fetchone()[0]
            
            return {
                'total_models': total_models,
                'total_collections': total_collections,
                'total_folders': total_folders,
                'total_size_gb': round(total_size_gb, 2),
                'avg_size_mb': round(avg_size_mb, 2),
                'avg_poly_count': avg_poly,
                'max_poly_count': max_poly,
                'min_poly_count': min_poly,
                'file_types': file_types,
                'quality_distribution': quality_dist,
                'recent_count': recent_count,
                'favorites_count': favorites_count,
                'textured_count': textured_count,
                'broken_count': broken_count
            }
        except Exception as e:
            self.error_occurred.emit(f"get_library_stats failed: {e}")
            return {}

    def get_statistics(self) -> Dict[str, Any]:
        """Alias for get_library_stats() for UI compatibility."""
        return self.get_library_stats()

    def search(self, query: SearchQuery) -> List[Dict[str, Any]]:
        """Alias for search_models() for UI compatibility."""
        return self.search_models(query)

    def get_collections(self) -> List[Dict[str, Any]]:
        """Alias for list_collections() for UI compatibility."""
        return self.list_collections()

    def get_models_by_collection(self, collection_name: str) -> List[Dict[str, Any]]:
        """Get models in a specific collection."""
        if collection_name == "All Models":
            return self.get_models()
        elif collection_name == "Favorites":
            return self.get_favorites()
        elif collection_name == "Recently Added":
            return self.get_recent()
        elif collection_name == "High Poly":
            return self.get_high_poly()
        elif collection_name == "Textured Models":
            return self.get_textured()
        elif collection_name == "Needs Repair":
            return self.get_broken()
        else:
            return self.get_collection_items(collection_name)

    def check_database_integrity(self) -> Dict[str, Any]:
        """Check database integrity and return report."""
        try:
            cur = self.conn.cursor()
            
            # Check for missing files
            cur.execute("SELECT path FROM models")
            all_paths = [row[0] for row in cur.fetchall()]
            missing_files = [p for p in all_paths if not os.path.exists(p)]
            
            # Check for orphaned thumbnails
            orphaned_thumbs = []
            if os.path.exists(self.thumbs_dir):
                for thumb_file in os.listdir(self.thumbs_dir):
                    thumb_path = os.path.join(self.thumbs_dir, thumb_file)
                    if os.path.isfile(thumb_path):
                        # Check if corresponding model exists
                        base_name = os.path.splitext(thumb_file)[0]
                        cur.execute("SELECT path FROM models WHERE thumbnail LIKE ?", (f"%{base_name}%",))
                        if not cur.fetchone():
                            orphaned_thumbs.append(thumb_path)
            
            # Check for models without thumbnails
            cur.execute("SELECT path FROM models WHERE thumbnail IS NULL OR thumbnail = ''")
            missing_thumbs = [row[0] for row in cur.fetchall()]
            
            return {
                'missing_files': missing_files,
                'orphaned_thumbnails': orphaned_thumbs,
                'missing_thumbnails': missing_thumbs,
                'total_models': len(all_paths),
                'issues_found': len(missing_files) + len(orphaned_thumbs) + len(missing_thumbs)
            }
        except Exception as e:
            self.error_occurred.emit(f"check_database_integrity failed: {e}")
            return {}

    # ---------------------- Selection broadcast ----------------------
    def select_for_work(self, model_path: str) -> None:
        self.selected_for_work.emit(model_path)

    # ---------------------- LOD Generation ----------------------
    def generate_lod(self, model_id: int, levels: int = 3) -> List[str]:
        """
        Generate LODs for a model using the LODGenerator.
        
        Args:
            model_id: ID of the model
            levels: Number of LOD levels to generate
            
        Returns:
            List of generated LOD file paths
        """
        try:
            # Get model path
            model = self.get_model_details(model_id)
            if not model:
                raise ValueError(f"Model with ID {model_id} not found")
                
            file_path = model.get('path')
            if not file_path or not os.path.exists(file_path):
                raise FileNotFoundError(f"Model file not found: {file_path}")
                
            # Configure settings
            settings = LODSettings(levels=levels)
            generator = LODGenerator(settings)
            
            # Output directory (same as model for now, or a 'lods' subdirectory)
            output_dir = os.path.dirname(file_path)
            
            # Generate LODs
            lod_files = generator.generate_lods(file_path, output_dir)
            
            # Register LODs in database
            cur = self.conn.cursor()
            
            # First, clear existing LODs for this model to avoid duplicates
            cur.execute("DELETE FROM model_lods WHERE model_id = ?", (model_id,))
            
            for i, lod_path in enumerate(lod_files):
                try:
                    # Get stats
                    if trimesh:
                        mesh = trimesh.load(lod_path)
                        faces = len(mesh.faces)
                        vertices = len(mesh.vertices)
                    else:
                        faces = 0
                        vertices = 0
                        
                    size_mb = os.path.getsize(lod_path) / (1024 * 1024)
                    
                    cur.execute("""
                        INSERT INTO model_lods (model_id, lod_level, path, faces, vertices, size_mb)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (model_id, i, lod_path, faces, vertices, size_mb))
                    
                except Exception as e:
                    self.error_occurred.emit(f"Failed to register LOD {i} for model {model_id}: {e}")
            
            self.conn.commit()
            
            return lod_files
            
        except Exception as e:
            self.error_occurred.emit(f"Failed to generate LODs for model {model_id}: {e}")
            raise


class LibraryScannerWorker(SafeWorker):
    """Background scanner that uses LibraryManager.scan()."""
    def __init__(self, manager: LibraryManager, specific_paths: Optional[Sequence[str]] = None):
        super().__init__()
        self.manager = manager
        self.specific_paths = list(specific_paths) if specific_paths else None

    def safe_run(self):
        # No try-except needed here as SafeWorker handles it
        if self.specific_paths:
            self.manager.import_files(self.specific_paths)
        else:
            self.manager.scan()
