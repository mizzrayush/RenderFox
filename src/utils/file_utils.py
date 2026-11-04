"""
File utility functions for RenderFox.
"""

import os
import shutil
import hashlib
import mimetypes
from typing import List, Dict, Optional, Tuple
from pathlib import Path
import json
import tempfile
import zipfile
import tarfile
from datetime import datetime


def ensure_directory(path: str) -> bool:
    """Ensure a directory exists, create if it doesn't."""
    try:
        os.makedirs(path, exist_ok=True)
        return True
    except Exception:
        return False


def get_file_size(file_path: str) -> int:
    """Get file size in bytes."""
    try:
        return os.path.getsize(file_path)
    except (OSError, FileNotFoundError):
        return 0


def get_file_hash(file_path: str, algorithm: str = 'md5') -> str:
    """Calculate file hash."""
    hash_func = hashlib.new(algorithm)
    try:
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_func.update(chunk)
        return hash_func.hexdigest()
    except Exception:
        return ""


def is_image_file(file_path: str) -> bool:
    """Check if file is an image."""
    image_extensions = {'.png', '.jpg', '.jpeg', '.tiff', '.tif', '.bmp', '.exr', '.hdr'}
    return Path(file_path).suffix.lower() in image_extensions


def is_video_file(file_path: str) -> bool:
    """Check if file is a video."""
    video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm'}
    return Path(file_path).suffix.lower() in video_extensions


def is_3d_file(file_path: str) -> bool:
    """Check if file is a 3D model."""
    model_extensions = {'.blend', '.obj', '.fbx', '.dae', '.3ds', '.max', '.ma', '.mb', '.c4d'}
    return Path(file_path).suffix.lower() in model_extensions


def get_safe_filename(filename: str) -> str:
    """Make filename safe for filesystem."""
    # Remove invalid characters
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    
    # Limit length
    if len(filename) > 255:
        name, ext = os.path.splitext(filename)
        filename = name[:255-len(ext)] + ext
    
    return filename


def get_unique_filename(file_path: str) -> str:
    """Generate unique filename if file already exists."""
    if not os.path.exists(file_path):
        return file_path
    
    directory = os.path.dirname(file_path)
    name, ext = os.path.splitext(os.path.basename(file_path))
    
    counter = 1
    while True:
        new_name = f"{name}_{counter}{ext}"
        new_path = os.path.join(directory, new_name)
        if not os.path.exists(new_path):
            return new_path
        counter += 1


def copy_file_with_progress(src: str, dst: str, callback=None) -> bool:
    """Copy file with progress callback."""
    try:
        ensure_directory(os.path.dirname(dst))
        
        file_size = get_file_size(src)
        copied = 0
        
        with open(src, 'rb') as fsrc, open(dst, 'wb') as fdst:
            while True:
                chunk = fsrc.read(64 * 1024)  # 64KB chunks
                if not chunk:
                    break
                fdst.write(chunk)
                copied += len(chunk)
                
                if callback:
                    progress = int((copied / file_size) * 100) if file_size > 0 else 100
                    callback(progress)
        
        return True
    except Exception:
        return False


def move_file(src: str, dst: str) -> bool:
    """Move file safely."""
    try:
        ensure_directory(os.path.dirname(dst))
        shutil.move(src, dst)
        return True
    except Exception:
        return False


def delete_file_safe(file_path: str) -> bool:
    """Delete file safely."""
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
        return True
    except Exception:
        return False


def cleanup_directory(directory: str, older_than_days: int = 30) -> int:
    """Clean up old files in directory."""
    if not os.path.exists(directory):
        return 0
    
    cutoff_time = datetime.now().timestamp() - (older_than_days * 24 * 3600)
    cleaned_count = 0
    
    try:
        for root, dirs, files in os.walk(directory):
            for file in files:
                file_path = os.path.join(root, file)
                if os.path.getmtime(file_path) < cutoff_time:
                    if delete_file_safe(file_path):
                        cleaned_count += 1
    except Exception:
        pass
    
    return cleaned_count


def get_directory_size(directory: str) -> int:
    """Calculate total directory size."""
    total_size = 0
    try:
        for root, dirs, files in os.walk(directory):
            for file in files:
                file_path = os.path.join(root, file)
                total_size += get_file_size(file_path)
    except Exception:
        pass
    
    return total_size


def find_files_by_pattern(directory: str, pattern: str, recursive: bool = True) -> List[str]:
    """Find files matching pattern."""
    import glob
    
    if recursive:
        search_pattern = os.path.join(directory, '**', pattern)
        return glob.glob(search_pattern, recursive=True)
    else:
        search_pattern = os.path.join(directory, pattern)
        return glob.glob(search_pattern)


