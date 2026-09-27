; PDF转换工具 安装程序脚本（NSIS 3）
; 编译：_nsis\nsis-bundle\windows\makensis.exe setup.nsi

!include "MUI2.nsh"

Name "PDF转换工具"
OutFile "installer\PDF转换工具_Setup.exe"
Unicode True
; 装到用户目录：无需管理员权限，且应用内一键安装 GPU 加速包需要对安装目录有写权限
InstallDir "$LOCALAPPDATA\Programs\PDF转换工具"
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

Section "Install"
    SetOutPath "$INSTDIR"
    File /r "dist\PDF转换工具\*.*"

    WriteUninstaller "$INSTDIR\卸载 PDF转换工具.exe"

    CreateDirectory "$SMPROGRAMS\PDF转换工具"
    CreateShortcut "$SMPROGRAMS\PDF转换工具\PDF转换工具.lnk" "$INSTDIR\PDF转换工具.exe"
    CreateShortcut "$SMPROGRAMS\PDF转换工具\卸载 PDF转换工具.lnk" "$INSTDIR\卸载 PDF转换工具.exe"
    CreateShortcut "$DESKTOP\PDF转换工具.lnk" "$INSTDIR\PDF转换工具.exe"

    ; 注册到 Windows「应用和功能」
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\PDF转换工具" "DisplayName" "PDF转换工具"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\PDF转换工具" "DisplayVersion" "1.0.0"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\PDF转换工具" "Publisher" "SmallH0433"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\PDF转换工具" "DisplayIcon" "$INSTDIR\PDF转换工具.exe"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\PDF转换工具" "UninstallString" "$INSTDIR\卸载 PDF转换工具.exe"
    WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\PDF转换工具" "NoModify" 1
    WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\PDF转换工具" "NoRepair" 1
SectionEnd

Section "Uninstall"
    RMDir /r "$INSTDIR"
    Delete "$SMPROGRAMS\PDF转换工具\PDF转换工具.lnk"
    Delete "$SMPROGRAMS\PDF转换工具\卸载 PDF转换工具.lnk"
    RMDir "$SMPROGRAMS\PDF转换工具"
    Delete "$DESKTOP\PDF转换工具.lnk"
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\PDF转换工具"
SectionEnd
