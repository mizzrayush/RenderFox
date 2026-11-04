"""
RenderFox Automation Engine
Provides task scheduling, workflow automation, batch processing, and trigger-based actions.
"""

import os
import time
import json
import fnmatch
import calendar
import subprocess
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
import threading
import schedule
import uuid

from PyQt6.QtCore import QObject, pyqtSignal, QTimer


class TaskStatus(Enum):
    """Task execution status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SCHEDULED = "scheduled"


class TaskPriority(Enum):
    """Task priority levels."""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4


class TriggerType(Enum):
    """Automation trigger types."""
    TIME_BASED = "time_based"
    FILE_WATCH = "file_watch"
    EVENT_BASED = "event_based"
    CONDITION = "condition"
    MANUAL = "manual"


def app_data_dir() -> str:
    """The folder RenderFox keeps its own state in, as the library and telemetry do.

    Tasks and workflows used to be written relative to the working directory, so the app
    only found its saved work when it happened to be started from the right folder, and a
    packaged build pointed at ``sys._MEIPASS`` wrote into a temporary directory.
    """
    path = os.path.join(os.path.expanduser('~'), '.renderfox')
    os.makedirs(path, exist_ok=True)
    return path



class ActionRegistry:
    """Registry for automation actions."""
    
    _actions: Dict[str, Callable] = {}
    _descriptions: Dict[str, str] = {}
    _param_specs: Dict[str, Dict] = {}
    
    @classmethod
    def register(cls, action_id: str, func: Callable, description: str = "", params: Dict = None):
        """Register a new action."""
        cls._actions[action_id] = func
        cls._descriptions[action_id] = description
        cls._param_specs[action_id] = params or {}
        print(f"Registered action: {action_id}")
        
    @classmethod
    def get_action(cls, action_id: str) -> Optional[Callable]:
        """Get action callable by ID."""
        return cls._actions.get(action_id)
        
    @classmethod
    def get_all_actions(cls) -> Dict[str, Dict]:
        """Get all registered actions with metadata."""
        return {
            aid: {
                'description': cls._descriptions.get(aid, ''),
                'parameters': cls._param_specs.get(aid, {})
            }
            for aid in cls._actions.keys()
        }
    
    @classmethod
    def execute(cls, action_id: str, **kwargs) -> Dict[str, Any]:
        """Execute an action by ID."""
        if action_id not in cls._actions:
            return {'success': False, 'error': f'Action {action_id} not found'}
            
        try:
            func = cls._actions[action_id]
            specs = cls._param_specs.get(action_id, {})
            
            # Validate parameters
            for param_name, spec in specs.items():
                if spec.get('required', False) and param_name not in kwargs:
                    return {'success': False, 'error': f'Missing required parameter: {param_name}'}
                
                if param_name in kwargs:
                    value = kwargs[param_name]
                    param_type = spec.get('type')
                    if param_type:
                        if param_type == 'str' and not isinstance(value, str):
                             return {'success': False, 'error': f'Parameter {param_name} must be a string'}
                        elif param_type == 'int' and not isinstance(value, int):
                             return {'success': False, 'error': f'Parameter {param_name} must be an integer'}
                        elif param_type == 'float' and not isinstance(value, (int, float)):
                             return {'success': False, 'error': f'Parameter {param_name} must be a number'}
                        elif param_type == 'bool' and not isinstance(value, bool):
                             return {'success': False, 'error': f'Parameter {param_name} must be a boolean'}
            
            result = func(**kwargs)
            
            # Ensure result is a dict with success flag
            if isinstance(result, dict) and 'success' in result:
                return result
            
            return {'success': True, 'result': result}
            
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @classmethod
    def register_default_actions(cls):
        """Register the actions a task or a workflow step is allowed to name.

        Each one reports what it can prove rather than what it intended: a copy is
        confirmed by the bytes at the destination, a command is judged by its exit
        code, and the two processing actions name the files they actually wrote.
        """
        import shutil

        def copy_file(source: str, destination: str):
            if not os.path.isfile(source):
                raise FileNotFoundError(f"there is no file to copy at {source}")
            size = os.path.getsize(source)
            shutil.copy2(source, destination)
            if not os.path.isfile(destination) or os.path.getsize(destination) != size:
                raise RuntimeError(f"{destination} is not a full copy of {source}")
            return f"Copied {os.path.basename(source)} ({size} bytes) to {destination}"

        cls.register("file.copy", copy_file, "Copy a file", {
            "source": {"type": "str", "required": True},
            "destination": {"type": "str", "required": True}
        })

        def move_file(source: str, destination: str):
            if not os.path.isfile(source):
                raise FileNotFoundError(f"there is no file to move at {source}")
            shutil.move(source, destination)
            if os.path.exists(source) or not os.path.isfile(destination):
                raise RuntimeError(f"{source} is still where it was and {destination} is not a file")
            return f"Moved {os.path.basename(source)} to {destination}"

        cls.register("file.move", move_file, "Move a file", {
            "source": {"type": "str", "required": True},
            "destination": {"type": "str", "required": True}
        })

        def delete_file(path: str):
            if os.path.isdir(path):
                raise IsADirectoryError(f"{path} is a folder; this action deletes single files")
            if not os.path.exists(path):
                raise FileNotFoundError(f"{path} is already gone")
            size = os.path.getsize(path)
            os.remove(path)
            if os.path.exists(path):
                raise RuntimeError(f"{path} was not deleted")
            return f"Deleted {path} ({size} bytes)"

        cls.register("file.delete", delete_file, "Delete a file", {
            "path": {"type": "str", "required": True}
        })

        def run_command(command: str):
            try:
                completed = subprocess.run(command, shell=True, capture_output=True,
                                           text=True, timeout=300)
            except subprocess.TimeoutExpired:
                return {'success': False,
                        'error': 'the command was still running after 300 seconds and was killed'}
            output = ((completed.stdout or '') + (completed.stderr or '')).strip()
            tail = output[-400:] if output else ''
            if completed.returncode != 0:
                return {'success': False, 'exit_code': completed.returncode,
                        'error': f"the command exited {completed.returncode}: "
                                 f"{tail or 'it printed nothing'}"}
            return {'success': True, 'exit_code': 0,
                    'result': tail or 'the command exited 0 and printed nothing'}

        cls.register("system.run_command", run_command,
                     "Run a shell command; its exit code is the verdict", {
            "command": {"type": "str", "required": True}
        })

        # --- Processing Actions ---

        def bake_texture(high_poly: str, low_poly: str, output_dir: str, resolution: int = 2048):
            from ..processing.texture_baker import TextureBaker
            for path, label in ((high_poly, 'high-poly'), (low_poly, 'low-poly')):
                if not os.path.isfile(path):
                    raise FileNotFoundError(f"the {label} model is not a file: {path}")
            baker = TextureBaker()
            complaints = []
            baker.error_occurred.connect(lambda message: complaints.append(message))
            maps = baker.bake(high_poly, low_poly, output_dir, int(resolution), True, True, True) or {}
            written = {kind: path for kind, path in maps.items()
                       if os.path.isfile(path) and os.path.getsize(path) > 0}
            if not written:
                return {'success': False,
                        'error': f"no baked map could be read back for "
                                 f"{os.path.basename(low_poly)}: "
                                 + (complaints[-1] if complaints else 'the baker gave no reason')}
            return {'success': True,
                    'result': f"Baked {len(written)} map(s) for {os.path.basename(low_poly)}: "
                              + ', '.join(sorted(written)),
                    'maps': written}

        cls.register("processing.bake_texture", bake_texture, "Bake textures", {
            "high_poly": {"type": "str", "required": True},
            "low_poly": {"type": "str", "required": True},
            "output_dir": {"type": "str", "required": True},
            "resolution": {"type": "int", "required": False}
        })

        def generate_lod(input_file: str, output_dir: str, levels: int = 3):
            from ..processing.lod_generator import LODGenerator, LODSettings
            if not os.path.isfile(input_file):
                raise FileNotFoundError(f"there is no model at {input_file}")
            levels = max(1, int(levels))
            files = LODGenerator(LODSettings(levels=levels)).generate_lods(input_file, output_dir) or []
            written = [path for path in files
                       if os.path.isfile(path) and os.path.getsize(path) > 0]
            if not written:
                return {'success': False,
                        'error': f"no LOD file was written for {os.path.basename(input_file)}"}
            return {'success': True,
                    'result': f"Wrote {len(written)} LOD(s) into {output_dir}: "
                              + ', '.join(os.path.basename(path) for path in written),
                    'files': written}

        cls.register("processing.generate_lod", generate_lod, "Generate LODs", {
            "input_file": {"type": "str", "required": True},
            "output_dir": {"type": "str", "required": True},
            "levels": {"type": "int", "required": False}
        })



class WorkflowStep:
    """Represents a single step in a workflow."""
    
    def __init__(self, name: str, action: str, parameters: Dict = None,
                 condition: str = "always", on_error: str = "stop"):
        self.step_id = str(uuid.uuid4())
        self.name = name
        self.action = action  # Action to perform
        self.parameters = parameters or {}
        self.condition = condition  # Condition to execute this step
        self.on_error = on_error  # "stop", "continue", "retry"
        self.retry_count = 0
        self.max_retries = 3
        self.status = TaskStatus.PENDING
        self.result = None
        self.error = None
    
    def to_dict(self) -> Dict:
        """Convert step to dictionary."""
        return {
            'step_id': self.step_id,
            'name': self.name,
            'action': self.action,
            'parameters': self.parameters,
            'condition': self.condition,
            'on_error': self.on_error,
            'max_retries': self.max_retries
        }
    
    @staticmethod
    def from_dict(data: Dict) -> 'WorkflowStep':
        """Create step from dictionary."""
        step = WorkflowStep(
            name=data['name'],
            action=data['action'],
            parameters=data.get('parameters', {}),
            condition=data.get('condition', 'always'),
            on_error=data.get('on_error', 'stop')
        )
        step.step_id = data.get('step_id', str(uuid.uuid4()))
        step.max_retries = data.get('max_retries', 3)
        return step


@dataclass
class AutomationTask:
    """Container for automation task."""
    task_id: str
    name: str
    task_type: str
    parameters: Dict[str, Any]
    schedule_time: Optional[str] = None
    enabled: bool = True
    status: TaskStatus = TaskStatus.PENDING
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'task_id': self.task_id,
            'name': self.name,
            'task_type': self.task_type,
            'parameters': self.parameters,
            'schedule_time': self.schedule_time,
            'enabled': self.enabled,
            'status': self.status.value,
            'created_at': self.created_at,
            'started_at': self.started_at,
            'completed_at': self.completed_at,
            'result': self.result,
            'error': self.error
        }


    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'AutomationTask':
        """Rebuild a saved task; a record with no id or no name is not a task."""
        task = AutomationTask(
            task_id=data['task_id'],
            name=data['name'],
            task_type=data.get('task_type', ''),
            parameters=data.get('parameters') or {},
            schedule_time=data.get('schedule_time'),
            enabled=bool(data.get('enabled', True)),
            status=TaskStatus(data.get('status', 'pending')),
            created_at=data.get('created_at', time.time()),
        )
        task.started_at = data.get('started_at')
        task.completed_at = data.get('completed_at')
        task.result = data.get('result')
        task.error = data.get('error')
        return task



class Workflow:
    """Represents a workflow with multiple steps."""
    
    def __init__(self, name: str, description: str = ""):
        self.workflow_id = str(uuid.uuid4())
        self.name = name
        self.description = description
        self.steps: List[WorkflowStep] = []
        self.created_at = datetime.now()
        self.modified_at = datetime.now()
        self.status = TaskStatus.PENDING
        self.current_step = 0
        self.variables = {}  # Workflow-level variables
    
    def add_step(self, step: WorkflowStep):
        """Add a step to the workflow."""
        self.steps.append(step)
        self.modified_at = datetime.now()
    
    def remove_step(self, step_id: str):
        """Remove a step from the workflow."""
        self.steps = [s for s in self.steps if s.step_id != step_id]
        self.modified_at = datetime.now()
    
    def to_dict(self) -> Dict:
        """Convert workflow to dictionary."""
        return {
            'workflow_id': self.workflow_id,
            'name': self.name,
            'description': self.description,
            'steps': [step.to_dict() for step in self.steps],
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'modified_at': self.modified_at.isoformat() if self.modified_at else None,
            'variables': self.variables
        }
    
    @staticmethod
    def from_dict(data: Dict) -> 'Workflow':
        """Create workflow from dictionary."""
        workflow = Workflow(
            name=data['name'],
            description=data.get('description', '')
        )
        workflow.workflow_id = data['workflow_id']
        workflow.variables = data.get('variables', {})
        
        for step_data in data.get('steps', []):
            step = WorkflowStep.from_dict(step_data)
            workflow.add_step(step)
        
        return workflow


SCHEDULE_UNITS = ('seconds', 'minutes', 'hours', 'days')

#: The schedule strings the Automation tab composes and this class understands:
#:   hourly / daily / weekly            plain intervals
#:   HH:MM                              every day at that time
#:   weekly@HH:MM / monthly@HH:MM       every 7 days / every month at that time
#:   every_N_unit                       N >= 1, unit in SCHEDULE_UNITS
#:   once:YYYY-MM-DDTHH:MM              one shot, then forgotten


def _time_part(spec: str) -> str:
    """The HH:MM inside a schedule string, or an empty string."""
    if '@' in spec:
        return spec.split('@', 1)[1]
    return spec if len(spec) == 5 and spec[2] == ':' else ''


def _monthly_occurrence(day: int, hour: int, minute: int, after: datetime) -> datetime:
    """The next run on `day` - or that month's last day - strictly after `after`."""
    candidate = after.replace(day=min(day, calendar.monthrange(after.year, after.month)[1]),
                              hour=hour, minute=minute, second=0, microsecond=0)
    if candidate > after:
        return candidate
    year, month = (after.year + 1, 1) if after.month == 12 else (after.year, after.month + 1)
    return datetime(year, month, min(day, calendar.monthrange(year, month)[1]), hour, minute)


