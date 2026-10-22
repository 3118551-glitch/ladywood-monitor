@echo off
REM Ladywood Environmental Monitor - Progress Report 3 prototype
REM Double-click this file to start the dashboard.
cd /d "%~dp0"
if not exist .venv (
    echo First run: setting up Python packages, this takes a few minutes...
    py -m venv .venv || python -m venv .venv
    .venv\Scripts\python -m pip install --upgrade pip
    .venv\Scripts\python -m pip install -r requirements.txt
)
.venv\Scripts\python -m streamlit run app.py
pause
