"""
Post-processing module for rendered images including denoising, watermarking, and file organization.
"""

import os
import shutil
import json
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Callable
from dataclasses import dataclass
from pathlib import Path
import threading
import time
import logging

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import trimesh

from ..core.models import PostProcessingSettings, RenderJob
from .render_engines import frame_stem, output_spec

logger = logging.getLogger(__name__)

# How old a `renderfox_*` entry in the system temp folder has to be before a
# cleanup sweep may delete it. Every RenderFox window shares one temp folder, and
# a sweep without this age deletes the scratch directory of a render running now.
STALE_TEMP_SECONDS = 24 * 3600


@dataclass
class PostProcessingResult:
    """Result of post-processing operations."""
    success: bool
    processed_files: List[str]
    errors: List[str]
    processing_time: float
    file_size_before: int
    file_size_after: int


class ImageDenoiser:
    """Handles image denoising using various algorithms."""
    
    def __init__(self):
        self.methods = {
            "OpenCV Non-Local Means": self._opencv_nlm_denoise,
            "OpenCV Gaussian": self._opencv_gaussian_denoise,
            "Bilateral Filter": self._bilateral_filter_denoise,
            "OpenImageDenoise (OIDN)": self._oidn_denoise
        }
    
    def denoise_image(self, image_path: str, output_path: str, 
                     method: str = "OpenCV Non-Local Means", 
                     strength: float = 0.5) -> bool:
        """Denoise an image using the specified method."""
        try:
            if method not in self.methods:
                logger.warning(f"Unknown denoising method: {method}")
                return False
            
            return self.methods[method](image_path, output_path, strength)
            
        except Exception as e:
            logger.error(f"Denoising failed: {str(e)}")
            return False
    
    def _opencv_nlm_denoise(self, image_path: str, output_path: str, strength: float) -> bool:
        """Denoise using OpenCV's Non-Local Means algorithm."""
        img = cv2.imread(image_path)
        if img is None:
            return False
        
        # Convert strength (0-1) to OpenCV parameters
        h = int(strength * 20 + 3)  # 3-23 range
        template_window_size = 7
        search_window_size = 21
        
        if len(img.shape) == 3:
            # Color image
            denoised = cv2.fastNlMeansDenoisingColored(
                img, None, h, h, template_window_size, search_window_size
            )
        else:
            # Grayscale image
            denoised = cv2.fastNlMeansDenoising(
                img, None, h, template_window_size, search_window_size
            )
        
        return cv2.imwrite(output_path, denoised)
    
    def _opencv_gaussian_denoise(self, image_path: str, output_path: str, strength: float) -> bool:
        """Denoise using Gaussian blur."""
        img = cv2.imread(image_path)
        if img is None:
            return False
        
        # Convert strength to kernel size
        kernel_size = int(strength * 10 + 1)
        if kernel_size % 2 == 0:
            kernel_size += 1
        
        denoised = cv2.GaussianBlur(img, (kernel_size, kernel_size), 0)
        return cv2.imwrite(output_path, denoised)
    
    def _bilateral_filter_denoise(self, image_path: str, output_path: str, strength: float) -> bool:
        """Denoise using bilateral filter."""
        img = cv2.imread(image_path)
        if img is None:
            return False
        
        # Convert strength to filter parameters
        d = int(strength * 15 + 5)  # 5-20 range
        sigma_color = strength * 150 + 50  # 50-200 range
        sigma_space = strength * 150 + 50
        
        denoised = cv2.bilateralFilter(img, d, sigma_color, sigma_space)
        return cv2.imwrite(output_path, denoised)
    
    def _oidn_denoise(self, image_path: str, output_path: str, strength: float) -> bool:
        """Denoise using Intel Open Image Denoise (if available)."""
        try:
            # Try to import and use OIDN
            import oidn
            
            # Load image
            img = cv2.imread(image_path, cv2.IMREAD_COLOR)
            if img is None:
                return False
            
            # Convert BGR to RGB and normalize
            img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            img_float = img_rgb.astype(np.float32) / 255.0
            
            # Create OIDN device and filter
            device = oidn.Device()
            filter = device.newFilter("RT")  # Raytracing filter
            
            # Set input and output
            filter.setImage("color", img_float)
            filter.setImage("output", img_float.copy())
            
            # Set parameters based on strength
            filter.set("hdr", False)
            filter.set("cleanAux", True)
            
            # Execute denoising
            filter.commit()
            filter.execute()
            
            # Get result and convert back
            result = filter.getImage("output")
            result_uint8 = (result * 255).astype(np.uint8)
            result_bgr = cv2.cvtColor(result_uint8, cv2.COLOR_RGB2BGR)
            
            return cv2.imwrite(output_path, result_bgr)
            
        except ImportError:
            logger.warning("Intel Open Image Denoise not available, falling back to OpenCV")
            return self._opencv_nlm_denoise(image_path, output_path, strength)
        except Exception as e:
            logger.error(f"OIDN denoising failed: {str(e)}")
            return False