class TaskScheduler(QObject):
    """Hand tasks to the `schedule` library and run what is due on a polling thread."""

    def __init__(self):
        super().__init__()
        self.scheduled_tasks: Dict[str, schedule.Job] = {}
        self.is_running = False
        self._scheduler_thread = None
        # A scheduler of this instance's own. The `schedule` module's default is a
        # module global, so a second engine would run this one's jobs as well and a
        # task would fire once per live engine.
        self._jobs = schedule.Scheduler()

    def schedule_task(self, task_id: str, schedule_time: str, callback: Callable) -> bool:
        """Register one task. False means this app cannot honour that schedule."""
        spec = (schedule_time or '').strip().lower()
        if not spec or callback is None:
            return False

        self.cancel_task(task_id)
        # `schedule` has no try/except of its own: a callback that raises skips
        # _schedule_next_run(), which leaves that job due forever - and being first in the
        # sorted list each pass, it starves every other job behind it. One broken task
        # would quietly stop every schedule in the app, so nothing reaches the library raw.
        callback = self._guarded(task_id, callback)

        try:
            if spec == 'hourly':
                job = self._jobs.every().hour.do(callback)
            elif spec == 'daily':
                job = self._jobs.every().day.do(callback)
            elif spec == 'weekly':
                job = self._jobs.every().week.do(callback)
            elif _time_part(spec):
                clock = _time_part(spec)
                if spec.startswith('weekly@'):
                    # This build of `schedule` only allows .at() on days, hours and
                    # minutes, so a weekly job at a time is seven days at that time.
                    job = self._jobs.every(7).days.at(clock).do(callback)
                elif spec.startswith('monthly@'):
                    hour, minute = (int(part) for part in clock.split(':')[:2])
                    now = datetime.now()
                    first = _monthly_occurrence(now.day, hour, minute, now)
                    return self._schedule_absolute(
                        task_id, first, callback,
                        lambda past: _monthly_occurrence(first.day, hour, minute, past))
                else:
                    job = self._jobs.every().day.at(clock).do(callback)
            elif spec.startswith('every_'):
                parts = spec.split('_')
                if len(parts) != 3 or parts[2] not in SCHEDULE_UNITS:
                    return False
                interval = int(parts[1])
                if interval < 1:
                    # schedule.every(0) never returns: it spins forever in
                    # _schedule_next_run and freezes whichever thread asked for it.
                    return False
                job = getattr(self._jobs.every(interval), parts[2]).do(callback)
            elif spec.startswith('once:'):
                when = datetime.fromisoformat(spec[5:])
                if when <= datetime.now():
                    return False
                return self._schedule_absolute(task_id, when, callback, None)
            else:
                return False
        except Exception as error:
            print(f"Could not schedule task {task_id} as {schedule_time!r}: {error}")
            return False

        self.scheduled_tasks[task_id] = job
        return True

    def _schedule_absolute(self, task_id: str, when: datetime, callback: Callable,
                           rearm) -> bool:
        """Fire at an exact moment; `schedule` has no absolute API and no month unit.

        `rearm` turns the moment that just fired into the next one, or is None for a
        one-off job that takes itself out of the registry once it has run.
        """
        delay = (when - datetime.now()).total_seconds()
        if delay <= 0:
            if rearm is None:
                return False
            when = rearm(when)
            delay = (when - datetime.now()).total_seconds()

        def fire():
            finished = self.scheduled_tasks.pop(task_id, None)
            if finished is not None:
                self._jobs.cancel_job(finished)
            try:
                callback()
            finally:
                if rearm is not None:
                    self._schedule_absolute(task_id, rearm(when), callback, rearm)

        job = self._jobs.every(max(1, int(delay))).seconds.do(fire)
        job.next_run = when
        self.scheduled_tasks[task_id] = job
        return True

    @staticmethod
    def _guarded(task_id: str, callback: Callable) -> Callable:
        """Let the failure be reported here rather than inside the scheduler loop."""
        def run():
            try:
                callback()
            except Exception as error:
                print(f"Scheduled task {task_id} raised: {error}")
        return run

    def next_run(self, task_id: str):
        """When this task is next due, or None when nothing is waiting for it."""
        job = self.scheduled_tasks.get(task_id)
        return job.next_run if job is not None else None

    def cancel_task(self, task_id: str) -> bool:
        """Take a task out of the schedule registry."""
        job = self.scheduled_tasks.pop(task_id, None)
        if job is None:
            return False
        self._jobs.cancel_job(job)
        return True

    def start_scheduler(self):
        """Start the polling thread that runs whatever is due."""
        if self.is_running:
            return
        self.is_running = True
        self._scheduler_thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self._scheduler_thread.start()

    def stop_scheduler(self):
        """Stop the polling thread."""
        self.is_running = False
        if self._scheduler_thread:
            self._scheduler_thread.join(timeout=3)
            self._scheduler_thread = None

    def _run_scheduler(self):
        """Run the schedule library until asked to stop."""
        while self.is_running:
            try:
                self._jobs.run_pending()
            except Exception as error:
                print(f"Scheduler error: {error}")
            # Ten short sleeps rather than one long one: stop_scheduler() sets a
            # flag and joins, so a full second of sleep makes every teardown wait.
            for _ in range(10):
                if not self.is_running:
                    break
                time.sleep(0.1)



