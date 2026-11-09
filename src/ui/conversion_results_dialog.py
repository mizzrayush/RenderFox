"""
Conversion Results Dialog - Shows detailed conversion status and results
"""

import os
from typing import Dict, List
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QTextEdit, QGroupBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QTabWidget, QWidget, QProgressBar,
    QMessageBox, QDialogButtonBox, QFrame
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QPixmap, QIcon
from .icon_provider import get_icon

class ConversionResultsDialog(QDialog):
    """Dialog to display detailed conversion results with success/failure information."""
    
    def __init__(self, results: Dict, parent=None):
        super().__init__(parent)
        self.results = results
        self.setWindowTitle("Conversion Results")
        self.setModal(True)
        self.resize(700, 500)
        
        # Apply dark theme styling
        self.setStyleSheet("""
            QDialog {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QLabel {
                color: #ffffff;
                background-color: transparent;
            }
            QGroupBox {
                color: #ffffff;
                font-weight: bold;
                border: 2px solid #555555;
                border-radius: 5px;
                margin-top: 1ex;
                padding-top: 10px;
                background-color: #333333;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: #ffffff;
                background-color: #333333;
            }
            QTextEdit {
                background-color: #1e1e1e;
                color: #ffffff;
                border: 1px solid #555555;
                border-radius: 3px;
                selection-background-color: #0078d4;
            }
            QTableWidget {
                background-color: #1e1e1e;
                color: #ffffff;
                border: 1px solid #555555;
                gridline-color: #555555;
                selection-background-color: #0078d4;
            }
            QTableWidget::item {
                background-color: #1e1e1e;
                color: #ffffff;
                border-bottom: 1px solid #555555;
            }
            QTableWidget::item:selected {
                background-color: #0078d4;
                color: #ffffff;
            }
            QHeaderView::section {
                background-color: #404040;
                color: #ffffff;
                border: 1px solid #555555;
                padding: 4px;
                font-weight: bold;
            }
            QPushButton {
                background-color: #0078d4;
                color: #ffffff;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #106ebe;
            }
            QPushButton:pressed {
                background-color: #005a9e;
            }
            QTabWidget::pane {
                border: 1px solid #555555;
                background-color: #2b2b2b;
            }
            QTabBar::tab {
                background-color: #404040;
                color: #ffffff;
                border: 1px solid #555555;
                padding: 8px 12px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background-color: #0078d4;
                color: #ffffff;
            }
            QTabBar::tab:hover {
                background-color: #555555;
            }
            QFrame {
                background-color: #333333;
                border: 1px solid #555555;
                border-radius: 5px;
            }
        """)
        
        self.init_ui()
        
    def init_ui(self):
        """Initialize the dialog UI."""
        layout = QVBoxLayout(self)
        
        # Header with summary
        self.create_header(layout)
        
        # Main content tabs
        self.create_content_tabs(layout)
        
        # Action buttons
        self.create_action_buttons(layout)
        
    def create_header(self, layout):
        """Create the header section with summary information."""
        header_frame = QFrame()
        header_frame.setFrameStyle(QFrame.Shape.StyledPanel)
        header_layout = QVBoxLayout(header_frame)
        
        # Title
        title_label = QLabel("Conversion Results")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title_label.setFont(title_font)
        header_layout.addWidget(title_label)
        
        # Summary statistics
        total_files = self.results.get('total_files', 0)
        successful = len(self.results.get('successful', []))
        failed = len(self.results.get('failed', []))
        
        # Success rate calculation
        success_rate = (successful / total_files * 100) if total_files > 0 else 0
        
        # Summary text with status colors
        if failed == 0:
            status_text = "All conversions completed successfully!"
            status_color = "#2ed573"
        elif successful == 0:
            status_text = "All conversions failed!"
            status_color = "#ff4757"
        else:
            status_text = "Some conversions failed!"
            status_color = "#ffa502"
        
        summary_label = QLabel(f"""
        <span style="font-size: 14px; color: {status_color}; font-weight: bold;">
            {status_text}
        </span><br>
        <span style="font-size: 12px; color: #ced6e0;">
            <b>Summary:</b> {successful}/{total_files} successful ({success_rate:.1f}% success rate)<br>
            <b>Successful:</b> {successful} files<br>
            <b>Failed:</b> {failed} files
        </span>
        """)
        summary_label.setWordWrap(True)
        header_layout.addWidget(summary_label)
        
        layout.addWidget(header_frame)
        
    def create_content_tabs(self, layout):
        """Create the main content tabs."""
        tab_widget = QTabWidget()
        
        # Overview tab
        tab_widget.addTab(self.create_overview_tab(), "Overview")
        
        # Successful conversions tab
        if self.results.get('successful'):
            tab_widget.addTab(self.create_successful_tab(), f"Successful ({len(self.results['successful'])})")
        
        # Failed conversions tab
        if self.results.get('failed'):
            tab_widget.addTab(self.create_failed_tab(), f"Failed ({len(self.results['failed'])})")
        
        # Errors/Details tab
        if self.results.get('errors'):
            tab_widget.addTab(self.create_errors_tab(), f"Error Details ({len(self.results['errors'])})")
        
        layout.addWidget(tab_widget)
        
    def create_overview_tab(self):
        """Create the overview tab with general information."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Conversion summary
        summary_group = QGroupBox("Conversion Summary")
        summary_layout = QVBoxLayout(summary_group)
        
        # Statistics
        total_files = self.results.get('total_files', 0)
        successful = len(self.results.get('successful', []))
        failed = len(self.results.get('failed', []))
        
        stats_text = QTextEdit()
        stats_text.setMaximumHeight(150)
        stats_text.setReadOnly(True)
        
        # Format statistics nicely with dark theme colors
        stats_content = f"""
