"""
Job manager for handling render queues and job execution.
"""

import os
import sys
import json
import hashlib
import logging
import uuid
import threading
import time
from typing import List, Optional, Callable, Dict, Tuple
from PyQt6.QtCore import QObject, pyqtSignal, QTimer
from .models import Priority, RenderJob, JobStatus, SoftwareType
from ..processing.render_engines import (create_render_engine, detect_available_software,
                                         _get_user_configured_path)
from ..utils.app_paths import config_path

# The one report channel the packaged build has: `diagnostics_tab.setup_logging` puts a
# PaneLogHandler on the root logger, and every record that reaches it becomes a row. A write
# to stdout is not a report there - `RenderFox.spec` builds the app with `console=False`.
logger = logging.getLogger(__name__)

# `Priority` is an Enum of strings, which has no order of its own; the queue needs
# one, and it is this table rather than the declaration order so that adding a
# level cannot silently reshuffle every queue.
_PRIORITY_RANK = {Priority.LOW: 0, Priority.NORMAL: 1, Priority.HIGH: 2,
                  Priority.URGENT: 3}

# What the Settings tab's queue controls mean when config.json does not say.
_DEFAULT_POLICY = {'max_concurrent': 1, 'auto_retry': False, 'max_retries': 3,
                   'pause_on_error': False}

