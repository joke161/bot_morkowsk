@echo off
:: Set console output to UTF-8 just in case, but keep script ASCII-only to prevent CMD encoding bugs
chcp 65001 > nul

echo ==================================================
echo      Initializing RPA Bot "Morkovsk"
echo ==================================================

:: Detect Python environment
if exist ".venv\Scripts\python.exe" (
    echo [INFO] Virtual environment .venv detected.
    set "PYTHON_EXE=.venv\Scripts\python.exe"
    set "PIP_EXE=.venv\Scripts\pip.exe"
) else (
    echo [WARNING] .venv not found. Falling back to global Python.
    set "PYTHON_EXE=python"
    set "PIP_EXE=pip"
)

:: Verify Python is installed and accessible
%PYTHON_EXE% --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python was not found on your system!
    echo Please install Python 3.10+ and add it to system PATH.
    pause
    exit /b 1
)

:: Check and install requirements
if exist "requirements.txt" (
    echo [INFO] Verifying dependencies from requirements.txt...
    %PIP_EXE% install -r requirements.txt --quiet
    if %errorlevel% neq 0 (
        echo [WARNING] Quiet installation failed. Retrying with verbose...
        %PYTHON_EXE% -m pip install --upgrade pip
        %PIP_EXE% install -r requirements.txt
    )
) else (
    echo [WARNING] requirements.txt not found. Skipping dependency installation.
)

echo [INFO] Setup verification completed.
echo [INFO] Launching bot.py...
echo ==================================================
echo.

:: Launch the bot script
%PYTHON_EXE% bot.py

pause