<div style="color: #ffffff; background-color: #1e1e1e;">
<h3 style="color: #ffffff;">Conversion Statistics</h3>
<table style="width: 100%; border-collapse: collapse; color: #ffffff;">
<tr><td style="padding: 5px; border: 1px solid #555555;"><b>Total Files:</b></td><td style="padding: 5px; border: 1px solid #555555;">{total_files}</td></tr>
<tr style="background-color: #1e3a1e;"><td style="padding: 5px; border: 1px solid #555555;"><b>Successful:</b></td><td style="padding: 5px; border: 1px solid #555555;">{successful}</td></tr>
<tr style="background-color: #3a1e1e;"><td style="padding: 5px; border: 1px solid #555555;"><b>Failed:</b></td><td style="padding: 5px; border: 1px solid #555555;">{failed}</td></tr>
<tr><td style="padding: 5px; border: 1px solid #555555;"><b>Success Rate:</b></td><td style="padding: 5px; border: 1px solid #555555;">{(successful/total_files*100) if total_files > 0 else 0:.1f}%</td></tr>
</table>
</div>
        """
        
        # Add library information if available
        if 'library_used' in self.results:
            stats_content += f"""
<div style="color: #ffffff;">
<h3 style="color: #ffffff;">Conversion Method</h3>
<p style="color: #ffffff;"><b>Primary Library Used:</b> {self.results['library_used']}</p>
</div>
            """
        
        # Add timing information if available
        if 'processing_time' in self.results:
            stats_content += f"""
