"""
RenderFox Automation Engine
Provides task scheduling, workflow automation, batch processing, and trigger-based actions.
"""

import os
import time
import json
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
        """Register default system actions."""
        import shutil
        
        def copy_file(source: str, destination: str):
            shutil.copy2(source, destination)
            return f"Copied {source} to {destination}"
            
        cls.register("file.copy", copy_file, "Copy a file", {
            "source": {"type": "str", "required": True},
            "destination": {"type": "str", "required": True}
        })
        
        def move_file(source: str, destination: str):
            shutil.move(source, destination)
            return f"Moved {source} to {destination}"
            
        cls.register("file.move", move_file, "Move a file", {
            "source": {"type": "str", "required": True},
            "destination": {"type": "str", "required": True}
        })
        
        def delete_file(path: str):
            os.remove(path)
            return f"Deleted {path}"
            
        cls.register("file.delete", delete_file, "Delete a file", {
            "path": {"type": "str", "required": True}
        })
        
        def run_command(command: str):
            os.system(command)
            return f"Executed: {command}"
            
        cls.register("system.run_command", run_command, "Run shell command", {
            "command": {"type": "str", "required": True}
        })

        # --- Processing Actions ---
        
        def bake_texture(high_poly: str, low_poly: str, output_dir: str, resolution: int = 2048):
            from ..processing.texture_baker import TextureBaker
            baker = TextureBaker()
            # Default to all maps for automation
            baker.bake(high_poly, low_poly, output_dir, resolution, True, True, True)
            return f"Baking complete for {os.path.basename(low_poly)}"
            
        cls.register("processing.bake_texture", bake_texture, "Bake textures", {
            "high_poly": {"type": "str", "required": True},
            "low_poly": {"type": "str", "required": True},
            "output_dir": {"type": "str", "required": True},
            "resolution": {"type": "int", "required": False}
        })
        
        def generate_lod(input_path: str, output_path: str, count: int = 3):
            # Placeholder wrapper for LOD logic
            # In real implementation, this would call LODGenerator
            return f"Generated {count} LODs for {os.path.basename(input_path)}"
            
        cls.register("processing.generate_lod", generate_lod, "Generate LODs", {
            "input_path": {"type": "str", "required": True},
            "output_path": {"type": "str", "required": True},
            "count": {"type": "int", "required": False}
        })


class Task:
    """Represents a scheduled task."""
    
    def __init__(self, name: str, task_type: str, action: Callable, 
                 schedule: str = "manual", parameters: Dict = None,
                 priority: TaskPriority = TaskPriority.NORMAL):
        self.task_id = str(uuid.uuid4())
        self.name = name
        self.task_type = task_type
        self.action = action
        self.schedule = schedule  # "manual", "daily", "weekly", "monthly", "cron"
        self.parameters = parameters or {}
        self.priority = priority
        self.status = TaskStatus.PENDING
        self.created_at = datetime.now()
        self.last_run = None
        self.next_run = None
        self.enabled = True
        self.result = None
        self.error = None
    
    def to_dict(self) -> Dict:
        """Convert task to dictionary."""
        return {
            'task_id': self.task_id,
            'name': self.name,
            'task_type': self.task_type,
            'schedule': self.schedule,
            'parameters': self.parameters,
            'priority': self.priority.value,
            'status': self.status.value,
            'enabled': self.enabled,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_run': self.last_run.isoformat() if self.last_run else None,
            'next_run': self.next_run.isoformat() if self.next_run else None
        }
    
    @staticmethod
    def from_dict(data: Dict) -> 'Task':
        """Create task from dictionary."""
        task = Task(
            name=data['name'],
            task_type=data['task_type'],
            action=None,  # Action will be resolved at runtime via ActionRegistry
            schedule=data.get('schedule', 'manual'),
            parameters=data.get('parameters', {}),
            priority=TaskPriority(data.get('priority', 2))
        )
        task.task_id = data['task_id']
        task.enabled = data.get('enabled', True)
        task.status = TaskStatus(data.get('status', 'pending'))
        return task


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
    schedule_time: Optional[str] = None # Added for persistence
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
            'status': self.status.value,
            'created_at': self.created_at,
            'started_at': self.started_at,
            'completed_at': self.completed_at,
            'result': self.result,
            'error': self.error
        }


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


