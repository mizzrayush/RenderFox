"""
Model Downloader for RenderFox
Handles downloading of AI models (Stable Diffusion, CLIP) for offline use.
"""

import os
import sys
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QProgressBar, QPushButton, QMessageBox, QCheckBox, QHBoxLayout
)
from PyQt6.QtCore import QThread, pyqtSignal, Qt

class ModelDownloaderThread(QThread):
    progress_update = pyqtSignal(int, str)
    finished = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def __init__(self, download_sd=True, download_clip=True):
        super().__init__()
        self.download_sd = download_sd
        self.download_clip = download_clip

    def run(self):
        try:
            from huggingface_hub import hf_hub_download, snapshot_download
            
            total_steps = 0
            if self.download_sd: total_steps += 1
            if self.download_clip: total_steps += 1
            
            if total_steps == 0:
                self.finished.emit()
                return
            
            if getattr(sys, 'frozen', False):
                base_dir = os.path.dirname(os.path.abspath(sys.executable))
            else:
                base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            
            current_step = 0
            
            # 1. Download Stable Diffusion 1.5 (Single File)
            if self.download_sd:
                self.progress_update.emit(int((current_step / total_steps) * 100), "Downloading Stable Diffusion 1.5...")
                
                sd_dir = os.path.join(base_dir, "ai_models", "sd-v1-5")
                os.makedirs(sd_dir, exist_ok=True)
                
                # Check if already exists
                sd_file = os.path.join(sd_dir, "v1-5-pruned-emaonly.safetensors")
                if not os.path.exists(sd_file):
                    hf_hub_download(
                        repo_id="runwayml/stable-diffusion-v1-5",
                        filename="v1-5-pruned-emaonly.safetensors",
                        local_dir=sd_dir,
                        local_dir_use_symlinks=False
                    )
                else:
                    self.progress_update.emit(int((current_step / total_steps) * 100), "Stable Diffusion already exists. Skipping.")
                
                current_step += 1

            # 2. Download OpenAI CLIP (Repo Snapshot)
            if self.download_clip:
                self.progress_update.emit(int((current_step / total_steps) * 100), "Downloading OpenAI CLIP Model...")
                
                clip_dir = os.path.join(base_dir, "OPENai Clip")
                os.makedirs(clip_dir, exist_ok=True)
                
                allow_patterns = [
                    "config.json",
                    "pytorch_model.bin",
                    "tokenizer.json",
                    "vocab.json",
                    "merges.txt",
                    "preprocessor_config.json",
                    "special_tokens_map.json",
                    "tokenizer_config.json"
                ]
                
                snapshot_download(
                    repo_id="openai/clip-vit-base-patch32",
                    local_dir=clip_dir,
                    local_dir_use_symlinks=False,
                    allow_patterns=allow_patterns
                )
                current_step += 1
            
            self.progress_update.emit(100, "All downloads complete!")
            self.finished.emit()
            
        except Exception as e:
            self.error_occurred.emit(str(e))

class ModelDownloaderDialog(QDialog):
    def __init__(self, auto_start=True):
        super().__init__()
        self.setWindowTitle("AI Model Manager")
        self.setFixedSize(400, 250)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.CustomizeWindowHint | Qt.WindowType.WindowTitleHint | Qt.WindowType.WindowCloseButtonHint)
        
        layout = QVBoxLayout(self)
        
        # Instructions
        layout.addWidget(QLabel("Select models to download for offline use:"))
        
        # Checkboxes
        self.chk_sd = QCheckBox("Stable Diffusion 1.5 (~4GB)")
        self.chk_sd.setChecked(True)
        self.chk_sd.setToolTip("Required for offline texture generation")
        layout.addWidget(self.chk_sd)
        
        self.chk_clip = QCheckBox("OpenAI CLIP (~500MB)")
        self.chk_clip.setChecked(True)
        self.chk_clip.setToolTip("Required for AI Asset Tagging")
        layout.addWidget(self.chk_clip)
        
        # Progress
        self.status_label = QLabel("Ready to download.")
        layout.addWidget(self.status_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        layout.addWidget(self.progress_bar)
        
        # Buttons
        btn_layout = QHBoxLayout()
        self.download_btn = QPushButton("Download Selected")
        self.download_btn.clicked.connect(self.start_download)
        btn_layout.addWidget(self.download_btn)
        
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.close_btn)
        
        layout.addLayout(btn_layout)
        
        self.auto_start = auto_start
        if self.auto_start:
            self.chk_sd.setEnabled(False)
            self.chk_clip.setEnabled(False)
            self.download_btn.setEnabled(False)
            self.close_btn.setEnabled(False)
            self.start_download()
            
    def start_download(self):
        self.download_btn.setEnabled(False)
        self.chk_sd.setEnabled(False)
        self.chk_clip.setEnabled(False)
        self.close_btn.setEnabled(False)
        
        self.thread = ModelDownloaderThread(
            download_sd=self.chk_sd.isChecked(),
            download_clip=self.chk_clip.isChecked()
        )
        self.thread.progress_update.connect(self.update_progress)
        self.thread.finished.connect(self.on_finished)
        self.thread.error_occurred.connect(self.on_error)
        self.thread.start()
        
    def update_progress(self, value, message):
        self.progress_bar.setValue(value)
        self.status_label.setText(message)
        
    def on_finished(self):
        self.status_label.setText("Download Complete!")
        self.progress_bar.setValue(100)
        self.close_btn.setEnabled(True)
        self.download_btn.setText("Redownload")
        self.download_btn.setEnabled(True)
        self.chk_sd.setEnabled(True)
        self.chk_clip.setEnabled(True)
        
        if self.auto_start:
            self.accept()
        else:
            QMessageBox.information(self, "Success", "Selected models have been downloaded.")

    def on_error(self, message):
        QMessageBox.critical(self, "Download Failed", f"Error downloading models:\n{message}")
        self.close_btn.setEnabled(True)
        self.download_btn.setEnabled(True)
        self.chk_sd.setEnabled(True)
        self.chk_clip.setEnabled(True)
        if self.auto_start:
            self.reject()
