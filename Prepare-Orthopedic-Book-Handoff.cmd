@echo off
setlocal
set "PYTHONUTF8=1"
cd /d "%~dp0"
if errorlevel 1 goto project_missing
if not exist "%~dp0backend\tools\orthopedic_book_handoff.py" goto project_missing
if not defined LOCALAPPDATA goto output_unavailable

set "MOS_HANDOFF_SOURCE=D:\orthopedic book"
if not "%~1"=="" set "MOS_HANDOFF_SOURCE=%~1"
set "MOS_HANDOFF_PYTHON=%~dp0.venv-books\Scripts\python.exe"
set "MOS_HANDOFF_PYTHON_ARGS="
if not exist "%MOS_HANDOFF_PYTHON%" goto try_py
"%MOS_HANDOFF_PYTHON%" -B -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 2)" >nul 2>nul
if not errorlevel 1 goto python_ready

:try_py
where py >nul 2>nul
if errorlevel 1 goto try_python
set "MOS_HANDOFF_PYTHON=py"
set "MOS_HANDOFF_PYTHON_ARGS=-3"
"%MOS_HANDOFF_PYTHON%" %MOS_HANDOFF_PYTHON_ARGS% -B -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 2)" >nul 2>nul
if not errorlevel 1 goto python_ready

:try_python
where python >nul 2>nul
if errorlevel 1 goto python_unavailable
set "MOS_HANDOFF_PYTHON=python"
set "MOS_HANDOFF_PYTHON_ARGS="
"%MOS_HANDOFF_PYTHON%" -B -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 2)" >nul 2>nul
if errorlevel 1 goto python_unavailable

:python_ready
:choose_output
set "MOS_HANDOFF_OUTPUT=%LOCALAPPDATA%\4B-MOS\orthopedic-handoffs\handoff-%RANDOM%-%RANDOM%-%RANDOM%.json"
if exist "%MOS_HANDOFF_OUTPUT%" goto choose_output
echo Checking the existing extraction and the selected original PDFs locally.
echo This can take a few minutes for large books. Extraction will not be repeated.
"%MOS_HANDOFF_PYTHON%" %MOS_HANDOFF_PYTHON_ARGS% -B "%~dp0backend\tools\orthopedic_book_handoff.py" --source "%MOS_HANDOFF_SOURCE%" --latest --output "%MOS_HANDOFF_OUTPUT%"
set "MOS_HANDOFF_RESULT=%ERRORLEVEL%"
echo.
if "%MOS_HANDOFF_RESULT%"=="0" goto complete
if "%MOS_HANDOFF_RESULT%"=="1" goto partial
echo ERROR: The handoff could not be completed. Read the tool message above.
if exist "%MOS_HANDOFF_OUTPUT%" echo Output to review: "%MOS_HANDOFF_OUTPUT%"
goto finished

:complete
echo SUCCESS: Local provenance checks completed. This is not medical approval.
echo Private handoff: "%MOS_HANDOFF_OUTPUT%"
goto finished

:partial
echo PARTIAL: A handoff was prepared with items requiring review.
echo Missing or changed PDFs and failed or empty pages are not eligible evidence.
echo Private handoff: "%MOS_HANDOFF_OUTPUT%"
goto finished

:project_missing
echo ERROR: Open this launcher from the complete 4B-MOS project folder.
echo The backend\tools\orthopedic_book_handoff.py file must be present.
set "MOS_HANDOFF_RESULT=2"
goto finished

:output_unavailable
echo ERROR: LOCALAPPDATA is unavailable, so a private output path cannot be selected.
echo Use the documented command with an explicit private --output path.
set "MOS_HANDOFF_RESULT=2"
goto finished

:python_unavailable
echo ERROR: Python 3.12 or later is required. No installation was attempted.
echo The launcher checks .venv-books first, then py -3 or python.
set "MOS_HANDOFF_RESULT=2"

:finished
echo No upload, database import or medical approval was performed by this launcher.
pause
exit /b %MOS_HANDOFF_RESULT%