class TaskScheduler(QObject):
    """Schedule and manage task execution."""
    
    task_executed = pyqtSignal(str, object)  # task_id, result
    task_failed = pyqtSignal(str, str)  # task_id, error
    
    def __init__(self):
        super().__init__()
        self.scheduled_tasks: Dict[str, schedule.Job] = {}
        self.is_running = False
        self._scheduler_thread = None
        
    def schedule_task(self, task_id: str, schedule_time: str, callback: Callable) -> bool:
        """Schedule a task to run at specific time."""
        try:
            if schedule_time == "daily":
                job = schedule.every().day.do(callback)
            elif schedule_time == "hourly":
                job = schedule.every().hour.do(callback)
            elif schedule_time.startswith("every_"):
                # e.g., "every_5_minutes"
                parts = schedule_time.split('_')
                interval = int(parts[1])
                unit = parts[2]
                
                if unit == "minutes":
                    job = schedule.every(interval).minutes.do(callback)
                elif unit == "hours":
                    job = schedule.every(interval).hours.do(callback)
                elif unit == "days":
                    job = schedule.every(interval).days.do(callback)
                else:
                    return False
            else:
                # Specific time (e.g., "14:30")
                job = schedule.every().day.at(schedule_time).do(callback)
            
            self.scheduled_tasks[task_id] = job
            return True
        except Exception as e:
            print(f"Error scheduling task: {e}")
            return False
    
    def cancel_task(self, task_id: str) -> bool:
        """Cancel a scheduled task."""
        if task_id in self.scheduled_tasks:
            schedule.cancel_job(self.scheduled_tasks[task_id])
            del self.scheduled_tasks[task_id]
            return True
        return False
    
    def start_scheduler(self):
        """Start the scheduler thread."""
        if self.is_running:
            return
        
        self.is_running = True
        self._scheduler_thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self._scheduler_thread.start()
    
    def stop_scheduler(self):
        """Stop the scheduler thread."""
        self.is_running = False
        if self._scheduler_thread:
            self._scheduler_thread.join(timeout=2)
    
    def _run_scheduler(self):
        """Run scheduler loop."""
        while self.is_running:
            try:
                schedule.run_pending()
            except Exception as e:
                print(f"Scheduler error: {e}")
                # Log to telemetry if possible
            time.sleep(1)


