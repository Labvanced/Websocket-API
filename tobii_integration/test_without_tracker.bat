@echo off
rem Same as start_recording.bat, but with a simulated eye tracker: for testing the Labvanced study setup.
call "%~dp0start_recording.bat" --mock %*