WATCH_EVENTS = ('created', 'modified', 'deleted', 'moved')


def _glob_list(patterns) -> List[str]:
    """Turn one filter field into a list of globs.

    The Automation tab's filters are typed by hand, so "*.obj, *.fbx", "obj fbx" and
    ".obj" are three ways of asking for the same files. A bare extension gets the star
    and the dot it needs; "*" and "*.*" mean "everything" and drop out of the list.
    """
    if patterns is None:
        return []
    if isinstance(patterns, str):
        pieces = patterns.replace(';', ',').replace('|', ',').split(',')
    else:
        pieces = [str(p) for p in patterns]

    globs = []
    for piece in pieces:
        for token in piece.split():
            token = token.strip().strip('"').strip("'")
            if not token or token in ('*', '*.*'):
                continue
            if '*' in token or '?' in token or '[' in token:
                globs.append(token)
            elif token.startswith('.'):
                globs.append('*' + token)
            else:
                globs.append('*.' + token)
    return globs


def _name_matches(filename: str, globs: List[str]) -> bool:
    """An empty glob list is "no filter", which matches every file."""
    if not globs:
        return True
    return any(fnmatch.fnmatch(filename, pattern) for pattern in globs)


def _is_excluded(filename: str, globs: List[str]) -> bool:
    """The exclude field asks the opposite question: no patterns means exclude nothing."""
    if not globs:
        return False
    return any(fnmatch.fnmatch(filename, pattern) for pattern in globs)