def create_archive(files: List[str], archive_path: str, compression: str = 'zip') -> bool:
    """Create archive from file list."""
    try:
        ensure_directory(os.path.dirname(archive_path))
        
        if compression.lower() == 'zip':
            with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for file_path in files:
                    if os.path.exists(file_path):
                        arcname = os.path.basename(file_path)
                        zipf.write(file_path, arcname)
        
        elif compression.lower() in ['tar', 'tar.gz', 'tgz']:
            mode = 'w:gz' if compression.lower() in ['tar.gz', 'tgz'] else 'w'
            with tarfile.open(archive_path, mode) as tarf:
                for file_path in files:
                    if os.path.exists(file_path):
                        arcname = os.path.basename(file_path)
                        tarf.add(file_path, arcname)
        
        return True
    except Exception:
        return False


def extract_archive(archive_path: str, destination: str) -> bool:
    """Extract archive to destination."""
    try:
        ensure_directory(destination)
        
        if archive_path.endswith('.zip'):
            with zipfile.ZipFile(archive_path, 'r') as zipf:
                zipf.extractall(destination)
        
        elif any(archive_path.endswith(ext) for ext in ['.tar', '.tar.gz', '.tgz']):
            with tarfile.open(archive_path, 'r:*') as tarf:
                tarf.extractall(destination)
        
        return True
    except Exception:
        return False


def get_temp_directory() -> str:
    """Get temporary directory for RenderFox."""
    temp_dir = os.path.join(tempfile.gettempdir(), 'renderfox')
    ensure_directory(temp_dir)
    return temp_dir


def cleanup_temp_files() -> int:
    """Clean up RenderFox temporary files."""
    temp_dir = get_temp_directory()
    return cleanup_directory(temp_dir, older_than_days=1)


def format_file_size(size_bytes: int) -> str:
    """Format file size in human readable format."""
    if size_bytes == 0:
        return "0 B"
    
    size_names = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    
    return f"{size_bytes:.1f} {size_names[i]}"


def get_file_metadata(file_path: str) -> Dict:
    """Get comprehensive file metadata."""
    try:
        stat = os.stat(file_path)
        return {
            'size': stat.st_size,
            'created': datetime.fromtimestamp(stat.st_ctime),
            'modified': datetime.fromtimestamp(stat.st_mtime),
            'accessed': datetime.fromtimestamp(stat.st_atime),
            'mime_type': mimetypes.guess_type(file_path)[0],
            'extension': Path(file_path).suffix,
            'is_image': is_image_file(file_path),
            'is_video': is_video_file(file_path),
            'is_3d': is_3d_file(file_path)
        }
    except Exception:
        return {}


def validate_file_path(file_path: str) -> Tuple[bool, str]:
    """Validate file path and return status with message."""
    if not file_path:
        return False, "File path is empty"
    
    if not os.path.exists(file_path):
        return False, "File does not exist"
    
    if not os.path.isfile(file_path):
        return False, "Path is not a file"
    
    try:
        # Test read access
        with open(file_path, 'rb') as f:
            f.read(1)
        return True, "File is valid"
    except PermissionError:
        return False, "No read permission"
    except Exception as e:
        return False, f"File error: {str(e)}"


def backup_file(file_path: str, backup_dir: Optional[str] = None) -> Optional[str]:
    """Create backup of file."""
    if not os.path.exists(file_path):
        return None
    
    if backup_dir is None:
        backup_dir = os.path.join(os.path.dirname(file_path), 'backups')
    
    ensure_directory(backup_dir)
    
    # Create backup filename with timestamp
    name, ext = os.path.splitext(os.path.basename(file_path))
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_name = f"{name}_backup_{timestamp}{ext}"
    backup_path = os.path.join(backup_dir, backup_name)
    
    try:
        shutil.copy2(file_path, backup_path)
        return backup_path
    except Exception:
        return None


def restore_backup(backup_path: str, original_path: str) -> bool:
    """Restore file from backup."""
    try:
        ensure_directory(os.path.dirname(original_path))
        shutil.copy2(backup_path, original_path)
        return True
    except Exception:
        return False


class FileWatcher:
    """Simple file watcher for monitoring changes."""
    
    def __init__(self):
        self.watched_files = {}
    
    def add_file(self, file_path: str):
        """Add file to watch list."""
        if os.path.exists(file_path):
            self.watched_files[file_path] = os.path.getmtime(file_path)
    
    def check_changes(self) -> List[str]:
        """Check for file changes and return list of changed files."""
        changed_files = []
        
        for file_path, last_mtime in list(self.watched_files.items()):
            if not os.path.exists(file_path):
                # File was deleted
                del self.watched_files[file_path]
                changed_files.append(file_path)
            else:
                current_mtime = os.path.getmtime(file_path)
                if current_mtime != last_mtime:
                    self.watched_files[file_path] = current_mtime
                    changed_files.append(file_path)
        
        return changed_files
    
    def remove_file(self, file_path: str):
        """Remove file from watch list."""
        self.watched_files.pop(file_path, None)
    
    def clear(self):
        """Clear all watched files."""
        self.watched_files.clear()