class ImageWatermarker:
    """Handles adding watermarks to rendered images."""
    
    def __init__(self):
        self.positions = {
            "top-left": (0.05, 0.05),
            "top-right": (0.95, 0.05),
            "bottom-left": (0.05, 0.95),
            "bottom-right": (0.95, 0.95),
            "center": (0.5, 0.5)
        }
    
    def add_watermark(self, image_path: str, output_path: str,
                     text: str = "", logo_path: str = "",
                     position: str = "bottom-right",
                     opacity: float = 0.7,
                     font_size: int = 12,
                     color: str = "#FFFFFF",
                     padding: int = 10) -> bool:
        """Add text or logo watermark to an image."""
        try:
            # Open image
            with Image.open(image_path) as img:
                # Convert to RGBA for transparency support
                if img.mode != 'RGBA':
                    img = img.convert('RGBA')
                
                # Create transparent overlay
                overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
                draw = ImageDraw.Draw(overlay)
                
                if logo_path and os.path.exists(logo_path):
                    # Add logo watermark
                    success = self._add_logo_watermark(
                        overlay, logo_path, position, opacity, padding
                    )
                elif text:
                    # Add text watermark
                    success = self._add_text_watermark(
                        draw, img.size, text, position, opacity, 
                        font_size, color, padding
                    )
                else:
                    return False
                
                if not success:
                    return False
                
                # Composite the watermark onto the image
                watermarked = Image.alpha_composite(img, overlay)
                
                # Convert back to original mode if needed
                if image_path.lower().endswith(('.jpg', '.jpeg')):
                    watermarked = watermarked.convert('RGB')
                
                # Save the result
                watermarked.save(output_path)
                return True
                
        except Exception as e:
            logger.error(f"Watermarking failed: {str(e)}")
            return False
    
    def _add_text_watermark(self, draw: ImageDraw.Draw, image_size: Tuple[int, int],
                          text: str, position: str, opacity: float,
                          font_size: int, color: str, padding: int) -> bool:
        """Add text watermark to the image."""
        try:
            # Load font
            try:
                font = ImageFont.truetype("arial.ttf", font_size)
            except (OSError, IOError):
                font = ImageFont.load_default()
            
            # Get text size
            bbox = draw.textbbox((0, 0), text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            
            # Calculate position
            pos_x, pos_y = self.positions.get(position, (0.95, 0.95))
            
            if pos_x > 0.5:  # Right side
                x = image_size[0] - text_width - padding
            else:  # Left side
                x = padding
            
            if pos_y > 0.5:  # Bottom
                y = image_size[1] - text_height - padding
            else:  # Top
                y = padding
            
            if position == "center":
                x = (image_size[0] - text_width) // 2
                y = (image_size[1] - text_height) // 2
            
            # Convert color and apply opacity
            if color.startswith('#'):
                color = color[1:]
            
            r = int(color[:2], 16)
            g = int(color[2:4], 16)
            b = int(color[4:6], 16)
            a = int(opacity * 255)
            
            # Draw text
            draw.text((x, y), text, font=font, fill=(r, g, b, a))
            return True
            
        except Exception as e:
            logger.error(f"Text watermark failed: {str(e)}")
            return False
    
    def _add_logo_watermark(self, overlay: Image.Image, logo_path: str,
                          position: str, opacity: float, padding: int) -> bool:
        """Add logo watermark to the image."""
        try:
            with Image.open(logo_path) as logo:
                # Convert logo to RGBA
                if logo.mode != 'RGBA':
                    logo = logo.convert('RGBA')
                
                # Apply opacity efficiently
                alpha = logo.split()[-1]
                alpha = alpha.point(lambda p: int(p * opacity))
                logo.putalpha(alpha)
                
                # Calculate position
                pos_x, pos_y = self.positions.get(position, (0.95, 0.95))
                
                if pos_x > 0.5:  # Right side
                    x = overlay.width - logo.width - padding
                else:  # Left side
                    x = padding
                
                if pos_y > 0.5:  # Bottom
                    y = overlay.height - logo.height - padding
                else:  # Top
                    y = padding
                
                if position == "center":
                    x = (overlay.width - logo.width) // 2
                    y = (overlay.height - logo.height) // 2
                
                # Paste logo onto overlay
                overlay.paste(logo, (x, y), logo)
                return True
                
        except Exception as e:
            logger.error(f"Logo watermark failed: {str(e)}")
            return False


class FileOrganizer:
    """Handles organization and archiving of rendered files."""
    
    def __init__(self):
        self.organization_patterns = {
            "by_date": "{year}/{month:02d}/{day:02d}",
            "by_project": "{project_name}",
            "by_format": "{format}",
            "by_resolution": "{width}x{height}",
            "custom": "{custom_pattern}"
        }
    
    def organize_files(self, files: List[str], base_output_dir: str,
                      job: RenderJob, settings: PostProcessingSettings) -> List[str]:
        """Organize files according to specified pattern.
        If preserve_details is True, files are copied; otherwise they are moved.
        """
        organized_files = []
        
        try:
            for file_path in files:
                if not os.path.exists(file_path):
                    continue
                
                # Generate target directory
                target_dir = self._generate_target_directory(
                    base_output_dir, job, settings, file_path
                )
                
                # Create directory if it doesn't exist
                os.makedirs(target_dir, exist_ok=True)
                
                # Generate target filename
                filename = self._generate_filename(file_path, job, settings)
                target_path = os.path.join(target_dir, filename)
                
                # Handle duplicate filenames
                target_path = self._handle_duplicate_filename(target_path)
                
                # Move or copy file based on non-destructive preference
                if settings.preserve_details:
                    shutil.copy2(file_path, target_path)
                else:
                    shutil.move(file_path, target_path)
                
                organized_files.append(target_path)
                
        except Exception as e:
            logger.error(f"File organization failed: {str(e)}")
        
        return organized_files
    
    def _generate_target_directory(self, base_dir: str, job: RenderJob,
                                 settings: PostProcessingSettings, file_path: str) -> str:
        """Generate target directory path based on organization settings."""
        parts = [base_dir] if base_dir else [os.path.dirname(file_path)]
        
        now = datetime.now()
        
        if settings.organize_by_date:
            date_part = f"{now.year}/{now.month:02d}/{now.day:02d}"
            parts.append(date_part)
        
        if settings.create_subfolders:
            parts.append(frame_stem(job.name))
        
        if settings.organize_by_format:
            file_ext = os.path.splitext(file_path)[1][1:].lower()
            parts.append(file_ext)
        
        return os.path.join(*parts)
    
    def _generate_filename(self, file_path: str, job: RenderJob,
                         settings: PostProcessingSettings) -> str:
        """Generate filename based on organization pattern."""
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        extension = os.path.splitext(file_path)[1]
        
        # Parse organization pattern
        pattern = settings.organization_pattern or "{job_name}_{timestamp}_{frame:04d}"
        
        # Create format variables
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Extract frame number if present
        frame_num = 1
        if job.frame_range and '_' in base_name:
            try:
                frame_num = int(base_name.split('_')[-1])
            except ValueError:
                pass
        
        format_vars = {
            'job_name': frame_stem(job.name),
            'timestamp': timestamp,
            'frame': frame_num,
            'width': job.resolution[0],
            'height': job.resolution[1],
            'format': job.output_format
        }
        
        try:
            new_name = pattern.format(**format_vars)
            return new_name + extension
        except (KeyError, ValueError):
            # Fallback to original name with timestamp
            return f"{base_name}_{timestamp}{extension}"
    
    def _handle_duplicate_filename(self, file_path: str) -> str:
        """Handle duplicate filenames by adding a counter."""
        if not os.path.exists(file_path):
            return file_path
        
        base_path = os.path.splitext(file_path)[0]
        extension = os.path.splitext(file_path)[1]
        
        counter = 1
        while True:
            new_path = f"{base_path}_{counter:03d}{extension}"
            if not os.path.exists(new_path):
                return new_path
            counter += 1
    
    def archive_old_files(self, directory: str, days_threshold: int,
                         compress: bool = True) -> int:
        """Archive files older than specified days."""
        archived_count = 0
        
        try:
            import zipfile
            from datetime import timedelta
            
            cutoff_date = datetime.now() - timedelta(days=days_threshold)
            archive_dir = os.path.join(directory, "archived")
            os.makedirs(archive_dir, exist_ok=True)
            
            if compress:
                archive_path = os.path.join(
                    archive_dir, f"archive_{datetime.now().strftime('%Y%m%d')}.zip"
                )
                
                with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for root, dirs, files in os.walk(directory):
                        if "archived" in root:
                            continue
                        
                        for file in files:
                            file_path = os.path.join(root, file)
                            file_date = datetime.fromtimestamp(os.path.getmtime(file_path))
                            
                            if file_date < cutoff_date:
                                # Add to archive
                                arcname = os.path.relpath(file_path, directory)
                                zipf.write(file_path, arcname)
                                
                                # Remove original file
                                os.remove(file_path)
                                archived_count += 1
            else:
                # Move files to archive directory without compression
                for root, dirs, files in os.walk(directory):
                    if "archived" in root:
                        continue
                    
                    for file in files:
                        file_path = os.path.join(root, file)
                        file_date = datetime.fromtimestamp(os.path.getmtime(file_path))
                        
                        if file_date < cutoff_date:
                            rel_path = os.path.relpath(file_path, directory)
                            archive_file_path = os.path.join(archive_dir, rel_path)
                            
                            os.makedirs(os.path.dirname(archive_file_path), exist_ok=True)
                            shutil.move(file_path, archive_file_path)
                            archived_count += 1
                            
        except Exception as e:
            logger.error(f"Archiving failed: {str(e)}")
        
        return archived_count


class PostProcessor:
    """Main post-processing coordinator."""
    
    def __init__(self):
        self.denoiser = ImageDenoiser()
        self.watermarker = ImageWatermarker()
        self.organizer = FileOrganizer()
    
    def process_job_output(self, job: RenderJob, settings: PostProcessingSettings,
                          output_files: List[str],
                          progress_cb: Optional[Callable[[int, str], None]] = None,
                          cancel_event: Optional[threading.Event] = None) -> PostProcessingResult:
        """Process the output files of a render job.
        progress_cb receives (percent, message) updates.
        Supports cooperative cancellation via cancel_event.
        """
        start_time = datetime.now()
        processed_files = []
        errors = []
        
        def cancelled() -> bool:
            return bool(cancel_event and cancel_event.is_set())
        
        # Calculate initial file sizes
        file_size_before = sum(
            os.path.getsize(f) for f in output_files if os.path.exists(f)
        )
        
        def report(pct: int, msg: str):
            if progress_cb:
                try:
                    progress_cb(pct, msg)
                except Exception:
                    pass
        
        try:
            total_steps = 0
            if settings.apply_denoising:
                total_steps += len(output_files)
            if settings.add_watermark:
                total_steps += len(output_files)
            if settings.auto_organize:
                total_steps += len(output_files)
            completed_steps = 0
            
            # Step 1: Denoising
            if settings.apply_denoising and not cancelled():
                report(5, "Denoising images...")
                output_files, step_processed, step_errors = self._denoise_files(
                    output_files, settings, cancel_event
                )
                processed_files.extend(step_processed)
                errors.extend(step_errors)
                completed_steps += len(step_processed)
                if total_steps:
                    report(int(5 + 45 * completed_steps / max(1, total_steps)), "Denoising complete")
            
            if cancelled():
                errors.append("Operation cancelled by user during denoising")
                raise RuntimeError("Cancelled")
            
            # Step 2: Watermarking
            if settings.add_watermark and not cancelled():
                report(50, "Applying watermarks...")
                output_files, step_processed, step_errors = self._watermark_files(
                    output_files, settings, cancel_event
                )
                processed_files.extend(step_processed)
                errors.extend(step_errors)
                completed_steps += len(step_processed)
                if total_steps:
                    report(int(50 + 40 * completed_steps / max(1, total_steps)), "Watermarking complete")
            
            if cancelled():
                errors.append("Operation cancelled by user during watermarking")
                raise RuntimeError("Cancelled")
            
            # Step 3: File Organization
            organized_files = []
            if settings.auto_organize and not cancelled():
                report(90, "Organizing files...")
                organized_files = self.organizer.organize_files(
                    output_files, output_spec(job)[0], job, settings
                )
                processed_files.extend(organized_files)
                completed_steps += len(organized_files)
                if total_steps:
                    report(98, "Organization complete")
            else:
                # If not organizing, consider the last step outputs as processed
                processed_files.extend(output_files)
            
            if cancelled():
                errors.append("Operation cancelled by user during organization")
                raise RuntimeError("Cancelled")
            
            # Step 4: Cleanup
            if settings.cleanup_temp_files and not cancelled():
                report(98, "Cleaning up temporary files...")
                self._cleanup_temp_files(job, settings)
            
            # Step 5: Archive old files
            if settings.archive_old_jobs and not cancelled():
                report(99, "Archiving old files...")
                try:
                    archived_count = self.organizer.archive_old_files(
                        output_spec(job)[0],
                        settings.archive_after_days,
                        settings.compress_archives
                    )
                    if archived_count > 0:
                        logger.info(f"Archived {archived_count} old files")
                except Exception as e:
                    errors.append(f"Archiving error: {str(e)}")
            
        except RuntimeError as re:
            # Cancellation or controlled stop
            pass
        except Exception as e:
            errors.append(f"Post-processing error: {str(e)}")
        
        # Calculate final file sizes
        file_size_after = sum(
            os.path.getsize(f) for f in processed_files if os.path.exists(f)
        )
        
        processing_time = (datetime.now() - start_time).total_seconds()
        
        return PostProcessingResult(
            success=len(errors) == 0,
            processed_files=processed_files if processed_files else output_files,
            errors=errors,
            processing_time=processing_time,
            file_size_before=file_size_before,
            file_size_after=file_size_after
        )
    
    def _denoise_files(self, files: List[str], settings: PostProcessingSettings, cancel_event: Optional[threading.Event] = None) -> Tuple[List[str], List[str], List[str]]:
        """Apply denoising to image files.
        Returns (new_files_list, processed_files, errors)
        """
        denoised_files: List[str] = []
        processed_files: List[str] = []
        errors: List[str] = []
        
        def cancelled() -> bool:
            return bool(cancel_event and cancel_event.is_set())
        
        tasks = []
        for file_path in files:
            if not self._is_image_file(file_path):
                denoised_files.append(file_path)
                continue
            base_name = os.path.splitext(file_path)[0]
            extension = os.path.splitext(file_path)[1]
            denoised_path = f"{base_name}_denoised{extension}"
            tasks.append((file_path, denoised_path))
        
        if settings.parallel_processing and tasks:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            with ThreadPoolExecutor(max_workers=max(1, settings.max_threads)) as executor:
                future_map = {executor.submit(self.denoiser.denoise_image, src, dst, settings.denoise_method, settings.denoise_strength): (src, dst) for src, dst in tasks}
                processed_srcs = set()
                for future in as_completed(future_map):
                    if cancelled():
                        # Collect remaining unprocessed sources as passthrough
                        for f, (src, _dst) in future_map.items():
                            if src not in processed_srcs:
                                denoised_files.append(src)
                        errors.append("Denoising cancelled")
                        break
                    src, dst = future_map[future]
                    processed_srcs.add(src)
                    try:
                        success = future.result()
                        if success:
                            denoised_files.append(dst)
                            processed_files.append(dst)
                            if not settings.preserve_details:
                                try:
                                    os.remove(src)
                                except OSError:
                                    pass
                        else:
                            errors.append(f"Failed to denoise {src}")
                            denoised_files.append(src)
                    except Exception as e:
                        errors.append(f"Denoising error for {src}: {str(e)}")
                        denoised_files.append(src)
        else:
            for file_path in files:
                if cancelled():
                    errors.append("Denoising cancelled")
                    # Pass through remaining files unchanged
                    for rem in files[files.index(file_path):]:
                        if rem not in denoised_files:
                            denoised_files.append(rem)
                    break
                if not self._is_image_file(file_path):
                    continue
                base_name = os.path.splitext(file_path)[0]
                extension = os.path.splitext(file_path)[1]
                denoised_path = f"{base_name}_denoised{extension}"
                try:
                    success = self.denoiser.denoise_image(
                        file_path, denoised_path,
                        settings.denoise_method, settings.denoise_strength
                    )
                    if success:
                        denoised_files.append(denoised_path)
                        processed_files.append(denoised_path)
                        if not settings.preserve_details:
                            try:
                                os.remove(file_path)
                            except OSError:
                                pass
                    else:
                        errors.append(f"Failed to denoise {file_path}")
                        denoised_files.append(file_path)
                except Exception as e:
                    errors.append(f"Denoising error for {file_path}: {str(e)}")
                    denoised_files.append(file_path)
            # Include any non-image files that were skipped
            for file_path in files:
                if not self._is_image_file(file_path) and file_path not in denoised_files:
                    denoised_files.append(file_path)
        
        # Ensure fallback
        if not denoised_files:
            denoised_files = files
        
        return denoised_files, processed_files, errors
    
    def _watermark_files(self, files: List[str], settings: PostProcessingSettings, cancel_event: Optional[threading.Event] = None) -> Tuple[List[str], List[str], List[str]]:
        """Apply watermarks to image files.
        Returns (new_files_list, processed_files, errors)
        """
        watermarked_files: List[str] = []
        processed_files: List[str] = []
        errors: List[str] = []
        
        def cancelled() -> bool:
            return bool(cancel_event and cancel_event.is_set())
        
        tasks = []
        for file_path in files:
            if not self._is_image_file(file_path):
                watermarked_files.append(file_path)
                continue
            base_name = os.path.splitext(file_path)[0]
            extension = os.path.splitext(file_path)[1]
            watermarked_path = f"{base_name}_watermarked{extension}"
            tasks.append((file_path, watermarked_path))
        
        if settings.parallel_processing and tasks:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            with ThreadPoolExecutor(max_workers=max(1, settings.max_threads)) as executor:
                future_map = {executor.submit(self.watermarker.add_watermark, src, dst,
                                              settings.watermark_text,
                                              settings.watermark_logo,
                                              settings.watermark_position,
                                              settings.watermark_opacity,
                                              settings.watermark_font_size,
                                              settings.watermark_color,
                                              settings.watermark_padding): (src, dst) for src, dst in tasks}
                processed_srcs = set()
                for future in as_completed(future_map):
                    if cancelled():
                        for f, (src, _dst) in future_map.items():
                            if src not in processed_srcs:
                                watermarked_files.append(src)
                        errors.append("Watermarking cancelled")
                        break
                    src, dst = future_map[future]
                    processed_srcs.add(src)
                    try:
                        success = future.result()
                        if success:
                            watermarked_files.append(dst)
                            processed_files.append(dst)
                            if not settings.preserve_details:
                                try:
                                    os.remove(src)
                                except OSError:
                                    pass
                        else:
                            errors.append(f"Failed to watermark {src}")
                            watermarked_files.append(src)
                    except Exception as e:
                        errors.append(f"Watermarking error for {src}: {str(e)}")
                        watermarked_files.append(src)
        else:
            for file_path in files:
                if cancelled():
                    errors.append("Watermarking cancelled")
                    for rem in files[files.index(file_path):]:
                        if rem not in watermarked_files:
                            watermarked_files.append(rem)
                    break
                if not self._is_image_file(file_path):
                    continue
                base_name = os.path.splitext(file_path)[0]
                extension = os.path.splitext(file_path)[1]
                watermarked_path = f"{base_name}_watermarked{extension}"
                try:
                    success = self.watermarker.add_watermark(
                        file_path, watermarked_path,
                        text=settings.watermark_text,
                        logo_path=settings.watermark_logo,
                        position=settings.watermark_position,
                        opacity=settings.watermark_opacity,
                        font_size=settings.watermark_font_size,
                        color=settings.watermark_color,
                        padding=settings.watermark_padding
                    )
                    if success:
                        watermarked_files.append(watermarked_path)
                        processed_files.append(watermarked_path)
                        # Remove original only if not preserving originals
                        if not settings.preserve_details:
                            try:
                                os.remove(file_path)
                            except OSError:
                                pass
                    else:
                        errors.append(f"Failed to watermark {file_path}")
                        watermarked_files.append(file_path)
                except Exception as e:
                    errors.append(f"Watermarking error for {file_path}: {str(e)}")
                    watermarked_files.append(file_path)
            # Include any non-image files that were skipped
            for file_path in files:
                if not self._is_image_file(file_path) and file_path not in watermarked_files:
                    watermarked_files.append(file_path)
        
        if not watermarked_files:
            watermarked_files = files
        
        return watermarked_files, processed_files, errors
    
    def _cleanup_temp_files(self, job: RenderJob, settings: PostProcessingSettings):
        """Clean up temporary files created during processing."""
        try:
            # Clean up job-specific temp files
            temp_dir = os.path.join(output_spec(job)[0], "temp")
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            
            # Clean up system temp files if enabled
            import tempfile
            temp_files = []
            
            # Look for RenderFox temp files
            system_temp = tempfile.gettempdir()
            cutoff = time.time() - STALE_TEMP_SECONDS
            temp_files = []
            for filename in os.listdir(system_temp):
                if not filename.startswith("renderfox_"):
                    continue
                candidate = os.path.join(system_temp, filename)
                try:
                    if os.path.getmtime(candidate) >= cutoff:
                        continue
                except OSError:
                    continue
                temp_files.append(candidate)
            
            for temp_file in temp_files:
                try:
                    if os.path.isfile(temp_file):
                        os.remove(temp_file)
                    elif os.path.isdir(temp_file):
                        shutil.rmtree(temp_file)
                except (OSError, PermissionError):
                    pass  # Skip files in use
                    
        except Exception as e:
            logger.error(f"Cleanup error: {str(e)}")
    
    def _is_image_file(self, file_path: str) -> bool:
        """Check if file is an image that can be processed."""
        image_extensions = {'.png', '.jpg', '.jpeg', '.tiff', '.tif', '.bmp', '.exr'}
        return os.path.splitext(file_path)[1].lower() in image_extensions


# Utility functions
def get_post_processing_presets() -> Dict[str, PostProcessingSettings]:
    """Get predefined post-processing presets."""
    return {
        "minimal": PostProcessingSettings(
            auto_organize=True,
            cleanup_temp_files=True,
            preserve_details=True
        ),
        "standard": PostProcessingSettings(
            apply_denoising=True,
            denoise_strength=0.3,
            auto_organize=True,
            create_subfolders=True,
            cleanup_temp_files=True,
            preserve_details=True
        ),
        "professional": PostProcessingSettings(
            apply_denoising=True,
            denoise_strength=0.5,
            denoise_method="OpenImageDenoise (OIDN)",
            add_watermark=True,
            watermark_position="bottom-right",
            watermark_opacity=0.7,
            auto_organize=True,
            create_subfolders=True,
            organize_by_date=True,
            cleanup_temp_files=True,
            archive_old_jobs=True,
            archive_after_days=30,
            preserve_details=True
        )
    }


def estimate_processing_time(files: List[str], settings: PostProcessingSettings) -> float:
    """Estimate post-processing time in seconds."""
    base_time_per_file = 2.0  # Base time per file in seconds
    
    total_time = 0
    for file_path in files:
        if os.path.exists(file_path):
            file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
            time_factor = 1.0
            
            # Denoising adds significant time
            if settings.apply_denoising:
                time_factor += 3.0 if settings.denoise_method == "OpenImageDenoise (OIDN)" else 1.5
            
            # Watermarking is relatively fast
            if settings.add_watermark:
                time_factor += 0.2
            
            # File organization is fast
            if settings.auto_organize:
                time_factor += 0.1
            
            # Parallel processing lowers time roughly inversely
            if settings.parallel_processing and settings.max_threads > 1:
                time_factor = max(0.5, time_factor / min(4, settings.max_threads))
            
            file_time = base_time_per_file * max(1.0, file_size_mb) * time_factor
            total_time += file_time
    
    return max(1.0, total_time)  # Minimum 1 second