def _event_set(event_type) -> set:
    """Which of the four events one watched directory should report."""
    if event_type is None:
        return {'created'}
    if isinstance(event_type, str):
        if event_type in ('any', 'all'):
            return set(WATCH_EVENTS)
        return {event_type}
    events = set()
    for item in event_type:
        if item in ('any', 'all'):
            return set(WATCH_EVENTS)
        if item in WATCH_EVENTS:
            events.add(item)
    return events


class FileWatcher(QObject):
    """Watch directories for file changes."""

    file_created = pyqtSignal(str)  # file_path
    file_modified = pyqtSignal(str)  # file_path
    file_deleted = pyqtSignal(str)  # file_path
    file_moved = pyqtSignal(str, str)  # old_path, new_path

    def __init__(self, poll_seconds: float = 2.0):
        super().__init__()
        self.watched_directories: Dict[str, Dict[str, Any]] = {}
        self.is_watching = False
        self.poll_seconds = poll_seconds
        self._watcher_thread = None
        self._path_signals = {
            'created': self.file_created,
            'modified': self.file_modified,
            'deleted': self.file_deleted,
        }

    def watch_directory(self, directory: str, callback: Callable = None,
                        file_pattern: str = "*", event_type: Any = "created",
                        exclude_patterns: Any = "", min_size_kb: float = 0) -> str:
        """Watch one directory for file events and return its normalised path.

        callback is optional: the four signals are the API the Automation tab uses, and
        a tab that only wants the log should not have to invent a no-op function.
        """
        if not directory:
            raise ValueError("No directory given to watch")
        path = os.path.abspath(directory)
        if not os.path.isdir(path):
            raise ValueError(f"Cannot watch {path}: not a directory")

        info = self.watched_directories.get(path)
        if info is None:
            info = {'callbacks': [], 'last_modified': {}}
            self.watched_directories[path] = info
        info['file_pattern'] = _glob_list(file_pattern)
        info['exclude_patterns'] = _glob_list(exclude_patterns)
        info['min_size_kb'] = float(min_size_kb or 0)
        info['events'] = _event_set(event_type)
        # Record the baseline here rather than on the thread's first pass: a file that
        # lands between this call and that pass is an event, not part of what was
        # already there. Re-registering a folder re-baselines it with its new filters.
        info['last_modified'] = self._snapshot(path, info)

        if callback is not None:
            info['callbacks'].append(callback)

        if not self.is_watching:
            self.start_watching()
        return path

    def is_watched(self, directory: str) -> bool:
        """Whether this exact directory is already in the watch list."""
        if not directory:
            return False
        return os.path.abspath(directory) in self.watched_directories

    def unwatch_directory(self, directory: str):
        """Stop watching directory."""
        if not directory:
            return
        self.watched_directories.pop(os.path.abspath(directory), None)

    def start_watching(self):
        """Start file watcher thread."""
        if self.is_watching:
            return

        self.is_watching = True
        self._watcher_thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._watcher_thread.start()

    def stop_watching(self):
        """Stop file watcher."""
        self.is_watching = False
        if self._watcher_thread:
            self._watcher_thread.join(timeout=2)
            self._watcher_thread = None

    def _snapshot(self, directory: str, info: Dict[str, Any]) -> Dict[str, tuple]:
        """Every file in this folder that passes its filters, as path -> (mtime, size)."""
        found: Dict[str, tuple] = {}
        smallest = float(info['min_size_kb']) * 1024.0
        for filename in os.listdir(directory):
            if not _name_matches(filename, info['file_pattern']):
                continue
            if _is_excluded(filename, info['exclude_patterns']):
                continue
            filepath = os.path.join(directory, filename)
            try:
                if not os.path.isfile(filepath):
                    continue
                stat = os.stat(filepath)
            except OSError:
                continue
            if stat.st_size < smallest:
                continue
            found[filepath] = (stat.st_mtime, stat.st_size)
        return found

    def _diff(self, info: Dict[str, Any], current: Dict[str, tuple]) -> List[tuple]:
        """What changed since the last pass, as (event, path, other_path) tuples.

        A file that left one path and appeared at another in the same pass with the same
        mtime and size is reported as moved rather than deleted plus created; that is the
        only way a polling watcher can tell the two apart, and it is what the tab's
        "File Moved" checkbox asks for.

        The folder's baseline was recorded when it was registered, so what was already
        on disk when watching started is never announced as created.
        """
        known = info['last_modified']

        appeared = [p for p in current if p not in known]
        vanished = [p for p in known if p not in current]

        events: List[tuple] = []
        for old in list(vanished):
            match = next((new for new in appeared if current[new] == known[old]), None)
            if match is None:
                continue
            appeared.remove(match)
            vanished.remove(old)
            events.append(('moved', match, old))

        for old in vanished:
            events.append(('deleted', old, None))
        for new in appeared:
            events.append(('created', new, None))
        for path in current:
            if path in known and current[path][0] > known[path][0]:
                events.append(('modified', path, None))

        info['last_modified'] = dict(current)
        return events

    def _watch_loop(self):
        """Poll every watched folder and report what changed."""
        while self.is_watching:
            for directory in list(self.watched_directories):
                if not os.path.isdir(directory):
                    continue
                try:
                    info = self.watched_directories.get(directory)
                    if info is None:
                        continue
                    current = self._snapshot(directory, info)
                    for event, path, other in self._diff(info, current):
                        self._report(path, event, other)
                except Exception as e:
                    print(f"Error watching directory {directory}: {e}")

            time.sleep(self.poll_seconds)

    def _report(self, file_path: str, event: str, other_path: str = None):
        """Tell both APIs about one change: the Qt signal and the python callback.

        Only the callback used to be reached, so the signals the Automation tab connects
        to had no emitter anywhere in the class. Events the folder was not asked to
        report are dropped here rather than at each caller.
        """
        info = self.watched_directories.get(os.path.dirname(file_path))
        if info is None or event not in info['events']:
            return

        if event == 'moved':
            self.file_moved.emit(other_path or '', file_path)
        else:
            self._path_signals[event].emit(file_path)

        for callback in list(info['callbacks']):
            try:
                callback(file_path, event)
            except Exception as error:
                print(f"Watch callback failed for {file_path}: {error}")