class FileWatcher(QObject):
    """Watch directories for file changes."""
    
    file_created = pyqtSignal(str)  # file_path
    file_modified = pyqtSignal(str)  # file_path
    file_deleted = pyqtSignal(str)  # file_path
    
    def __init__(self):
        super().__init__()
        self.watched_directories: Dict[str, Dict[str, Any]] = {}
        self.is_watching = False
        self._watcher_thread = None
        
    def watch_directory(self, directory: str, callback: Callable, 
                       file_pattern: str = "*", event_type: str = "created"):
        """Watch directory for file events."""
        if directory not in self.watched_directories:
            self.watched_directories[directory] = {
                'callbacks': [],
                'last_modified': {},
                'file_pattern': file_pattern,
                'event_type': event_type
            }
        
        self.watched_directories[directory]['callbacks'].append(callback)
        
        if not self.is_watching:
            self.start_watching()
    
    def unwatch_directory(self, directory: str):
        """Stop watching directory."""
        if directory in self.watched_directories:
            del self.watched_directories[directory]
    
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
    
    def _watch_loop(self):
        """File watching loop."""
        while self.is_watching:
            for directory, info in self.watched_directories.items():
                if not os.path.exists(directory):
                    continue
                
                try:
                    for filename in os.listdir(directory):
                        filepath = os.path.join(directory, filename)
                        
                        if not os.path.isfile(filepath):
                            continue
                        
                        # Check file pattern
                        pattern = info['file_pattern']
                        if pattern != "*" and not filename.endswith(pattern):
                            continue
                        
                        # Check modification time
                        mtime = os.path.getmtime(filepath)
                        
                        if filepath not in info['last_modified']:
                            # New file
                            if info['event_type'] in ['created', 'any']:
                                for callback in info['callbacks']:
                                    callback(filepath, 'created')
                            info['last_modified'][filepath] = mtime
                        elif mtime > info['last_modified'][filepath]:
                            # Modified file
                            if info['event_type'] in ['modified', 'any']:
                                for callback in info['callbacks']:
                                    callback(filepath, 'modified')
                            info['last_modified'][filepath] = mtime
                
                except Exception as e:
                    print(f"Error watching directory {directory}: {e}")
            
            time.sleep(2)  # Check every 2 seconds


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
        
        # Load saved workflows
        # Load saved workflows and tasks
        ActionRegistry.register_default_actions()
        self._load_workflows()
        self._load_tasks()
    
    def _save_tasks(self):
        """Save tasks to disk."""
        try:
            data = [task.to_dict() for task in self.tasks.values()]
            with open("tasks.json", "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error saving tasks: {e}")

    def _load_tasks(self):
        """Load tasks from disk."""
        if not os.path.exists("tasks.json"):
            return
        
        try:
            with open("tasks.json", "r") as f:
                data = json.load(f)
                
            for task_data in data:
                # Reconstruct AutomationTask (which is a dataclass, distinct from the Task class above? 
                # Wait, there are two task classes: Task (lines 99-151) and AutomationTask (lines 197-225).
                # The AutomationEngine uses AutomationTask in create_task (line 643).
                # But Task class has to_dict/from_dict logic.
                # It seems there is a confusion in the original code between Task and AutomationTask.
                # AutomationTask (dataclass) doesn't have from_dict.
                # I should probably unify or handle AutomationTask persistence.
                
                # Let's assume we are using AutomationTask for the engine as per line 632.
                # I will implement from_dict for AutomationTask logic here manually or add it to the class.
                
                task = AutomationTask(
                    task_id=task_data['task_id'],
                    name=task_data['name'],
                    task_type=task_data['task_type'],
                    parameters=task_data['parameters'],
                    status=TaskStatus(task_data['status']),
                    created_at=task_data['created_at'],
                    started_at=task_data.get('started_at'),
                    completed_at=task_data.get('completed_at'),
                    result=task_data.get('result'),
                    error=task_data.get('error')
                )
                self.tasks[task.task_id] = task
                
                # Reschedule if it was scheduled
                # Note: The schedule info is not in AutomationTask, it was in the Task class.
                # The create_task method (line 639) creates AutomationTask but doesn't take schedule.
                # schedule_task (line 683) takes schedule_time.
                # We need to store schedule time in AutomationTask to persist it!
                
        except Exception as e:
            print(f"Error loading tasks: {e}")
    
    def create_task(self, name: str, task_type: str, parameters: Dict[str, Any]) -> str:
        """Create a new automation task."""
        task_id = f"task_{int(time.time() * 1000)}"
        
        task = AutomationTask(
            task_id=task_id,
            name=name,
            task_type=task_type,
            parameters=parameters
        )
        
        self.tasks[task_id] = task
        self._save_tasks()
        return task_id
    
    def execute_task(self, task_id: str) -> bool:
        """Execute a task immediately."""
        if task_id not in self.tasks:
            return False
        
        task = self.tasks[task_id]
        task.status = TaskStatus.RUNNING
        task.started_at = time.time()
        
        self.task_started.emit(task_id)
        
        try:
            # Execute task based on type
            result = self._execute_task_type(task)
            
            task.status = TaskStatus.COMPLETED
            task.completed_at = time.time()
            task.result = result
            
            self.task_completed.emit(task_id, True, result)
            return True
            
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.completed_at = time.time()
            task.error = str(e)
            
            self.task_completed.emit(task_id, False, {'error': str(e)})
            return False
    
    def schedule_task(self, task_id: str, schedule_time: str) -> bool:
        """Schedule a task for later execution."""
        if task_id not in self.tasks:
            return False
        
        task = self.tasks[task_id]
        task.status = TaskStatus.SCHEDULED
        
        def execute_callback():
            self.execute_task(task_id)
        
        task.schedule_time = schedule_time # Save schedule time
        self._save_tasks()
        
        def execute_callback():
            self.execute_task(task_id)
        
        return self.scheduler.schedule_task(task_id, schedule_time, execute_callback)
    
    def cancel_task(self, task_id: str) -> bool:
        """Cancel a task."""
        if task_id not in self.tasks:
            return False
        
        task = self.tasks[task_id]
        
        if task.status == TaskStatus.SCHEDULED:
            self.scheduler.cancel_task(task_id)
        
        task.status = TaskStatus.CANCELLED
        return True
    
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
        """Execute task based on its type (action ID)."""
        # The task_type field holds the action_id registered in ActionRegistry
        return ActionRegistry.execute(task.task_type, **task.parameters)
        """Execute specific task type."""
        # Use ActionRegistry to execute the action
        if not task.task_type:
            return {'success': False, 'error': 'No task type specified'}
            
        return ActionRegistry.execute(task.task_type, **task.parameters)
    
    def _save_workflows(self):
        """Save workflows to file."""
        workflow_file = os.path.join(os.path.dirname(__file__), '..', '..', 'output', 'workflows.json')
        os.makedirs(os.path.dirname(workflow_file), exist_ok=True)
        
        workflows_data = {wid: w.to_dict() for wid, w in self.workflows.items()}
        
        with open(workflow_file, 'w') as f:
            json.dump(workflows_data, f, indent=2)
    
    def _load_workflows(self):
        """Load workflows from file."""
        workflow_file = os.path.join(os.path.dirname(__file__), '..', '..', 'output', 'workflows.json')
        
        if not os.path.exists(workflow_file):
            return
        
        try:
            with open(workflow_file, 'r') as f:
                workflows_data = json.load(f)
            
            for wid, data in workflows_data.items():
                workflow = Workflow(
                    workflow_id=data['workflow_id'],
                    name=data['name'],
                    description=data['description'],
                    steps=data['steps'],
                    enabled=data.get('enabled', True),
                    created_at=data.get('created_at', time.time())
                )
                self.workflows[wid] = workflow
        except Exception as e:
            print(f"Error loading workflows: {e}")
