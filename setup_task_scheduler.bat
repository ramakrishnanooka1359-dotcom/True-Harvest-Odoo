@echo off
REM ─────────────────────────────────────────────────────────────────────────
REM  setup_task_scheduler.bat
REM  Run this ONCE as Administrator to register the daily subscription job.
REM  It will run "run_subscriptions.bat" every day at 6:00 AM.
REM ─────────────────────────────────────────────────────────────────────────

set TASK_NAME=TrueHarvestSubscriptions
set SCRIPT_PATH=C:\Users\ADMIN\True Harvest\true_harvest_api\run_subscriptions.bat
set START_TIME=06:00

echo Registering Task Scheduler job: %TASK_NAME%

schtasks /create ^
    /tn "%TASK_NAME%" ^
    /tr "\"%SCRIPT_PATH%\"" ^
    /sc DAILY ^
    /st %START_TIME% ^
    /ru "%USERNAME%" ^
    /rl HIGHEST ^
    /f

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ✔ Task created successfully!
    echo   Name:    %TASK_NAME%
    echo   Script:  %SCRIPT_PATH%
    echo   Runs at: %START_TIME% daily
    echo.
    echo To verify: Open Task Scheduler → Task Scheduler Library → %TASK_NAME%
    echo To run now for testing: schtasks /run /tn "%TASK_NAME%"
) else (
    echo.
    echo ✖ Failed to create task. Make sure you are running as Administrator.
)

pause
