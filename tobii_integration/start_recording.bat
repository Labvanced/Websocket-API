@echo off
rem Starts the Labvanced + Tobii recorder: recording starts immediately, the window has the Stop button.
rem Extra options can be added after the script name below, e.g.  --frame-size 1600x900
rem Note: no parentheses inside the echo lines of the if-blocks, they would end the block.
cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
    echo Python was not found.
    echo Please install Python 3.13 or newer from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH" in the installer. See README.md, section 3.2.
    pause
    exit /b 1
)

python -c "import websockets" >nul 2>&1
if errorlevel 1 (
    echo Installing the Python package "websockets", only needed once ...
    python -m pip install websockets
    if errorlevel 1 (
        echo Installing "websockets" failed, see the messages above. See README.md, section 13.
        pause
        exit /b 1
    )
)

python labvanced_tobii_bridge.py %*
if errorlevel 1 pause
