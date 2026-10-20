@echo off
setlocal
set "PYTHONUTF8=1"
cd /d "%~dp0"
set "MOS_BOOK_PYTHON=%~dp0.venv-books\Scripts\python.exe"
if exist "%MOS_BOOK_PYTHON%" goto reader_ready
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -m venv "%~dp0.venv-books"
) else (
  python -m venv "%~dp0.venv-books"
)
if errorlevel 1 goto setup_failed
:reader_ready
"%MOS_BOOK_PYTHON%" -c "import sys; assert sys.version_info >= (3, 12)" >nul 2>nul
if errorlevel 1 goto setup_failed
"%MOS_BOOK_PYTHON%" -c "import importlib.metadata; assert importlib.metadata.version('pypdf') == '6.21.1'" >nul 2>nul
if errorlevel 1 (
  echo First setup downloads the optional PDF reader. Book processing stays local.
  "%MOS_BOOK_PYTHON%" -m pip install -r "%~dp0backend\requirements-books.txt"
  if errorlevel 1 goto setup_failed
)
if "%~1"=="" (
  "%MOS_BOOK_PYTHON%" "%~dp0backend\tools\local_orthopedic_library.py" --source "D:\orthopedic book"
) else (
  "%MOS_BOOK_PYTHON%" "%~dp0backend\tools\local_orthopedic_library.py" --source "%~1"
)
set "MOS_BOOK_RESULT=%ERRORLEVEL%"
echo.
if "%MOS_BOOK_RESULT%"=="1" echo Finished with items requiring review. See the local report above.
pause
exit /b %MOS_BOOK_RESULT%
:setup_failed
echo Setup failed. Install Python 3.12 or later and rerun this file.
echo No book has been uploaded or added to approved medical knowledge.
pause
exit /b 2
