"""
Texture Generation Engine
Handles the loading of AI models and generation of textures using Stable Diffusion.
"""

import os
import logging
import torch
from PyQt6.QtCore import QThread, pyqtSignal, QObject

from src.utils.app_paths import data_dir, output_dir

# Configure logging
logger = logging.getLogger(__name__)

class TextureGenerationThread(QThread):
    """
    Background thread for generating textures to keep UI responsive.
    """
    progress_update = pyqtSignal(int, str)  # value, status message
    generation_finished = pyqtSignal(str)   # output_path
    error_occurred = pyqtSignal(str)        # error message
    
    def __init__(self, prompt, width=512, height=512, steps=20, seed=-1, device_id="auto", model_path=None, mode="offline", api_key=None):
        super().__init__()
        self.prompt = prompt
        self.width = width
        self.height = height
        self.steps = steps
        self.seed = seed
        self.device_id = device_id
        self.model_path = model_path
        self.mode = mode.lower()
        self.api_key = api_key
        self._is_cancelled = False
        
    def run(self):
        if self.mode == "online":
            self.generate_online()
        else:
            self.generate_offline()

    def generate_online(self):
        """Generate texture using Stability AI API."""
        try:
            import requests
            import base64
            from PIL import Image
            import io
            
            if not self.api_key:
                self.error_occurred.emit("API Key is missing for online generation.")
                return

            self.progress_update.emit(10, "Connecting to Stability AI API...")
            
            url = "https://api.stability.ai/v1/generation/stable-diffusion-xl-1024-v1-0/text-to-image"
            
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            }
            
            body = {
                "steps": self.steps,
                "width": self.width,
                "height": self.height,
                "seed": self.seed if self.seed != -1 else 0,
                "cfg_scale": 7,
                "samples": 1,
                "text_prompts": [
                    {"text": self.prompt, "weight": 1}
                ],
            }
            
            self.progress_update.emit(30, "Sending request...")
            response = requests.post(url, headers=headers, json=body)
            
            if response.status_code != 200:
                try:
                    error_json = response.json()
                    message = error_json.get("message", str(response.text))
                except:
                    message = str(response.text)
                raise Exception(f"API Error ({response.status_code}): {message}")
            
            self.progress_update.emit(80, "Processing response...")
            data = response.json()
            
            # Decode image
            for i, image_data in enumerate(data["artifacts"]):
                if image_data["finishReason"] == "CONTENT_FILTERED":
                    raise Exception("Generation failed: Content filtered by safety system.")
                    
                base64_image = image_data["base64"]
                image_bytes = base64.b64decode(base64_image)
                image = Image.open(io.BytesIO(image_bytes))
                
                # Save Output
                self.progress_update.emit(90, "Saving Image...")
                out_dir = os.path.join(output_dir(), "generated_textures")
                os.makedirs(out_dir, exist_ok=True)
                
                import uuid
                filename = f"tex_online_{uuid.uuid4().hex[:8]}.png"
                filepath = os.path.join(out_dir, filename)
                
                image.save(filepath)
                
                self.progress_update.emit(100, "Done!")
                self.generation_finished.emit(filepath)
                break # Only handle first image for now

        except Exception as e:
            logger.exception("Online generation failed")
            self.error_occurred.emit(f"Online Generation Failed: {str(e)}")

    def generate_offline(self):
        """Generate texture using local Stable Diffusion."""
        try:
            self.progress_update.emit(5, "Initializing AI Engine...")
            
            # 1. Check Imports
            try:
                from diffusers import StableDiffusionPipeline, EulerAncestralDiscreteScheduler
            except ImportError:
                self.error_occurred.emit("Missing dependencies. Please install: pip install diffusers transformers accelerate safetensors")
                return

            # 2. Determine Device
            device = "cpu"
            if torch.cuda.is_available():
                device = "cuda"
                self.progress_update.emit(10, f"Using GPU: {torch.cuda.get_device_name(0)}")
            else:
                self.progress_update.emit(10, "Using CPU (Slow mode)")
                
            # 3. Load Model
            self.progress_update.emit(20, f"Loading Model (this may take time)...")
            
            try:
                if self.model_path and os.path.exists(self.model_path):
                    # Custom Model Path
                    self.progress_update.emit(25, f"Loading custom model: {os.path.basename(self.model_path)}")
                    
                    if self.model_path.endswith(".safetensors") or self.model_path.endswith(".ckpt"):
                        # Load from single file (safetensors/ckpt)
                        pipe = StableDiffusionPipeline.from_single_file(
                            self.model_path,
                            torch_dtype=torch.float16 if device == "cuda" else torch.float32,
                            load_safety_checker=False
                        )
                    else:
                        # Load from directory
                        pipe = StableDiffusionPipeline.from_pretrained(
                            self.model_path,
                            torch_dtype=torch.float16 if device == "cuda" else torch.float32
                        )
                else:
                    # Default Download
                    model_id = "runwayml/stable-diffusion-v1-5"
                    cache_dir = os.path.join(data_dir(), "ai_models", "sd-v1-5")
                    os.makedirs(cache_dir, exist_ok=True)
                    
                    # Check for pre-downloaded safetensors file (from installer)
                    default_safetensors = os.path.join(cache_dir, "v1-5-pruned-emaonly.safetensors")
                    
                    if os.path.exists(default_safetensors):
                        self.progress_update.emit(25, "Loading default model (safetensors)...")
                        pipe = StableDiffusionPipeline.from_single_file(
                            default_safetensors,
                            torch_dtype=torch.float16 if device == "cuda" else torch.float32,
                            load_safety_checker=False
                        )
                    else:
                        # Fallback to standard repo download
                        self.progress_update.emit(25, "Downloading default model (repo)...")
                        pipe = StableDiffusionPipeline.from_pretrained(
                            model_id,
                            cache_dir=cache_dir,
                            torch_dtype=torch.float16 if device == "cuda" else torch.float32
                        )
            except Exception as e:
                # Fallback for offline or download error
                self.error_occurred.emit(f"Failed to load model: {str(e)}\nCheck internet connection or file path.")
                return

            if self._is_cancelled: return

            # Optimizations
            pipe.scheduler = EulerAncestralDiscreteScheduler.from_config(pipe.scheduler.config)
            pipe.to(device)
            
            # Enable attention slicing for low memory (crucial for 4GB cards or CPU)
            pipe.enable_attention_slicing()
            
            # 4. Generate
            self.progress_update.emit(50, "Generating Texture...")
            
            generator = None
            if self.seed != -1:
                generator = torch.Generator(device).manual_seed(self.seed)
            
            # Callback to update progress bar during generation steps
            def callback(step, timestep, latents):
                # Calculate progress: 50% to 90%
                progress = 50 + int((step / self.steps) * 40)
                self.progress_update.emit(progress, f"Denoising step {step}/{self.steps}...")
                
            # Run inference
            # Note: callback_steps=1 ensures we get updates every step
            image = pipe(
                self.prompt,
                width=self.width,
                height=self.height,
                num_inference_steps=self.steps,
                generator=generator,
                callback=callback,
                callback_steps=1
            ).images[0]
            
            if self._is_cancelled: return
            
            # 5. Save Output
            self.progress_update.emit(95, "Saving Image...")
            
            out_dir = os.path.join(output_dir(), "generated_textures")
            os.makedirs(out_dir, exist_ok=True)
            
            import uuid
            filename = f"tex_{uuid.uuid4().hex[:8]}.png"
            filepath = os.path.join(out_dir, filename)
            
            image.save(filepath)
            
            self.progress_update.emit(100, "Done!")
            self.generation_finished.emit(filepath)
            
        except Exception as e:
            logger.exception("Texture generation failed")
            self.error_occurred.emit(str(e))
            
    def cancel(self):
        self._is_cancelled = True
