; PDF转换工具 安装程序脚本（NSIS 3）
; 编译：PowerShell 中运行 _nsis\nsis-bundle\makensis.ps1 setup.nsi

!include "MUI2.nsh"
!include "FileFunc.nsh"

!define APP_VERSION "1.2.4"
!define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\PDF转换工具"

Name "PDF转换工具"
OutFile "installer\PDF-Converter-Setup-${APP_VERSION}.exe"
Unicode True
; 装到用户目录：无需管理员权限，且应用内一键安装 GPU 加速包需要对安装目录有写权限
; 空目录便于区分 /D= 显式指定的路径与默认路径，优先沿用旧版安装位置
InstallDir ""
RequestExecutionLevel user
SetCompressor /SOLID lzma

!define MUI_FINISHPAGE_RUN "$INSTDIR\PDF转换工具.exe"
!define MUI_FINISHPAGE_RUN_TEXT "立即运行 PDF转换工具"

!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "SimpChinese"

Function .onInit
    SetShellVarContext current
    StrCmp $INSTDIR "" 0 install_dir_ready

    ; 新版记录完整路径；兼容 1.2.3 及更早版本仅记录卸载程序路径的注册表项
    ReadRegStr $0 HKCU "${UNINSTALL_KEY}" "InstallLocation"
    IfFileExists "$0\PDF转换工具.exe" 0 legacy_install_dir
    StrCpy $INSTDIR "$0"
    Goto install_dir_ready

legacy_install_dir:
    ReadRegStr $0 HKCU "${UNINSTALL_KEY}" "UninstallString"
    StrCmp $0 "" default_install_dir
    ${GetParent} "$0" $1
    IfFileExists "$1\PDF转换工具.exe" 0 default_install_dir
    StrCpy $INSTDIR "$1"
    Goto install_dir_ready

default_install_dir:
    StrCpy $INSTDIR "$LOCALAPPDATA\Programs\PDF转换工具"

install_dir_ready:
FunctionEnd

Section "Install"
    ; 运行中的程序会锁住 DLL，先提示退出，绝不留下半覆盖的文件
    nsProcess::_FindProcess "PDF转换工具.exe"
    Pop $0
    StrCmp $0 "603" process_closed
    IfSilent +2
    MessageBox MB_OK|MB_ICONEXCLAMATION "请先关闭 PDF转换工具，然后重新运行安装程序。"
    SetErrorLevel 1
    Abort

process_closed:
    ; 仅对已识别的旧版安装清理程序依赖，保留同级的 ocr_modules 加速包
    IfFileExists "$INSTDIR\PDF转换工具.exe" 0 copy_files
    IfFileExists "$INSTDIR\卸载 PDF转换工具.exe" 0 copy_files
    ClearErrors
    RMDir /r "$INSTDIR\_internal"
    IfErrors 0 copy_files
    IfSilent +2
    MessageBox MB_OK|MB_ICONSTOP "旧版本文件清理失败。请关闭相关程序后重试。"
    SetErrorLevel 1
    Abort

copy_files:
    SetOutPath "$INSTDIR"
    ; 对手动复制的旧程序也清理 1.2.2 遗留的错误 DLL
    Delete "$INSTDIR\_internal\icuuc.dll"
    Delete "$INSTDIR\_internal\icudt78.dll"
    File /r "dist\PDF转换工具\*.*"

    WriteUninstaller "$INSTDIR\卸载 PDF转换工具.exe"

    CreateDirectory "$SMPROGRAMS\PDF转换工具"
    CreateShortcut "$SMPROGRAMS\PDF转换工具\PDF转换工具.lnk" "$INSTDIR\PDF转换工具.exe"
    CreateShortcut "$SMPROGRAMS\PDF转换工具\卸载 PDF转换工具.lnk" "$INSTDIR\卸载 PDF转换工具.exe"
    CreateShortcut "$DESKTOP\PDF转换工具.lnk" "$INSTDIR\PDF转换工具.exe"

    ; 注册到 Windows「应用和功能」
    WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayName" "PDF转换工具"
    WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayVersion" "${APP_VERSION}"
    WriteRegStr HKCU "${UNINSTALL_KEY}" "Publisher" "SmallH0433"
    WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayIcon" "$INSTDIR\PDF转换工具.exe"
    WriteRegStr HKCU "${UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
    WriteRegStr HKCU "${UNINSTALL_KEY}" "UninstallString" '$\"$INSTDIR\卸载 PDF转换工具.exe$\"'
    WriteRegStr HKCU "${UNINSTALL_KEY}" "QuietUninstallString" '$\"$INSTDIR\卸载 PDF转换工具.exe$\" /S'
    WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoModify" 1
    WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoRepair" 1

    ; 注册到 .pdf「打开方式」（ProgId + OpenWithProgids，不抢占默认关联）
    WriteRegStr HKCU "Software\Classes\PDFConverterTool.pdf" "" "PDF 文档 (PDF转换工具)"
    WriteRegStr HKCU "Software\Classes\PDFConverterTool.pdf\DefaultIcon" "" '"$INSTDIR\PDF转换工具.exe",0'
    WriteRegStr HKCU "Software\Classes\PDFConverterTool.pdf\shell\open" "" "用 PDF转换工具 打开"
    WriteRegStr HKCU "Software\Classes\PDFConverterTool.pdf\shell\open\command" "" '"$INSTDIR\PDF转换工具.exe" "%1"'
    WriteRegStr HKCU "Software\Classes\.pdf\OpenWithProgids" "PDFConverterTool.pdf" ""
SectionEnd

Section "Uninstall"
    RMDir /r "$INSTDIR"
    Delete "$SMPROGRAMS\PDF转换工具\PDF转换工具.lnk"
    Delete "$SMPROGRAMS\PDF转换工具\卸载 PDF转换工具.lnk"
    RMDir "$SMPROGRAMS\PDF转换工具"
    Delete "$DESKTOP\PDF转换工具.lnk"
    DeleteRegKey HKCU "${UNINSTALL_KEY}"
    DeleteRegKey HKCU "Software\Classes\PDFConverterTool.pdf"
    DeleteRegValue HKCU "Software\Classes\.pdf\OpenWithProgids" "PDFConverterTool.pdf"
SectionEnd
