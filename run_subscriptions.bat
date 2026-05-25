@echo off
REM ─────────────────────────────────────────────────────────────
REM  True Harvest — Daily Subscription Automation
REM  Run by Windows Task Scheduler every morning at 6:00 AM
REM ─────────────────────────────────────────────────────────────

cd /d "C:\Users\ADMIN\True Harvest\true_harvest_api"

REM Activate virtual environment
call ..\venv\Scripts\activate.bat

REM Run the subscription processor and append output to log file
echo. >> subscription_log.txt
echo ======================================== >> subscription_log.txt
python process_subscriptions.py >> subscription_log.txt 2>&1

echo Done. Check subscription_log.txt for details.
