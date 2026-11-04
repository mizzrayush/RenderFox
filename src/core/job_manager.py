"""
Job manager for handling render queues and job execution.
"""

import os
import uuid
import threading
import time
from typing import List, Optional, Callable, Dict
from PyQt6.QtCore import QObject, pyqtSignal, QTimer
from .models import RenderJob, JobStatus, SoftwareType
from ..processing.render_engines import create_render_engine, detect_available_software

class JobManager(QObject):
    """Manages the render job queue and execution."""
    
    # Signals for UI updates
    job_added = pyqtSignal(RenderJob)
    job_updated = pyqtSignal(RenderJob)
    job_removed = pyqtSignal(str)  # job_id
    queue_updated = pyqtSignal()
    processing_started = pyqtSignal()
    processing_stopped = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self._jobs: List[RenderJob] = []
        self._is_processing = False
        self._current_job: Optional[RenderJob] = None
        self._processing_thread: Optional[threading.Thread] = None
        self._render_engine = None
        self._stop_event = threading.Event()
        
        # Cache available software for performance
        self._available_software_cache = {}
        self._cache_timestamp = 0
        self._cache_duration = 300  # 5 minutes
        
        # Timer for updating job progress
        self._progress_timer = QTimer()
        self._progress_timer.timeout.connect(self._update_progress)
    
    def add_job(self, job: RenderJob) -> None:
        """Add a new job to the queue."""
        if not job.id:
            job.id = str(uuid.uuid4())
        
        self._jobs.append(job)
        self.job_added.emit(job)
        self.queue_updated.emit()
    
    def remove_job(self, job_id: str) -> bool:
        """Remove a job from the queue."""
        for i, job in enumerate(self._jobs):
            if job.id == job_id:
                if job.status == JobStatus.RENDERING:
                    # Stop the rendering process
                    if self._render_engine:
                        self._render_engine.stop()
                    self._stop_event.set()
                
                self._jobs.pop(i)
                self.job_removed.emit(job_id)
                self.queue_updated.emit()
                return True
        return False
    
    def get_job(self, job_id: str) -> Optional[RenderJob]:
        """Get a job by its ID."""
        for job in self._jobs:
            if job.id == job_id:
                return job
        return None
    
    def get_all_jobs(self) -> List[RenderJob]:
        """Get all jobs in the queue."""
        return self._jobs.copy()
    
    def get_pending_jobs(self) -> List[RenderJob]:
        """Get all pending jobs."""
        return [job for job in self._jobs if job.status == JobStatus.PENDING]
    
    def get_completed_jobs(self) -> List[RenderJob]:
        """Get all completed jobs."""
        return [job for job in self._jobs if job.status in [JobStatus.COMPLETED, JobStatus.FAILED]]
    
    @property
    def current_job(self) -> Optional[RenderJob]:
        """Get the currently processing job."""
        return self._current_job
    
    @property
    def is_processing(self) -> bool:
        """Check if the job manager is currently processing jobs.""" 
        return self._is_processing
    
    @property
    def queue_size(self) -> int:
        """Get the total number of jobs in the queue."""
        return len(self._jobs)
    
    @property
    def pending_count(self) -> int:
        """Get the number of pending jobs.""" 
        return len(self.get_pending_jobs())
    
    def start_processing(self) -> None:
        """Start processing the job queue."""
        if self._is_processing:
            return
        
        self._is_processing = True
        self._stop_event.clear()
        self._processing_thread = threading.Thread(target=self._process_queue)
        self._processing_thread.daemon = True
        self._processing_thread.start()
        self._progress_timer.start(1000)  # Update every second
        self.processing_started.emit()
    
    def stop_processing(self) -> None:
        """Stop processing the job queue."""
        if not self._is_processing:
            return
        
        self._is_processing = False
        self._stop_event.set()
        
        # Stop current render engine
        if self._render_engine:
            try:
                self._render_engine.stop()
            except Exception as e:
                print(f"Error stopping render engine: {e}")
        
        # Wait for processing thread to finish
        if self._processing_thread and self._processing_thread.is_alive():
            self._processing_thread.join(timeout=5.0)
        
        self._progress_timer.stop()
        
        # Reset current job status if it was rendering
        if self._current_job and self._current_job.status == JobStatus.RENDERING:
            self._current_job.status = JobStatus.PENDING
            self._current_job.progress = 0
            self.job_updated.emit(self._current_job)
        
        self._current_job = None
        self._render_engine = None
        self.processing_stopped.emit()
    
    def pause_job(self, job_id: str) -> bool:
        """Pause a specific job."""
        job = self.get_job(job_id)
        if job and job.status == JobStatus.RENDERING:
            if self._render_engine:
                try:
                    self._render_engine.pause()
                    job.status = JobStatus.PAUSED
                    self.job_updated.emit(job)
                    return True
                except Exception as e:
                    print(f"Error pausing job: {e}")
        return False
    
    def resume_job(self, job_id: str) -> bool:
        """Resume a paused job."""
        job = self.get_job(job_id)
        if job and job.status == JobStatus.PAUSED:
            if self._render_engine:
                try:
                    self._render_engine.resume()
                    job.status = JobStatus.RENDERING
                    self.job_updated.emit(job)
                    return True
                except Exception as e:
                    print(f"Error resuming job: {e}")
        return False
    
    def move_job_up(self, job_id: str) -> bool:
        """Move a job up in the queue."""
        for i, job in enumerate(self._jobs):
            if job.id == job_id and i > 0:
                # Can't move up if it's currently rendering
                if job.status == JobStatus.RENDERING:
                    return False
                
                self._jobs[i], self._jobs[i-1] = self._jobs[i-1], self._jobs[i]
                self.queue_updated.emit()
                return True
        return False
    
    def move_job_down(self, job_id: str) -> bool:
        """Move a job down in the queue."""
        for i, job in enumerate(self._jobs):
            if job.id == job_id and i < len(self._jobs) - 1:
                # Can't move down if it's currently rendering
                if job.status == JobStatus.RENDERING:
                    return False
                
                self._jobs[i], self._jobs[i+1] = self._jobs[i+1], self._jobs[i]
                self.queue_updated.emit()
                return True
        return False
    
    def clear_completed_jobs(self) -> None:
        """Remove all completed and failed jobs from the queue."""
        initial_count = len(self._jobs)
        self._jobs = [job for job in self._jobs if job.status not in [JobStatus.COMPLETED, JobStatus.FAILED]]
        
        if len(self._jobs) != initial_count:
            self.queue_updated.emit()
    
    def _process_queue(self) -> None:
        """Process jobs in the queue (runs in separate thread)."""
        while self._is_processing and not self._stop_event.is_set():
            # Get next pending job
            pending_jobs = self.get_pending_jobs()
            if not pending_jobs:
                time.sleep(1)
                continue
            
            job = pending_jobs[0]
            self._current_job = job
            
            try:
                # Update job status
                job.status = JobStatus.RENDERING
                job.start_time = time.time()
                self.job_updated.emit(job)
                
                # Get available software with caching
                available_software = self._get_cached_available_software()
                
                if job.software_type not in available_software:
                    raise Exception(f"No render engine available for {job.software_type.value}")
                
                # Get the executable path from detection system
                executable_path = self._get_executable_path(job.software_type, available_software)
                
                if not executable_path:
                    raise Exception(f"No executable found for {job.software_type.value}")
                
                # Create render engine
                self._render_engine = create_render_engine(job.software_type, executable_path)
                
                if not self._render_engine:
                    raise Exception(f"Failed to create render engine for {job.software_type.value}")
                
                # Verify engine is available
                if not self._render_engine.is_available():
                    raise Exception(f"Render engine not available: {job.software_type.value}")
                
                # Set up progress callback
                def progress_callback(progress: float):
                    if self._current_job:
                        self._current_job.progress = min(100.0, max(0.0, progress))
                        self.job_updated.emit(self._current_job)
                
                self._render_engine.set_progress_callback(progress_callback)
                
                # Execute the job - FIX: Use correct method name
                success = self._render_engine.render_job(job)
                
                # Update job status based on result
                if self._stop_event.is_set():
                    job.status = JobStatus.PENDING
                    job.progress = 0
                elif success:
                    job.status = JobStatus.COMPLETED
                    job.progress = 100
                    job.end_time = time.time()
                else:
                    job.status = JobStatus.FAILED
                    job.end_time = time.time()
                    if not job.error_message:
                        job.error_message = "Render job failed"
                
                self.job_updated.emit(job)
                
            except Exception as e:
                job.status = JobStatus.FAILED
                job.error_message = str(e)
                job.end_time = time.time()
                job.progress = 0
                self.job_updated.emit(job)
                print(f"Error processing job {job.id}: {e}")
            
            finally:
                if self._render_engine:
                    try:
                        if hasattr(self._render_engine, 'cleanup'):
                            self._render_engine.cleanup()
                    except Exception as e:
                        print(f"Error cleaning up render engine: {e}")
                    self._render_engine = None
                
                self._current_job = None
        
        # Final cleanup
        self._is_processing = False

    def _get_cached_available_software(self) -> Dict[SoftwareType, str]:
        """Get available software with caching for performance."""
        current_time = time.time()
        
        # Check if cache is still valid
        if (current_time - self._cache_timestamp) < self._cache_duration and self._available_software_cache:
            return self._available_software_cache
        
        # Refresh cache
        try:
            self._available_software_cache = detect_available_software()
            self._cache_timestamp = current_time
        except Exception as e:
            print(f"Error detecting available software: {e}")
            # Return empty dict if detection fails
            self._available_software_cache = {}
        
        return self._available_software_cache

    def _get_executable_path(self, software_type: SoftwareType, available_software: Dict[SoftwareType, str]) -> Optional[str]:
        """Get the executable path for a specific software type."""
        try:
            # 1. Check user-configured path in config.json
            import json, shutil
            config_path = os.path.join(os.getcwd(), 'config.json')
            if os.path.exists(config_path):
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config_data = json.load(f)
                        software_map = config_data.get('software', {})
                        configured_path = software_map.get(software_type.value, '').strip()
                        if configured_path and os.path.exists(configured_path):
                            return configured_path
                except Exception:
                    pass

            # 2. Check engine path getters
            from ..processing.render_engines import _get_blender_paths, _get_maya_paths, _get_unreal_paths, _get_cinema4d_paths
            system = "windows" if os.name == 'nt' else ("darwin" if sys.platform == 'darwin' else "linux")
            
            paths_map = {
                SoftwareType.BLENDER: _get_blender_paths(system),
                SoftwareType.MAYA: _get_maya_paths(system),
                SoftwareType.UNREAL: _get_unreal_paths(system),
                SoftwareType.CINEMA4D: _get_cinema4d_paths(system)
            }
            
            paths = paths_map.get(software_type, [])
            for path in paths:
                if path and os.path.exists(path):
                    return path
            
            # 3. Check shutil.which
            which_exe = shutil.which(software_type.value)
            if which_exe:
                return which_exe
            
            return None
            
        except Exception as e:
            print(f"Error getting executable path for {software_type}: {e}")
            return None

    def _update_progress(self) -> None:
        """Update progress for the current job (called by timer)."""
        if self._current_job and self._render_engine:
            try:
                progress = self._render_engine.get_progress()
                if progress != self._current_job.progress:
                    self._current_job.progress = progress
                    self.job_updated.emit(self._current_job)
            except Exception:
                pass  # Ignore progress update errors
    
    def get_queue_stats(self) -> Dict[str, int]:
        """Get statistics about the job queue."""
        stats = {
            'total': len(self._jobs),
            'pending': 0,
            'rendering': 0,
            'completed': 0,
            'failed': 0,
            'paused': 0
        }
        
        for job in self._jobs:
            if job.status == JobStatus.PENDING:
                stats['pending'] += 1
            elif job.status == JobStatus.RENDERING:
                stats['rendering'] += 1
            elif job.status == JobStatus.COMPLETED:
                stats['completed'] += 1
            elif job.status == JobStatus.FAILED:
                stats['failed'] += 1
            elif job.status == JobStatus.PAUSED:
                stats['paused'] += 1
        
        return stats
    
    def estimate_remaining_time(self) -> Optional[float]:
        """Estimate remaining time for all pending jobs in seconds."""
        if not self._current_job or self._current_job.progress == 0:
            return None
        
        # Calculate time for current job
        elapsed = time.time() - (self._current_job.start_time or time.time())
        progress_ratio = self._current_job.progress / 100.0
        
        if progress_ratio > 0:
            estimated_total_time = elapsed / progress_ratio
            remaining_current = estimated_total_time - elapsed
        else:
            remaining_current = 0
        
        # Estimate time for pending jobs (rough estimate)
        pending_count = self.pending_count
        avg_job_time = estimated_total_time if self._current_job else 3600  # Default 1 hour
        
        return remaining_current + (pending_count * avg_job_time)
    
    def refresh_software_cache(self) -> None:
        """Force refresh of the software cache."""
        self._cache_timestamp = 0
        self._get_cached_available_software()

    def get_available_software_info(self) -> Dict[str, Dict]:
        """Get detailed information about available software."""
        available_software = self._get_cached_available_software()
        info = {}
        
        for software_type in SoftwareType:
            is_available = software_type in available_software
            version = available_software.get(software_type, "Not Found")
            executable_path = self._get_executable_path(software_type, available_software) if is_available else None
            
            info[software_type.value] = {
                "name": software_type.value.title(),
                "available": is_available,
                "version": version,
                "executable_path": executable_path
            }
        
        return info

    def get_software_status(self) -> Dict[str, bool]:
        """Get the availability status of all supported software."""
        available_software = self._get_cached_available_software()
        
        # Convert to simple boolean status
        status = {}
        for software_type in SoftwareType:
            status[software_type.value.title()] = software_type in available_software
        
        return status