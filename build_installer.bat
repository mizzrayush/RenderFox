@echo off
setlocal enabledelayedexpansion

title RenderFox Build ^& Packaging Tool
cd /d "%~dp0"

echo ======================================================================
echo                  RenderFox Build & Packaging Tool
echo ======================================================================
echo.

:: Step 1: Check Python
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python is not found in PATH!
    echo Please install Python 3.10+ and add it to your system PATH.
    echo.
    pause
    exit /b 1
)

:: Step 2: Build PyInstaller standalone bundle
echo [*] Step 1/2: Building PyInstaller executable bundle...
echo ----------------------------------------------------------------------
python build_exe.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] PyInstaller build failed! Check output above.
    echo.
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo [OK] PyInstaller build completed successfully.
echo.

:: Step 3: Locate NSIS makensis.exe
echo [*] Step 2/2: Compiling NSIS Setup Installer...
echo ----------------------------------------------------------------------

set "MAKENSIS="
if exist "C:\Program Files (x86)\NSIS\makensis.exe" (
    set "MAKENSIS=C:\Program Files (x86)\NSIS\makensis.exe"
) else if exist "C:\Program Files\NSIS\makensis.exe" (
    set "MAKENSIS=C:\Program Files\NSIS\makensis.exe"
) else (
    where makensis >nul 2>&1
    if !ERRORLEVEL! EQU 0 (
        set "MAKENSIS=makensis"
    )
)

if "%MAKENSIS%"=="" (
    echo [ERROR] NSIS (makensis.exe) not found!
    echo Please install NSIS from https://nsis.sourceforge.io/
    echo or ensure it is installed in standard Program Files directory.
    echo.
    pause
    exit /b 1
)

echo [*] Using NSIS compiler: "%MAKENSIS%"
"%MAKENSIS%" installer.nsi
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] NSIS compilation failed!
    echo.
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo ======================================================================
echo [SUCCESS] RenderFox Setup Installer built successfully!
echo Location: %~dp0RenderFox_Setup.exe
echo ======================================================================
echo.

pause
exit /b 0
