@echo off
rem ============================================================
rem multi-agent dev launcher (Windows cmd wrapper, ASCII only)
rem Executes scripts/dev.sh via Git Bash (bundled with Git for Windows)
rem Usage: scripts\dev.bat   (works from any directory)
rem ============================================================

rem UTF-8 codepage for .sh output (Chinese/emoji friendly, Win10+)
chcp 65001 >nul

rem Locate project root (this file lives under scripts/, root = parent)
cd /d "%~dp0.."

rem Locate Git for Windows bash by fixed path. Do NOT use `where bash`:
rem in a default cmd PATH, System32 comes first, so `where bash` resolves to
rem C:\Windows\System32\bash.exe (WSL launcher), which errors out when no
rem WSL distro is installed (WSL Relay: execvpe(/bin/bash) failed).
set "GIT_BASH=%ProgramFiles%\Git\bin\bash.exe"
if not exist "%GIT_BASH%" set "GIT_BASH=%ProgramFiles(x86)%\Git\bin\bash.exe"
if not exist "%GIT_BASH%" (
    echo [ERROR] Git for Windows bash not found. Install from https://git-scm.com
    echo [HINT] WSL bash is NOT supported: dev scripts need the MSYS environment
    pause
    exit /b 1
)

rem Delegate to the real script, propagate exit code
"%GIT_BASH%" scripts/dev.sh
exit /b %errorlevel%
