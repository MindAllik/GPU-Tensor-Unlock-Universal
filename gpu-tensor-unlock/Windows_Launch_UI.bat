@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
echo ============================================================================
echo   NVIDIA GPU TENSOR UNLOCK // WINDOWS_LAUNCH_UI [WINDOWS 10 / 11]
echo ============================================================================
if not "%OS%"=="Windows_NT" (
    echo [OS ERROR] Windows_Launch_UI.bat can only be run on Windows 10/11.
    echo [OS ERROR] On Linux, please run: ./Linux_Launch_UI.sh
    pause
    exit /b 2
)
if defined WINEPREFIX (
    echo [OS ERROR] Running under Wine on Linux is not supported.
    echo [OS ERROR] On Linux, please run the native launcher: ./Linux_Launch_UI.sh
    pause
    exit /b 2
)
where python >nul 2>&1
if !ERRORLEVEL! EQU 0 (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
    if !ERRORLEVEL! EQU 0 (
        python "%~dp0gpu_unlock_ui.py"
        set "RC=!ERRORLEVEL!"
        if !RC! NEQ 0 pause
        exit /b !RC!
    )
)
where py >nul 2>&1
if !ERRORLEVEL! EQU 0 (
    py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
    if !ERRORLEVEL! EQU 0 (
        py -3 "%~dp0gpu_unlock_ui.py"
        set "RC=!ERRORLEVEL!"
        if !RC! NEQ 0 pause
        exit /b !RC!
    )
)
echo [ERROR] Python 3.10+ not found in PATH. Please install Python 3.10+ from python.org.
pause
exit /b 1