class WorkflowExecutor:
    """Execute workflow steps sequentially."""
    
    def __init__(self, task_executor=None):
        self.task_executor = task_executor
        
    def execute_workflow(self, workflow: Workflow, callback: Optional[Callable] = None) -> bool:
        """Execute workflow steps."""
        results = []
        
        for step_idx, step in enumerate(workflow.steps):
            step_name = step.get('name', f'Step {step_idx + 1}')
            task_type = step.get('task_type')
            parameters = step.get('parameters', {})
            
            print(f"Executing workflow step: {step_name}")
            
            # Execute step
            result = self._execute_step(task_type, parameters)
            
            if not result.get('success', False):
                # Step failed
                if callback:
                    callback(False, {
                        'workflow': workflow.name,
                        'failed_step': step_name,
                        'error': result.get('error', 'Unknown error')
                    })
                return False
            
            results.append(result)
            
            # Check if there's a delay before next step
            delay = step.get('delay', 0)
            if delay > 0:
                time.sleep(delay)
        
        # All steps completed
        if callback:
            callback(True, {
                'workflow': workflow.name,
                'steps_completed': len(results),
                'results': results
            })
        
        return True
    
    def _execute_step(self, task_type: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a single workflow step."""
        # Use ActionRegistry to execute the action
        # In workflow steps, 'action' field usually maps to 'task_type' here
        # But wait, WorkflowStep has 'action' field, while Task has 'task_type'.
        # The execute_workflow method extracts 'task_type' from step.get('task_type').
        # Let's assume 'task_type' is the action ID in the registry.
        
        if not task_type:
            return {'success': False, 'error': 'No task type/action specified'}
            
        return ActionRegistry.execute(task_type, **parameters)


class BatchProcessor(QObject):
    """Process multiple items in batch."""
    
    progress_updated = pyqtSignal(int, int, str)  # current, total, current_item
    batch_completed = pyqtSignal(dict)  # results
    
    def __init__(self):
        super().__init__()
        self.current_batch = None
        self.is_processing = False
        
    def process_batch(self, items: List[Any], operation: Callable,
                     progress_callback: Optional[Callable] = None) -> List[Dict[str, Any]]:
        """Process batch of items."""
        results = []
        total = len(items)
        
        for idx, item in enumerate(items):
            # Emit progress signal
            self.progress_updated.emit(idx + 1, total, str(item))
            
            try:
                result = operation(item)
                results.append({
                    'item': item,
                    'success': True,
                    'result': result
                })
            except Exception as e:
                results.append({
                    'item': item,
                    'success': False,
                    'error': str(e)
                })
            
            if progress_callback:
                progress_callback(idx + 1, total, item)
        
        # Emit completion signal
        self.batch_completed.emit({'results': results, 'total': total})
        
        return results


class ConditionEvaluator:
    """Evaluate conditions for trigger-based automation."""
    
    @staticmethod
    def evaluate_condition(condition: Dict[str, Any], context: Dict[str, Any]) -> bool:
        """Evaluate a condition."""
        condition_type = condition.get('type')
        
        if condition_type == 'file_exists':
            filepath = condition.get('filepath')
            return os.path.exists(filepath)
        
        elif condition_type == 'file_size':
            filepath = condition.get('filepath')
            operator = condition.get('operator', '>')
            threshold = condition.get('threshold', 0)
            
            if not os.path.exists(filepath):
                return False
            
            size = os.path.getsize(filepath)
            
            if operator == '>':
                return size > threshold
            elif operator == '<':
                return size < threshold
            elif operator == '==':
                return size == threshold
            
        elif condition_type == 'time_range':
            start_time = condition.get('start_time')
            end_time = condition.get('end_time')
            current_time = datetime.now().time()
            
            start = datetime.strptime(start_time, '%H:%M').time()
            end = datetime.strptime(end_time, '%H:%M').time()
            
            return start <= current_time <= end
        
        elif condition_type == 'variable':
            var_name = condition.get('variable')
            operator = condition.get('operator', '==')
            value = condition.get('value')
            
            if var_name not in context:
                return False
            
            var_value = context[var_name]
            
            if operator == '==':
                return var_value == value
            elif operator == '!=':
                return var_value != value
            elif operator == '>':
                return var_value > value
            elif operator == '<':
                return var_value < value
        
        return False


class AutomationEngine(QObject):
    """Main automation engine coordinating all automation features."""
    
    task_started = pyqtSignal(str)  # task_id
    task_progress = pyqtSignal(str, int, str)  # task_id, progress, message
    task_completed = pyqtSignal(str, bool, dict)  # task_id, success, result
    workflow_started = pyqtSignal(str)  # workflow_id
    workflow_completed = pyqtSignal(str, dict)  # workflow_id, result
    workflow_failed = pyqtSignal(str, str)  # workflow_id, error
    workflow_progress = pyqtSignal(str, int, int, str)  # workflow_id, current_step, total_steps, step_name
    
    def __init__(self):
        super().__init__()
        self.scheduler = TaskScheduler()
        self.file_watcher = FileWatcher()
        self.workflow_executor = WorkflowExecutor(self)
        self.batch_processor = BatchProcessor()
        self.condition_evaluator = ConditionEvaluator()
        
        self.tasks: Dict[str, AutomationTask] = {}
        self.workflows: Dict[str, Workflow] = {}
        self.triggers: Dict[str, Dict[str, Any]] = {}
        
        # Load saved workflows and tasks
        ActionRegistry.register_default_actions()
        self._load_workflows()
        self._load_tasks()
    
    def _tasks_file(self) -> str:
        return os.path.join(app_data_dir(), 'tasks.json')

    def _save_tasks(self):
        """Write every task, with its schedule and its last verdict."""
        try:
            data = [task.to_dict() for task in self.tasks.values()]
            with open(self._tasks_file(), 'w', encoding='utf-8') as handle:
                json.dump(data, handle, indent=2)
        except Exception as error:
            print(f"Could not save tasks: {error}")

    def _load_tasks(self):
        """Read the tasks back and put the ones that are due on the scheduler.

        A one-off whose moment has already passed cannot fire, so it comes back
        CANCELLED rather than as something the user might still wait for.
        """
        path = self._tasks_file()
        if not os.path.exists(path):
            return

        try:
            with open(path, encoding='utf-8') as handle:
                data = json.load(handle)
        except Exception as error:
            print(f"Could not read {path}: {error}")
            return

        if not isinstance(data, list):
            print(f"Ignoring {path}: expected a list of task records")
            return

        for record in data:
            try:
                task = AutomationTask.from_dict(record)
            except Exception as error:
                print(f"Skipping an unreadable task record: {error}")
                continue
            self.tasks[task.task_id] = task
            if task.enabled and task.schedule_time and not self.schedule_task(task.task_id, task.schedule_time):
                task.status = TaskStatus.CANCELLED

        if data:
            self._save_tasks()


    def create_task(self, name: str, task_type: str, parameters: Dict[str, Any],
                    enabled: bool = True) -> str:
        """Store a task. Putting it on the calendar is `schedule_task`'s job."""
        # A millisecond stamp, walked forward while it is taken. The old retry reused a
        # counter that only changes once the task is stored, so a second collision looped.
        stamp = int(time.time() * 1000)
        task_id = f"task_{stamp}"
        while task_id in self.tasks:
            stamp += 1
            task_id = f"task_{stamp}"

        self.tasks[task_id] = AutomationTask(
            task_id=task_id,
            name=name,
            task_type=task_type,
            parameters=parameters or {},
            enabled=enabled
        )
        self._save_tasks()
        return task_id

    def update_task(self, task_id: str, name: str = None, task_type: str = None,
                    parameters: Dict[str, Any] = None, enabled: bool = None) -> bool:
        """Change the parts of a task that were given and leave the rest alone."""
        task = self.tasks.get(task_id)
        if task is None:
            return False
        if name is not None:
            task.name = name
        if task_type is not None:
            task.task_type = task_type
        if parameters is not None:
            task.parameters = parameters
        if enabled is not None:
            task.enabled = enabled
            if not enabled:
                self.scheduler.cancel_task(task_id)
                if task.status == TaskStatus.SCHEDULED:
                    task.status = TaskStatus.CANCELLED
        self._save_tasks()
        return True


    def execute_task(self, task_id: str) -> bool:
        """Run one task now. The action's own verdict decides the status."""
        task = self.tasks.get(task_id)
        if task is None:
            return False
        if not task.enabled:
            self.task_completed.emit(task_id, False, {'error': f"'{task.name}' is disabled"})
            return False

        task.status = TaskStatus.RUNNING
        task.started_at = time.time()
        self.task_started.emit(task_id)

        try:
            result = self._execute_task_type(task)
        except Exception as error:
            success = False
            result = {'success': False, 'error': str(error)}
        else:
            success = bool(result.get('success', False)) if isinstance(result, dict) else result is not None
            if not success and isinstance(result, dict) and not result.get('error'):
                result = dict(result, error='the action reported no reason')

        task.status = TaskStatus.COMPLETED if success else TaskStatus.FAILED
        task.completed_at = time.time()
        task.result = result
        task.error = None if success else str(result.get('error'))
        self._save_tasks()
        self.task_completed.emit(task_id, success, result)
        return success

    def schedule_task(self, task_id: str, schedule_time: str) -> bool:
        """Put an existing task on the scheduler and remember when it is due."""
        task = self.tasks.get(task_id)
        if task is None:
            return False

        def execute_callback():
            self.execute_task(task_id)

        if not self.scheduler.schedule_task(task_id, schedule_time, execute_callback):
            return False

        task.schedule_time = schedule_time
        task.status = TaskStatus.SCHEDULED
        self._save_tasks()
        return True

    def cancel_task(self, task_id: str) -> bool:
        """Take a task off the scheduler; it stays saved and can be scheduled again."""
        task = self.tasks.get(task_id)
        if task is None:
            return False

        self.scheduler.cancel_task(task_id)
        task.schedule_time = None
        task.status = TaskStatus.CANCELLED
        self._save_tasks()
        return True

    def delete_task(self, task_id: str) -> bool:
        """Remove a task from the scheduler, the table and the file."""
        task = self.tasks.get(task_id)
        if task is None:
            return False

        self.scheduler.cancel_task(task_id)
        del self.tasks[task_id]
        self._save_tasks()
        return True

    def set_task_enabled(self, task_id: str, enabled: bool) -> bool:
        """Enable or disable a task, keeping the scheduler in step with it."""
        task = self.tasks.get(task_id)
        if task is None:
            return False

        task.enabled = enabled
        if not enabled:
            self.scheduler.cancel_task(task_id)
            if task.status == TaskStatus.SCHEDULED:
                task.status = TaskStatus.CANCELLED
        elif task.schedule_time:
            self.schedule_task(task_id, task.schedule_time)
        self._save_tasks()
        return True

    def next_run(self, task_id: str):
        """When this task is next due, or None."""
        return self.scheduler.next_run(task_id)


    def create_workflow(self, name: str, description: str, steps: List[Dict[str, Any]]) -> str:
        """Create a new workflow."""
        workflow_id = f"workflow_{int(time.time() * 1000)}"
        
        workflow = Workflow(
            workflow_id=workflow_id,
            name=name,
            description=description,
            steps=steps
        )
        
        self.workflows[workflow_id] = workflow
        self._save_workflows()
        
        return workflow_id
    
    def execute_workflow(self, workflow_id: str) -> bool:
        """Execute a workflow."""
        if workflow_id not in self.workflows:
            return False
        
        workflow = self.workflows[workflow_id]
        
        self.workflow_started.emit(workflow_id)
        
        def completion_callback(success, result):
            self.workflow_completed.emit(workflow_id, success, result)
        
        # Execute in thread to avoid blocking
        thread = threading.Thread(
            target=self.workflow_executor.execute_workflow,
            args=(workflow, completion_callback),
            daemon=True
        )
        thread.start()
        
        return True
    
    def create_trigger(self, name: str, trigger_type: TriggerType, 
                      config: Dict[str, Any], action: Callable) -> str:
        """Create an automation trigger."""
        trigger_id = f"trigger_{int(time.time() * 1000)}"
        
        self.triggers[trigger_id] = {
            'name': name,
            'type': trigger_type,
            'config': config,
            'action': action,
            'enabled': True
        }
        
        # Setup trigger based on type
        if trigger_type == TriggerType.TIME_BASED:
            schedule_time = config.get('schedule')
            self.scheduler.schedule_task(trigger_id, schedule_time, action)
        
        elif trigger_type == TriggerType.FILE_WATCH:
            directory = config.get('directory')
            if not directory or not os.path.isdir(directory):
                raise ValueError(f"File watch trigger '{name}' needs an existing directory")
            file_pattern = config.get('file_pattern', '*')
            event_type = config.get('event_type', 'created')
            
            def file_callback(filepath, event):
                action(filepath, event)
            
            self.file_watcher.watch_directory(directory, file_callback, file_pattern, event_type)
        
        return trigger_id
    
    def disable_trigger(self, trigger_id: str) -> bool:
        """Disable a trigger."""
        if trigger_id not in self.triggers:
            return False
        
        self.triggers[trigger_id]['enabled'] = False
        return True
    
    def batch_process(self, items: List[Any], operation: Callable,
                     progress_callback: Optional[Callable] = None) -> List[Dict[str, Any]]:
        """Process items in batch."""
        return self.batch_processor.process_batch(items, operation, progress_callback)
    
    def start(self):
        """Start automation engine."""
        self.scheduler.start_scheduler()
        # File watcher starts automatically when directories are added
    
    def stop(self):
        """Stop automation engine."""
        self.scheduler.stop_scheduler()
        self.file_watcher.stop_watching()
    
    def _execute_task_type(self, task: AutomationTask) -> Dict[str, Any]:
        """Run the task's action id through the registry; task_type *is* the action id."""
        if not task.task_type:
            return {'success': False, 'error': 'this task has no action chosen'}
        return ActionRegistry.execute(task.task_type, **task.parameters)

    def _workflows_file(self) -> str:
        return os.path.join(app_data_dir(), 'workflows.json')

    def _save_workflows(self):
        """Write every workflow, keyed by id, with its steps."""
        try:
            data = {wid: workflow.to_dict() for wid, workflow in self.workflows.items()}
            with open(self._workflows_file(), 'w', encoding='utf-8') as handle:
                json.dump(data, handle, indent=2)
        except Exception as error:
            print(f"Could not save workflows: {error}")

    def _load_workflows(self):
        """Rebuild saved workflows through `Workflow.from_dict`.

        This used to call `Workflow(workflow_id=..., steps=..., enabled=...,
        created_at=...)`, which is not that constructor: every record raised TypeError
        into the except, so a workflow that had been saved was silently never seen again.
        """
        path = self._workflows_file()
        if not os.path.exists(path):
            return

        try:
            with open(path, encoding='utf-8') as handle:
                data = json.load(handle)
            for wid, record in (data or {}).items():
                self.workflows[wid] = Workflow.from_dict(record)
        except Exception as error:
            print(f"Could not read workflows from {path}: {error}")