<div style="color: #ffffff;">
<h3 style="color: #ffffff;">Performance</h3>
<p style="color: #ffffff;"><b>Total Processing Time:</b> {self.results['processing_time']:.2f} seconds</p>
<p style="color: #ffffff;"><b>Average Time per File:</b> {(self.results['processing_time']/total_files) if total_files > 0 else 0:.2f} seconds</p>
</div>
            """
        
        stats_text.setHtml(stats_content)
        summary_layout.addWidget(stats_text)
        layout.addWidget(summary_group)
        
        return widget
        
    def create_successful_tab(self):
        """Create the successful conversions tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Successful files table
        success_group = QGroupBox(f"Successfully Converted Files ({len(self.results['successful'])})")
        success_layout = QVBoxLayout(success_group)
        
        success_table = QTableWidget()
        success_table.setColumnCount(4)
        success_table.setHorizontalHeaderLabels(["Input File", "Output File", "Method", "Coverage Read Back"])
        
        # Populate successful files
        successful_files = self.results.get('successful', [])
        success_table.setRowCount(len(successful_files))
        
        for row, item in enumerate(successful_files):
            # Input file
            input_file = item.get('input', 'Unknown')
            input_item = QTableWidgetItem(os.path.basename(input_file))
            input_item.setToolTip(input_file)
            success_table.setItem(row, 0, input_item)
            
            # Output file
            output_file = item.get('output', 'Unknown')
            output_item = QTableWidgetItem(os.path.basename(output_file))
            output_item.setToolTip(output_file)
            success_table.setItem(row, 1, output_item)
            
            # Method used
            method = item.get('method', 'Unknown')
            method_item = QTableWidgetItem(method)
            success_table.setItem(row, 2, method_item)

            coverage = item.get('coverage')
            if coverage is None:
                text = "No container coverage available"
            else:
                retained = ', '.join(coverage.get('retained') or []) or 'no source fields retained'
                missing = ', '.join(coverage.get('not_retained') or [])
                text = f"Retained: {retained}" + (f"; not retained: {missing}" if missing else '')
            coverage_item = QTableWidgetItem(text)
            coverage_item.setToolTip(text)
            success_table.setItem(row, 3, coverage_item)
        
        # Auto-resize columns
        header = success_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        
        success_layout.addWidget(success_table)
        layout.addWidget(success_group)
        
        return widget
        
    def create_failed_tab(self):
        """Create the failed conversions tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Failed files table
        failed_group = QGroupBox(f"Failed Conversions ({len(self.results['failed'])})")
        failed_layout = QVBoxLayout(failed_group)
        
        failed_table = QTableWidget()
        failed_table.setColumnCount(3)
        failed_table.setHorizontalHeaderLabels(["Input File", "Output File", "Error"])
        
        # Populate failed files
        failed_files = self.results.get('failed', [])
        failed_table.setRowCount(len(failed_files))
        
        for row, item in enumerate(failed_files):
            # Input file
            input_file = item.get('input', 'Unknown')
            input_item = QTableWidgetItem(os.path.basename(input_file))
            input_item.setToolTip(input_file)
            failed_table.setItem(row, 0, input_item)
            
            # Output file (attempted)
            output_file = item.get('output', 'N/A')
            if output_file and output_file != 'N/A':
                output_item = QTableWidgetItem(os.path.basename(output_file))
                output_item.setToolTip(output_file)
            else:
                output_item = QTableWidgetItem("N/A")
            failed_table.setItem(row, 1, output_item)
            
            # Error message
            error = item.get('error', 'Unknown error')
            error_item = QTableWidgetItem(error)
            error_item.setToolTip(error)
            failed_table.setItem(row, 2, error_item)
        
        # Auto-resize columns
        header = failed_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        
        failed_layout.addWidget(failed_table)
        layout.addWidget(failed_group)
        
        return widget
        
    def create_errors_tab(self):
        """Create the detailed errors tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Error details
        errors_group = QGroupBox("Detailed Error Information")
        errors_layout = QVBoxLayout(errors_group)
        
        error_text = QTextEdit()
        error_text.setReadOnly(True)
        error_text.setFont(QFont("Consolas", 9))  # Monospace font for better readability
        
        # Format error messages with dark theme colors
        errors = self.results.get('errors', [])
        if errors:
            error_content = '<div style="color: #ffffff; background-color: #1e1e1e;"><h3 style="color: #ff6b6b;">Error Details:</h3>\n'
            for i, error in enumerate(errors, 1):
                error_content += f'<p style="color: #ffffff;"><b style="color: #ffa500;">{i}.</b> <span style="color: #ff6b6b;">{error}</span></p>\n'
            error_content += '</div>'
        else:
            error_content = '<div style="color: #ffffff; background-color: #1e1e1e;"><p style="color: #aaaaaa;">No detailed error information available.</p></div>'
        
        error_text.setHtml(error_content)
        errors_layout.addWidget(error_text)
        layout.addWidget(errors_group)
        
        return widget
        
    def create_action_buttons(self, layout):
        """Create action buttons at the bottom."""
        button_layout = QHBoxLayout()
        
        # Open output folder button (if successful conversions exist)
        if self.results.get('successful'):
            open_folder_btn = QPushButton("Open Output Folder")
            open_folder_btn.setIcon(get_icon("folder"))
            open_folder_btn.clicked.connect(self.open_output_folder)
            button_layout.addWidget(open_folder_btn)
        
        # Retry failed conversions button (if failed conversions exist)
        if self.results.get('failed'):
            retry_btn = QPushButton("Retry Failed")
            retry_btn.setIcon(get_icon("refresh"))
            retry_btn.clicked.connect(self.retry_failed_conversions)
            button_layout.addWidget(retry_btn)
        
        # Export results button
        export_btn = QPushButton("Export Report")
        export_btn.setIcon(get_icon("export"))
        export_btn.clicked.connect(self.export_results)
        button_layout.addWidget(export_btn)
        
        button_layout.addStretch()
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.setProperty("primary", "true")
        close_btn.clicked.connect(self.accept)
        close_btn.setDefault(True)
        button_layout.addWidget(close_btn)
        
        layout.addLayout(button_layout)
        
    def open_output_folder(self):
        """Open the output folder containing converted files."""
        successful_files = self.results.get('successful', [])
        if successful_files:
            # Get the directory of the first successful conversion
            first_output = successful_files[0].get('output', '')
            if first_output and os.path.exists(first_output):
                output_dir = os.path.dirname(first_output)
                try:
                    import subprocess
                    import sys
                    if sys.platform == "win32":
                        subprocess.run(["explorer", output_dir])
                    elif sys.platform == "darwin":
                        subprocess.run(["open", output_dir])
                    else:
                        subprocess.run(["xdg-open", output_dir])
                except Exception as e:
                    QMessageBox.warning(self, "Error", f"Could not open folder: {str(e)}")
            else:
                QMessageBox.warning(self, "Error", "Output folder not found.")
        
    def retry_failed_conversions(self):
        """Signal to retry failed conversions."""
        failed_files = self.results.get('failed', [])
        if failed_files:
            reply = QMessageBox.question(
                self, 
                "Retry Failed Conversions",
                f"Do you want to retry the {len(failed_files)} failed conversions?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                # This could emit a signal or call a callback
                QMessageBox.information(self, "Retry", "Retry functionality would be implemented here.")
        
    def export_results(self):
        """Export conversion results to a file."""
        from PyQt6.QtWidgets import QFileDialog
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, 
            "Export Conversion Report",
            f"conversion_report_{len(self.results.get('successful', []))}_successful_{len(self.results.get('failed', []))}_failed.txt",
            "Text Files (*.txt);;All Files (*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write("RENDERFOX CONVERSION REPORT\n")
                    f.write("=" * 50 + "\n\n")
                    
                    # Summary
                    total_files = self.results.get('total_files', 0)
                    successful = len(self.results.get('successful', []))
                    failed = len(self.results.get('failed', []))
                    
                    f.write(f"Total Files: {total_files}\n")
                    f.write(f"Successful: {successful}\n")
                    f.write(f"Failed: {failed}\n")
                    f.write(f"Success Rate: {(successful/total_files*100) if total_files > 0 else 0:.1f}%\n\n")
                    
                    # Successful conversions
                    if self.results.get('successful'):
                        f.write("SUCCESSFUL CONVERSIONS:\n")
                        f.write("-" * 30 + "\n")
                        for item in self.results['successful']:
                            f.write(f"[OK] {item.get('input', 'Unknown')} -> {item.get('output', 'Unknown')} (Method: {item.get('method', 'Unknown')})\n")
                        f.write("\n")
                    
                    # Failed conversions
                    if self.results.get('failed'):
                        f.write("FAILED CONVERSIONS:\n")
                        f.write("-" * 30 + "\n")
                        for item in self.results['failed']:
                            f.write(f"[Error] {item.get('input', 'Unknown')} - Error: {item.get('error', 'Unknown error')}\n")
                        f.write("\n")
                    
                    # Detailed errors
                    if self.results.get('errors'):
                        f.write("DETAILED ERRORS:\n")
                        f.write("-" * 30 + "\n")
                        for i, error in enumerate(self.results['errors'], 1):
                            f.write(f"{i}. {error}\n")
                
                QMessageBox.information(self, "Export Complete", f"Report exported to:\n{file_path}")
                
            except Exception as e:
                QMessageBox.critical(self, "Export Error", f"Failed to export report:\n{str(e)}")

def show_conversion_results(results: Dict, parent=None) -> ConversionResultsDialog:
    """
    Convenience function to show conversion results dialog.
    
    Args:
        results: Dictionary containing conversion results with structure:
                {
                    'total_files': int,
                    'successful': [{'input': str, 'output': str, 'method': str}, ...],
                    'failed': [{'input': str, 'output': str, 'error': str}, ...],
                    'errors': [str, ...],
                    'processing_time': float (optional),
                    'library_used': str (optional)
                }
        parent: Parent widget
    
    Returns:
        ConversionResultsDialog instance
    """
    dialog = ConversionResultsDialog(results, parent)
    dialog.show()
    return dialog
