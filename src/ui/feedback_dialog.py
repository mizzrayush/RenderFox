"""
Feedback Dialog
Allows users to submit bug reports and feature requests.
"""

import sys
import os
import json
import platform
from datetime import datetime
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QLineEdit, QTextEdit, QComboBox, QCheckBox, 
                             QPushButton, QMessageBox, QFormLayout)
from PyQt6.QtCore import Qt

class FeedbackDialog(QDialog):
    """Dialog for collecting user feedback."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Send Feedback")
        self.setMinimumWidth(400)
        self.setMinimumHeight(500)
        
        self.init_ui()
        
    def init_ui(self):
        """Initialize the UI components."""
        layout = QVBoxLayout(self)
        
        # Header
        header = QLabel("We value your feedback!")
        header.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(header)
        
        layout.addWidget(QLabel("Help us improve RenderFox by sharing your thoughts."))
        
        # Form
        form_layout = QFormLayout()
        
        # Feedback Type
        self.type_combo = QComboBox()
        self.type_combo.addItems(["Bug Report", "Feature Request", "General Feedback", "Other"])
        form_layout.addRow("Type:", self.type_combo)
        
        # Email (Optional)
        self.email_edit = QLineEdit()
        self.email_edit.setPlaceholderText("optional@example.com")
        form_layout.addRow("Email:", self.email_edit)
        
        layout.addLayout(form_layout)
        
        # Description
        layout.addWidget(QLabel("Description:"))
        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText("Please describe your issue or idea in detail...")
        layout.addWidget(self.description_edit)
        
        # System Info
        self.sys_info_cb = QCheckBox("Include system information")
        self.sys_info_cb.setChecked(True)
        self.sys_info_cb.setToolTip("Includes OS version, Python version, and app version.")
        layout.addWidget(self.sys_info_cb)
        
        # Buttons
        button_layout = QHBoxLayout()
        self.submit_btn = QPushButton("Send Feedback")
        self.submit_btn.clicked.connect(self.submit_feedback)
        self.submit_btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; padding: 5px;")
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        
        button_layout.addStretch()
        button_layout.addWidget(self.cancel_btn)
        button_layout.addWidget(self.submit_btn)
        
        layout.addLayout(button_layout)
        
    def submit_feedback(self):
        """Process and save the feedback."""
        description = self.description_edit.toPlainText().strip()
        
        if not description:
            QMessageBox.warning(self, "Missing Information", "Please provide a description.")
            return
            
        feedback_data = {
            "timestamp": datetime.now().isoformat(),
            "type": self.type_combo.currentText(),
            "email": self.email_edit.text().strip(),
            "description": description,
        }
        
        if self.sys_info_cb.isChecked():
            feedback_data["system_info"] = {
                "os": platform.system(),
                "os_release": platform.release(),
                "os_version": platform.version(),
                "python_version": platform.python_version(),
                "platform": platform.platform(),
                "processor": platform.processor()
            }
            
        self.save_feedback(feedback_data)
        
        QMessageBox.information(self, "Feedback Sent", "Thank you for your feedback!")
        self.accept()
        
    def save_feedback(self, data):
        """Save feedback to a local file (mocking server send)."""
        try:
            # Save to ~/.renderfox/feedback
            home_dir = os.path.expanduser("~")
            feedback_dir = os.path.join(home_dir, ".renderfox", "feedback")
            os.makedirs(feedback_dir, exist_ok=True)
            
            filename = f"feedback_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            file_path = os.path.join(feedback_dir, filename)
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
                
            print(f"Feedback saved to {file_path}")
            
        except Exception as e:
            print(f"Failed to save feedback: {e}")

if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    dialog = FeedbackDialog()
    dialog.show()
    sys.exit(app.exec())
