; RenderFox Professional Installer Script
; Built with NSIS v3+
; Includes: Core RenderFox App, FFmpeg Transcoder, OpenAI CLIP Offline Model, and Add/Remove Programs registration

;--------------------------------
;General Definitions

  !define PRODUCT_NAME "RenderFox"
  !define PRODUCT_VERSION "1.0.0"
  !define PRODUCT_PUBLISHER "RenderFox Studio"
  !define PRODUCT_WEB_SITE "https://github.com/RenderFox/RenderFox"
  !define PRODUCT_UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_NAME}"
  !define PRODUCT_UNINST_ROOT_KEY "HKCU"

  Name "${PRODUCT_NAME} ${PRODUCT_VERSION}"
  OutFile "RenderFox_Setup.exe"
  Unicode True

  ;Default installation folder (User Profile / Program Files 64)
  InstallDir "$PROGRAMFILES64\RenderFox"
  InstallDirRegKey HKCU "Software\RenderFox" "InstallDir"

  ;Request admin privileges for system-wide / program files installation
  RequestExecutionLevel admin

;--------------------------------
;Interface Settings

  !include "MUI2.nsh"

  !define MUI_ABORTWARNING
  
  ;Application branding icons
  !define MUI_ICON "resources\icon.ico"
  !define MUI_UNICON "resources\icon.ico"
  
  ;Header images if available
  !define MUI_HEADERIMAGE
  !define MUI_HEADERIMAGE_BITMAP_NOSTRETCH

;--------------------------------
;Installer Pages

  !insertmacro MUI_PAGE_WELCOME
  !insertmacro MUI_PAGE_LICENSE "LICENSE"
  !insertmacro MUI_PAGE_COMPONENTS  ; Allow user to select components
  !insertmacro MUI_PAGE_DIRECTORY
  !insertmacro MUI_PAGE_INSTFILES
  
  ; Finish page with option to run RenderFox immediately
  !define MUI_FINISHPAGE_RUN "$INSTDIR\RenderFox.exe"
  !define MUI_FINISHPAGE_RUN_TEXT "Launch RenderFox Studio"
  !insertmacro MUI_PAGE_FINISH

;--------------------------------
;Uninstaller Pages

  !insertmacro MUI_UNPAGE_WELCOME
  !insertmacro MUI_UNPAGE_CONFIRM
  !insertmacro MUI_UNPAGE_INSTFILES
  !insertmacro MUI_UNPAGE_FINISH

;--------------------------------
;Languages

  !insertmacro MUI_LANGUAGE "English"

;--------------------------------
;Installer Sections

Section "RenderFox Core (Required)" SecCore
  SectionIn RO  ; Read-only, always installed
  
  SetOutPath "$INSTDIR"
  
  ; Copy the PyInstaller onedir build: RenderFox.exe into $INSTDIR, its shipped files into _internal
  File /r "dist\RenderFox\*.*"

  ; Store installation folder in registry
  WriteRegStr HKCU "Software\RenderFox" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "Software\RenderFox" "Version" "${PRODUCT_VERSION}"
  
  ; Create uninstaller
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  
  ; Register in Windows Add/Remove Programs
  WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "DisplayName" "${PRODUCT_NAME} 3D Batch Studio"
  WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
  WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "DisplayIcon" "$INSTDIR\_internal\resources\icon.ico"
  WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "DisplayVersion" "${PRODUCT_VERSION}"
  WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "Publisher" "${PRODUCT_PUBLISHER}"
  WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "InstallLocation" "$INSTDIR"
  
  ; Create Start Menu Shortcuts
  CreateDirectory "$SMPROGRAMS\RenderFox"
  CreateShortcut "$SMPROGRAMS\RenderFox\RenderFox.lnk" "$INSTDIR\RenderFox.exe" "" "$INSTDIR\_internal\resources\icon.ico" 0
  CreateShortcut "$SMPROGRAMS\RenderFox\Uninstall RenderFox.lnk" "$INSTDIR\Uninstall.exe" "" "$INSTDIR\Uninstall.exe" 0
  
  ; Create Desktop Shortcut
  CreateShortcut "$DESKTOP\RenderFox.lnk" "$INSTDIR\RenderFox.exe" "" "$INSTDIR\_internal\resources\icon.ico" 0

SectionEnd

Section "FFmpeg Transcoder (Recommended)" SecFFmpeg
  
  SetOutPath "$INSTDIR\ffmpeg"
  
  ; Copy bundled FFmpeg binaries and libraries
  File /r "resources\ffmpeg-2025-12-22-git-c50e5c7778-essentials_build\*.*"
  
  ; Append FFmpeg bin to user PATH environment variable
  ReadRegStr $0 HKCU "Environment" "PATH"
  WriteRegExpandStr HKCU "Environment" "PATH" "$0;$INSTDIR\ffmpeg\bin"
  
  ; Broadcast system environment change notification
  SendMessage ${HWND_BROADCAST} ${WM_SETTINGCHANGE} 0 "STR:Environment" /TIMEOUT=5000

SectionEnd

Section "OpenAI CLIP Model (Offline AI Tagging)" SecCLIP
  
  SetOutPath "$INSTDIR\OPENai Clip"
  
  ; Copy local pre-downloaded OpenAI CLIP weights and tokenizers for instant offline AI tagging
  File /r "OPENai Clip\*.*"
  
SectionEnd

Section /o "Download Stable Diffusion 1.5 (~4GB)" SecSD
  
  DetailPrint "Starting optional Stable Diffusion 1.5 model download..."
  ExecWait '"$INSTDIR\RenderFox.exe" --download-models'
  
SectionEnd

; Component Descriptions
!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecCore} "The core RenderFox application and GUI components."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecFFmpeg} "Bundles FFmpeg for video rendering and animation export. Automatically registers FFmpeg in your PATH."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecCLIP} "Installs the OpenAI CLIP neural model for instant offline 3D model classification and smart tagging (~600MB)."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecSD} "Optional: Downloads Stable Diffusion 1.5 checkpoint (~4GB) for AI texture generation. Requires internet."
!insertmacro MUI_FUNCTION_DESCRIPTION_END

;--------------------------------
;Uninstaller Section

Section "Uninstall"

  ; Delete installed directory recursively
  RMDir /r "$INSTDIR"
  
  ; Remove Start Menu Shortcuts
  Delete "$SMPROGRAMS\RenderFox\RenderFox.lnk"
  Delete "$SMPROGRAMS\RenderFox\Uninstall RenderFox.lnk"
  RMDir "$SMPROGRAMS\RenderFox"
  
  ; Remove Desktop Shortcut
  Delete "$DESKTOP\RenderFox.lnk"

  ; Remove Registry Keys
  DeleteRegKey ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}"
  DeleteRegKey HKCU "Software\RenderFox"

SectionEnd
