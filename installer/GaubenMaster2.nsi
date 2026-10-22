Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"

!ifndef VERSION
  !error "VERSION fehlt"
!endif
!ifndef APP_DIR
  !error "APP_DIR fehlt"
!endif
!ifndef OUTDIR
  !define OUTDIR "..\dist"
!endif
!ifndef ICON
  !define ICON "..\assets\icon.ico"
!endif

!define APP_NAME "GaubenMaster2"
!define APP_EXE "GaubenMaster2.exe"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\GaubenMaster2"

Name "${APP_NAME} ${VERSION}"
OutFile "${OUTDIR}\GaubenMaster2-Setup-${VERSION}.exe"
InstallDir "$LOCALAPPDATA\Programs\GaubenMaster2"
InstallDirRegKey HKCU "Software\GaubenMaster2" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetCompressorDictSize 64
BrandingText "${APP_NAME}"
ManifestDPIAware true
ShowInstDetails nevershow
ShowUninstDetails nevershow

VIProductVersion "${VERSION}.0"
VIAddVersionKey /LANG=1031 "ProductName" "${APP_NAME}"
VIAddVersionKey /LANG=1031 "FileDescription" "${APP_NAME} Setup"
VIAddVersionKey /LANG=1031 "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=1031 "ProductVersion" "${VERSION}"
VIAddVersionKey /LANG=1031 "CompanyName" "Lukas Sonderegger"
VIAddVersionKey /LANG=1031 "LegalCopyright" "Lukas Sonderegger"

!define MUI_ICON "${ICON}"
!define MUI_UNICON "${ICON}"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "${APP_NAME} starten"
!define MUI_FINISHPAGE_NOREBOOTSUPPORT

!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "German"

Function EnsureAppClosed
  ${For} $0 1 30
    FindWindow $1 "" "${APP_NAME}"
    ${If} $1 == 0
      Return
    ${EndIf}
    Sleep 500
  ${Next}
  ${IfNot} ${Silent}
    MessageBox MB_ICONSTOP|MB_OK "${APP_NAME} läuft noch. Bitte schließen Sie die Anwendung und starten Sie das Setup erneut."
  ${EndIf}
  Abort "${APP_NAME} läuft noch."
FunctionEnd

Section "Installation" SecMain
  SetShellVarContext current
  Call EnsureAppClosed

  RMDir /r "$INSTDIR.new"
  CreateDirectory "$INSTDIR.new"
  SetOutPath "$INSTDIR.new"
  File /r "${APP_DIR}\*.*"

  SetOutPath "$TEMP"
  RMDir /r "$INSTDIR.old"
  IfFileExists "$INSTDIR\*.*" 0 no_backup
    ClearErrors
    Rename "$INSTDIR" "$INSTDIR.old"
    IfErrors 0 no_backup
      RMDir /r "$INSTDIR.new"
      Abort "Der Installationsordner konnte nicht ersetzt werden. Bitte schließen Sie alle Programme und versuchen Sie es erneut."
  no_backup:
  ClearErrors
  Rename "$INSTDIR.new" "$INSTDIR"
  IfErrors 0 swapped
    IfFileExists "$INSTDIR.old\*.*" 0 restore_done
      Rename "$INSTDIR.old" "$INSTDIR"
  restore_done:
    Abort "Die Installation ist fehlgeschlagen. Die bisherige Version wurde wiederhergestellt."
  swapped:
  RMDir /r "$INSTDIR.old"

  SetOutPath "$INSTDIR"
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  WriteRegStr HKCU "Software\GaubenMaster2" "InstallDir" "$INSTDIR"
  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\Deinstallieren.lnk" "$INSTDIR\Uninstall.exe"

  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "${APP_NAME}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher" "Lukas Sonderegger"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\${APP_EXE},0"
  WriteRegStr HKCU "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" "$\"$INSTDIR\Uninstall.exe$\""
  WriteRegStr HKCU "${UNINST_KEY}" "QuietUninstallString" "$\"$INSTDIR\Uninstall.exe$\" /S"
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1
!ifdef APP_SIZE_KB
  WriteRegDWORD HKCU "${UNINST_KEY}" "EstimatedSize" ${APP_SIZE_KB}
!endif
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\Deinstallieren.lnk"
  RMDir "$SMPROGRAMS\${APP_NAME}"
  DeleteRegKey HKCU "${UNINST_KEY}"
  DeleteRegKey HKCU "Software\GaubenMaster2"
  RMDir /r "$INSTDIR"
SectionEnd
