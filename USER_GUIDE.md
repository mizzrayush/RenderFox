# RenderFox User Guide

Welcome to **RenderFox**, the advanced batch rendering manager and mesh processing tool.

## Table of Contents
1. [Getting Started](#getting-started)
2. [Model Management](#model-management)
3. [Mesh Tools](#mesh-tools)
4. [Scripting & Automation](#scripting--automation)
5. [Settings](#settings)
6. [Troubleshooting](#troubleshooting)

## Getting Started
RenderFox helps you organize, process, and render 3D models efficiently.
- **Launch**: Run `main.py` or the executable.
- **Dashboard**: The main view shows your job queue and recent activity.

## Model Management
- **Import**: Drag and drop files or use `File > Load Model`.
- **Library**: View all your indexed models in the `Model Library` tab.
- **Analysis**: Select a model and click `Analyze` to see vertex count, manifold status, and more.

## Mesh Tools
Located in the `Mesh Tools` tab, these powerful utilities help you fix and optimize models.
- **Repair**:
  - **Close Holes**: Automatically fills holes in the mesh.
  - **Make Manifold**: Fixes non-manifold geometry (edges shared by >2 faces).
  - **Fix Normals**: Orients all faces consistently.
- **Simplify**:
  - **Quadric Edge Collapse**: High-quality reduction preserving shape.
  - **Clustering**: Fast reduction for very high-poly meshes.
- **Export**: Save your processed mesh in various formats (OBJ, STL, PLY, GLTF).

## Scripting & Automation
RenderFox features a built-in Python scripting engine.
- **Editor**: Write scripts to automate repetitive tasks.
- **API**: Access internal functions via the `rfx` object.
  - `rfx.load_model(path)`
  - `rfx.process_mesh(mesh, operation)`
- **Library**: Save your favorite scripts for quick access.

## Settings
Configure the application in the `Settings` tab.
- **General**: Theme (Dark/Light), default paths.
- **Rendering**: Blender/Maya executable paths.
- **Advanced**: Enable Telemetry, configure AI models.

## Troubleshooting
- **Crashes**: If the app crashes, a dialog will appear. Please submit the report.
- **Feedback**: Use `Help > Send Feedback` to report bugs or request features.
- **Logs**: Check `~/.renderfox/logs` for detailed application logs.

---
© 2024 RenderFox Studio
