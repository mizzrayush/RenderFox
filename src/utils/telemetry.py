"""
Telemetry Manager for RenderFox.
Handles logging of usage statistics, errors, and performance metrics.
Currently supports local logging only.
"""

import os
import json
import logging
import platform
import uuid
from datetime import datetime
from PyQt6.QtCore import QObject, QSettings

# The packaged build has no console (`RenderFox.spec`: console=False): the line this module
# used to print on a failed write was written where nobody could read it.
logger = logging.getLogger(__name__)

class TelemetryManager(QObject):
    """Manages application telemetry and logging."""
    
    def __init__(self):
        super().__init__()
        self.enabled = False
        self.session_id = str(uuid.uuid4())
        self.settings = QSettings("RenderFox", "RenderFox")
        
        # Setup logging
        self.log_dir = os.path.join(os.path.expanduser("~"), ".renderfox", "logs")
        os.makedirs(self.log_dir, exist_ok=True)
        
        self.log_file = os.path.join(self.log_dir, f"telemetry_{datetime.now().strftime('%Y%m%d')}.jsonl")
        
        # Initialize state from settings
        self.update_settings()
        
        if self.enabled:
            self.track_event("session_start", {
                "os": platform.system(),
                "os_release": platform.release(),
                "python_version": platform.python_version(),
                "session_id": self.session_id
            })

    def update_settings(self):
        """Update telemetry status from application settings."""
        # Default to False for privacy
        self.enabled = self.settings.value("Advanced/telemetry_enabled", False, type=bool)

    def track_event(self, event_name, properties=None):
        """
        Log a telemetry event.
        
        Args:
            event_name (str): Name of the event (e.g., "app_started", "mesh_loaded")
            properties (dict, optional): Additional data associated with the event
        """
        if not self.enabled:
            return
            
        if properties is None:
            properties = {}
            
        event_data = {
            "timestamp": datetime.now().isoformat(),
            "event": event_name,
            "session_id": self.session_id,
            "properties": properties
        }
        
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(event_data) + "\n")
        except Exception as e:
            # Nothing reaches the user's screen from here: the write is recorded on the log
            # channel and the event is dropped. It used to be printed to a stream the packaged
            # build does not have, which was silent in a way that could not be read.
            logger.warning("Telemetry error: %s", e)

    def track_error(self, error_type, message, stack_trace=None):
        """Log an error event."""
        self.track_event("error", {
            "type": error_type,
            "message": message,
            "stack_trace": stack_trace
        })

    def track_performance(self, operation, duration_ms):
        """Log a performance metric."""
        self.track_event("performance", {
            "operation": operation,
            "duration_ms": duration_ms
        })

# Global instance
_telemetry_instance = None

def get_telemetry():
    """Get the global telemetry instance."""
    global _telemetry_instance
    if _telemetry_instance is None:
        _telemetry_instance = TelemetryManager()
    return _telemetry_instance