def system_name(os_name: str, platform_name: str) -> str:
    """Map what Python knows about the machine onto the keys the path lists use.

    `os.name` and `sys.platform` are passed in rather than read, so the mapping
    can be tested for all three platforms on the one platform this runs on.
    """
    if os_name == 'nt':
        return "windows"
    if platform_name == 'darwin':
        return "darwin"
    return "linux"

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
        # One entry per job holding a render slot, so a paused or removed job can
        # be reached by id instead of by "the one job the queue happens to have".
        self._running: Dict[str, Tuple[RenderJob, Optional[object]]] = {}
        self._workers: Dict[str, threading.Thread] = {}
        self._processing_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        # Set when work appears or a slot frees, so the queue thread wakes on it
        # instead of sleeping its way through a second of every pick.
        self._queue_changed = threading.Event()
        self._hold_after_failure = False

        # Cache available software for performance
        self._available_software_cache = {}
        self._cache_timestamp = 0
        self._cache_duration = 300  # 5 minutes
        self._cache_stamp = None
        
        # Timer for updating job progress
        self._progress_timer = QTimer()
        self._progress_timer.timeout.connect(self._update_progress)

    def _snapshot(self) -> List[RenderJob]:
        """The job list as one atomic read.

        `add_job` runs on the UI thread while this one is picking, and iterating
        a list another thread is appending to raises "list changed size".
        """
        with self._lock:
            return list(self._jobs)
    
    def add_job(self, job: RenderJob) -> None:
        """Add a new job to the queue."""
        if not job.id:
            job.id = str(uuid.uuid4())
        
        with self._lock:
            self._jobs.append(job)
        self._queue_changed.set()
        self.job_added.emit(job)
        self.queue_updated.emit()
    
    def remove_job(self, job_id: str) -> bool:
        """Remove a job from the queue.

        A job that is rendering keeps its slot until its own process is gone:
        only *that* engine is stopped, because removing one render from a queue is
        not a request to cancel every other render in it.
        """
        with self._lock:
            for index, job in enumerate(self._jobs):
                if job.id == job_id:
                    entry = self._running.get(job_id)
                    self._jobs.pop(index)
                    break
            else:
                return False
        if entry is not None:
            self._kill_renderer(entry[0], entry[1])
        self._queue_changed.set()
        self.job_removed.emit(job_id)
        self.queue_updated.emit()
        return True
    
    def get_job(self, job_id: str) -> Optional[RenderJob]:
        """Get a job by its ID."""
        for job in self._snapshot():
            if job.id == job_id:
                return job
        return None
    
    def get_all_jobs(self) -> List[RenderJob]:
        """Get all jobs in the queue."""
        return self._snapshot()
    
    def get_pending_jobs(self) -> List[RenderJob]:
        """Get all pending jobs."""
        return [job for job in self._snapshot() if job.status == JobStatus.PENDING]
    
    def get_completed_jobs(self) -> List[RenderJob]:
        """Get all completed jobs."""
        return [job for job in self._snapshot()
                if job.status in [JobStatus.COMPLETED, JobStatus.FAILED]]

    def running_jobs(self) -> List[RenderJob]:
        """Every job holding a render slot, oldest first.

        A paused job still holds its slot: its renderer process is alive,
        suspended, and the frames it has written so far are real.
        """
        with self._lock:
            entries = [job for job, _engine in self._running.values()]
        return sorted(entries, key=lambda job: job.start_time or 0)

    @property
    def is_processing(self) -> bool:
        """Check if the job manager is currently processing jobs.""" 
        return self._is_processing
    
    @property
    def queue_size(self) -> int:
        """Get the total number of jobs in the queue."""
        return len(self._snapshot())
    
    @property
    def pending_count(self) -> int:
        """Get the number of pending jobs.""" 
        return len(self.get_pending_jobs())
    
    def start_processing(self) -> None:
        """Start processing the job queue."""
        if self._is_processing:
            return
        
        self._is_processing = True
        self._hold_after_failure = False
        self._stop_event.clear()
        self._queue_changed.clear()
        self._processing_thread = threading.Thread(target=self._process_queue)
        self._processing_thread.daemon = True
        self._processing_thread.start()
        self._progress_timer.start(1000)  # Update every second
        self.processing_started.emit()
    
    def stop_processing(self) -> None:
        """Stop processing the job queue, and every render it is running."""
        if not self._is_processing:
            return
        
        self._is_processing = False
        self._stop_event.set()
        self._queue_changed.set()

        with self._lock:
            renderings = list(self._running.values())
            workers = list(self._workers.values())
        for job, engine in renderings:
            self._kill_renderer(job, engine)

        # Wait for processing thread to finish
        if self._processing_thread and self._processing_thread.is_alive():
            self._processing_thread.join(timeout=5.0)
        for worker in workers:
            worker.join(timeout=5.0)

        self._progress_timer.stop()

        # Anything the workers did not get to is put back in the queue rather
        # than left claiming to be rendering.
        for job in self._snapshot():
            if job.status in (JobStatus.RENDERING, JobStatus.PAUSED):
                job.status = JobStatus.PENDING
                job.progress = 0
                self.job_updated.emit(job)

        self._hold_after_failure = False
        self.processing_stopped.emit()

    @staticmethod
    def _kill_renderer(job: RenderJob, engine: Optional[object]) -> None:
        """Cut one renderer off, waking a suspended process first.

        `terminate` on a SIGSTOPped process does nothing until the process is
        resumed, so a paused job has to be woken before it can be killed -
        otherwise the window closes with a live renderer in it.
        """
        if engine is None:
            return
        if job.status == JobStatus.PAUSED:
            try:
                engine.resume()
            except Exception as e:
                logger.warning("Error waking paused job %s: %s", job.id, e)
        try:
            engine.stop()
        except Exception as e:
            logger.warning("Error stopping render engine: %s", e)

    def pause_job(self, job_id: str) -> bool:
        """Pause one job's renderer, leaving the others alone."""
        with self._lock:
            entry = self._running.get(job_id)
        if entry is None:
            return False
        job, engine = entry
        if engine is None or job.status != JobStatus.RENDERING:
            return False
        try:
            engine.pause()
            job.status = JobStatus.PAUSED
            self.job_updated.emit(job)
            return True
        except Exception as e:
            logger.warning("Error pausing job: %s", e)
            return False

    def resume_job(self, job_id: str) -> bool:
        """Resume a paused job through its own renderer."""
        with self._lock:
            entry = self._running.get(job_id)
        if entry is None:
            return False
        job, engine = entry
        if engine is None or job.status != JobStatus.PAUSED:
            return False
        try:
            engine.resume()
            job.status = JobStatus.RENDERING
            self.job_updated.emit(job)
            return True
        except Exception as e:
            logger.warning("Error resuming job: %s", e)
            return False
    
    def _swap_in_queue(self, job_id: str, offset: int) -> bool:
        """Move one job one place along the list queue ties are broken by.

        Jobs of the same priority start in this order, so this is what the Batch
        menu's Move Up/Down actually controls.
        """
        with self._lock:
            for index, job in enumerate(self._jobs):
                if job.id != job_id:
                    continue
                target = index + offset
                if target < 0 or target >= len(self._jobs):
                    return False
                if job.status in (JobStatus.RENDERING, JobStatus.PAUSED):
                    return False
                self._jobs[index], self._jobs[target] = self._jobs[target], self._jobs[index]
                break
            else:
                return False
        self._queue_changed.set()
        self.queue_updated.emit()
        return True

    def move_job_up(self, job_id: str) -> bool:
        """Move a job up in the queue."""
        return self._swap_in_queue(job_id, -1)

    def move_job_down(self, job_id: str) -> bool:
        """Move a job down in the queue."""
        return self._swap_in_queue(job_id, 1)
    
    def clear_completed_jobs(self) -> None:
        """Remove all completed and failed jobs from the queue."""
        with self._lock:
            initial_count = len(self._jobs)
            self._jobs = [job for job in self._jobs
                          if job.status not in [JobStatus.COMPLETED, JobStatus.FAILED]]
            removed = len(self._jobs) != initial_count

        if removed:
            self.queue_updated.emit()
    
    def _queue_policy(self) -> Dict[str, object]:
        """The queue half of config.json, read again for every pick.

        The Settings tab writes these under `performance`; nothing used to read
        them back. config.json is a few hundred bytes and a pick happens once per
        render start, so caching would only make a saved setting look broken
        until the next queue start.
        """
        try:
            with open(config_path(), encoding='utf-8') as handle:
                perf = json.load(handle).get('performance') or {}
        except (OSError, ValueError, AttributeError):
            perf = {}

        def whole(key: str, low: int, high: int) -> int:
            try:
                return min(high, max(low, int(perf.get(key, _DEFAULT_POLICY[key]))))
            except (TypeError, ValueError):
                return _DEFAULT_POLICY[key]

        return {
            'max_concurrent': whole('max_concurrent', 1, 16),
            'auto_retry': bool(perf.get('auto_retry', _DEFAULT_POLICY['auto_retry'])),
            'max_retries': whole('max_retries', 0, 100),
            'pause_on_error': bool(perf.get('pause_on_error',
                                            _DEFAULT_POLICY['pause_on_error'])),
        }

    def _running_entries(self) -> List[Tuple[RenderJob, Optional[object]]]:
        with self._lock:
            return list(self._running.values())

    def _free_slots(self, limit: int) -> int:
        with self._lock:
            return max(0, limit - len(self._running))

    def _next_pending(self) -> Optional[RenderJob]:
        """The most urgent pending job, ties broken by the order they were added.

        `job.priority` was settable from the Batch menu and stored on the job;
        the queue took `pending_jobs[0]`, so the setting moved nothing.
        """
        with self._lock:
            running = set(self._running)
            jobs = list(self._jobs)
        waiting = [(position, job) for position, job in enumerate(jobs)
                   if job.status == JobStatus.PENDING and job.id not in running]
        if not waiting:
            return None
        waiting.sort(key=lambda item: (-_PRIORITY_RANK.get(item[1].priority, 1), item[0]))
        return waiting[0][1]

    def _process_queue(self) -> None:
        """Fill the free render slots; each render then runs in its own thread."""
        while self._is_processing and not self._stop_event.is_set():
            if self._hold_after_failure and not self._running_entries():
                break
            limit = self._queue_policy()['max_concurrent']
            job = None if self._hold_after_failure else self._next_pending()
            if job is not None and self._free_slots(limit) > 0:
                self._start_job(job)
                continue
            self._queue_changed.wait(timeout=0.5)
            self._queue_changed.clear()

        self._is_processing = False
        if self._hold_after_failure:
            # The queue stopped itself, so the UI is told what it cannot see.
            self._progress_timer.stop()
            self.processing_stopped.emit()

    def _start_job(self, job: RenderJob) -> None:
        """Claim a slot for a job and hand it to a worker thread."""
        job.status = JobStatus.RENDERING
        job.progress = 0
        job.start_time = time.time()
        with self._lock:
            self._running[job.id] = (job, None)
            worker = threading.Thread(target=self._run_job, args=(job,), daemon=True)
            self._workers[job.id] = worker
        self.job_updated.emit(job)
        worker.start()

    def _run_job(self, job: RenderJob) -> None:
        """Resolve an engine, render, and record one verdict."""
        policy = self._queue_policy()
        engine = None
        if self._stop_event.is_set():
            self._return_to_queue(job)
            return
        try:
            available_software = self._get_cached_available_software()

            if job.software_type not in available_software:
                raise Exception(f"No render engine available for {job.software_type.value}")

            executable_path = self._get_executable_path(job.software_type, available_software)

            if not executable_path:
                raise Exception(f"No executable found for {job.software_type.value}")

            engine = create_render_engine(job.software_type, executable_path)

            if not engine:
                raise Exception(f"Failed to create render engine for {job.software_type.value}")

            with self._lock:
                # `stop_processing` sets its flag before it reads the slots, so one
                # of the two always sees the other: either this thread registers the
                # engine and the stop kills it, or the stop wins and nothing launches.
                stopped = self._stop_event.is_set()
                if not stopped and job.id in self._running:
                    self._running[job.id] = (job, engine)

            if stopped:
                self._return_to_queue(job)
                return

            if not engine.is_available():
                raise Exception(f"Render engine not available: {job.software_type.value}")

            engine.set_progress_callback(self._bind_progress(job))
            success = engine.render_job(job)

            if self._stop_event.is_set():
                job.status = JobStatus.PENDING
                job.progress = 0
            elif self.get_job(job.id) is None:
                return  # taken out of the queue while it rendered; nothing to report
            elif success:
                job.status = JobStatus.COMPLETED
                job.progress = 100
                job.end_time = time.time()
            else:
                job.end_time = time.time()
                if not self._retry_pending(job, policy):
                    job.status = JobStatus.FAILED
                    if not job.error_message:
                        job.error_message = "Render job failed"
                    self._hold_after_failure = policy['pause_on_error']

            self.job_updated.emit(job)

        except Exception as error:
            job.status = JobStatus.FAILED
            job.error_message = str(error)
            job.end_time = time.time()
            job.progress = 0
            self._hold_after_failure = policy['pause_on_error']
            self.job_updated.emit(job)
            logger.warning("Error processing job %s: %s", job.id, error)

        finally:
            self._release(job, engine)

    def _return_to_queue(self, job: RenderJob) -> None:
        """Put a job back in the queue when its render never reached a process.

        A worker can claim a slot just as the user clicks Stop. Leaving the job on
        RENDERING would show a render that does not exist and hide the fact that
        nothing was launched; the next queue start has to pick it up again.
        """
        job.status = JobStatus.PENDING
        job.progress = 0
        self.job_updated.emit(job)

    def _retry_pending(self, job: RenderJob, policy: Dict[str, object]) -> bool:
        """Send a failed job back to PENDING, up to the configured limit.

        The retry counter lives on the job, so `max_retries` means the same thing
        for a hand-edited queue as for a hundred-job one.
        """
        if not policy['auto_retry'] or job.retry_count >= policy['max_retries']:
            return False
        job.retry_count += 1
        job.status = JobStatus.PENDING
        job.progress = 0
        return True

    def _bind_progress(self, job: RenderJob) -> Callable[[float], None]:
        """A callback that writes into *this* job.

        It used to write into "the current job", one attribute for the whole
        queue: with two renders going, the short one closing at 100 pushed the
        long one to 100 as well.
        """
        def progress_callback(progress: float) -> None:
            job.progress = min(100.0, max(0.0, progress))
            self.job_updated.emit(job)

        return progress_callback

    def _release(self, job: RenderJob, engine: Optional[object]) -> None:
        """Free the slot and wake the picker."""
        if engine is not None and hasattr(engine, 'cleanup'):
            try:
                engine.cleanup()
            except Exception as error:
                logger.warning("Error cleaning up render engine: %s", error)
        with self._lock:
            self._running.pop(job.id, None)
            self._workers.pop(job.id, None)
        self._queue_changed.set()

    def _get_cached_available_software(self) -> Dict[SoftwareType, str]:
        """Get available software, cached because a detection pass runs subprocesses.

        The cache is a view of `config.json`, so it is keyed on that file: when
        the user saves a Maya path in Settings the next job has to see it,
        instead of waiting out the 5-minute window on a stale answer.
        """
        current_time = time.time()
        stamp = self._config_stamp()

        # Check if cache is still valid
        if (self._available_software_cache
                and stamp == self._cache_stamp
                and (current_time - self._cache_timestamp) < self._cache_duration):
            return self._available_software_cache
        
        # Refresh cache
        try:
            self._available_software_cache = detect_available_software()
            self._cache_timestamp = current_time
            self._cache_stamp = stamp
        except Exception as e:
            logger.warning("Error detecting available software: %s", e)
            # Return empty dict if detection fails
            self._available_software_cache = {}
        
        return self._available_software_cache

    @staticmethod
    def _config_stamp() -> Optional[str]:
        """A digest of config.json, or None when there is none.

        Hashing the bytes beats an mtime: config.json is a few hundred bytes, and
        a modified-time can be one-second granular on a network share, which is
        exactly the resolution at which "Save" then "Start Queue" happens.
        """
        try:
            with open(config_path(), 'rb') as handle:
                return hashlib.sha256(handle.read()).hexdigest()
        except OSError:
            return None

    def _get_executable_path(self, software_type: SoftwareType, available_software: Dict[SoftwareType, str]) -> Optional[str]:
        """Get the executable path for a specific software type."""
        try:
            # 1. The path the Settings tab stored for this exact package.
            configured = _get_user_configured_path(software_type.value)
            if configured:
                return configured

            # 2. The same list the detector walks, so the two can never disagree
            #    about what is installed (it carries PATH lookups too).
            from ..processing.render_engines import (_get_blender_paths, _get_cinema4d_paths,
                                                     _get_maya_paths, _get_unreal_paths)
            system = system_name(os.name, sys.platform)
            
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
            
            return None
            
        except Exception as e:
            logger.warning("Error getting executable path for %s: %s", software_type, e)
            return None

    def _update_progress(self) -> None:
        """Poll every running engine for the frames its callback did not report.

        One engine used to be polled because one job could render at a time; with
        the queue's own slots filled, each render needs its own reading.
        """
        for job, engine in self._running_entries():
            if engine is None:
                continue
            try:
                progress = min(100.0, max(0.0, engine.get_progress()))
            except Exception:
                continue  # an engine mid-teardown is not a queue failure
            if progress != job.progress:
                job.progress = progress
                self.job_updated.emit(job)

    def get_queue_stats(self) -> Dict[str, int]:
        """Get statistics about the job queue."""
        jobs = self._snapshot()
        stats = {
            'total': len(jobs),
            'pending': 0,
            'rendering': 0,
            'completed': 0,
            'failed': 0,
            'paused': 0
        }

        for job in jobs:
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
        """Seconds left, summed over every job holding a slot.

        One job's remaining time used to stand for the whole queue's, which was
        out by however many slots the Settings tab allowed.
        """
        running = self.running_jobs()
        if not running:
            return None

        remaining = 0.0
        samples = []
        for job in running:
            if job.progress <= 0:
                continue
            elapsed = time.time() - (job.start_time or time.time())
            total = elapsed / (job.progress / 100.0)
            samples.append(total)
            remaining += max(0.0, total - elapsed)

        for job in self._snapshot():
            if job.status == JobStatus.COMPLETED and job.start_time and job.end_time:
                samples.append(job.end_time - job.start_time)

        if not samples:
            return None

        return remaining + self.pending_count * (sum(samples) / len(samples))
    
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