@echo off
REM Double-click to start the screen watcher in follow-friendly mode.
REM After it starts, tell your AI "Follow Mode On", then ask it to run:
REM     py screen_watcher.py follow grab
REM for reliable visual observation.
powershell -ExecutionPolicy Bypass -File "%~dp0Start-ScreenWatcher.ps1" %*
pause
