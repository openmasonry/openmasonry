@echo off
rem om: the OpenMasonry command line on native Windows (cmd.exe and PowerShell). It finds Python 3.11 or
rem newer as OM_PYTHON, the py launcher or python, and runs it with this clone's src on PYTHONPATH.
setlocal
rem UTF-8 output, also into a pipe: an agent reads it, and the console code page cannot write every mark.
set "PYTHONUTF8=1"
set "OM_ROOT=%~dp0.."
if defined PYTHONPATH (set "PYTHONPATH=%OM_ROOT%\src;%PYTHONPATH%") else (set "PYTHONPATH=%OM_ROOT%\src")
set "OM_CHECK=import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if not defined OM_PYTHON goto try_py
"%OM_PYTHON%" -c "%OM_CHECK%" >nul 2>nul && goto use_om_python
:try_py
py -3 -c "%OM_CHECK%" >nul 2>nul && goto use_py
python -c "%OM_CHECK%" >nul 2>nul && goto use_python
echo om needs Python 3.11 or newer (install it from python.org or with: winget install Python.Python.3.12; or set OM_PYTHON) 1>&2
exit /b 1
:use_om_python
"%OM_PYTHON%" -m openmasonry %*
exit /b %ERRORLEVEL%
:use_py
py -3 -m openmasonry %*
exit /b %ERRORLEVEL%
:use_python
python -m openmasonry %*
exit /b %ERRORLEVEL%
