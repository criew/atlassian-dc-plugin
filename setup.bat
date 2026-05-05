@echo off
setlocal enabledelayedexpansion

REM Setup script for Atlassian DC Skills (Windows)
REM Checks prerequisites and installs the requests module if missing.

echo === Atlassian DC Skills — Setup ===
echo.

REM 1. Check Python
set "PYTHON="
where python >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON=python"
) else (
    where python3 >nul 2>&1
    if %errorlevel% equ 0 (
        set "PYTHON=python3"
    )
)

if not defined PYTHON (
    echo [FAIL] Python nicht gefunden. Bitte Python 3.6+ installieren.
    echo        Download: https://www.python.org/downloads/
    exit /b 1
)

for /f "tokens=*" %%v in ('%PYTHON% -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"') do set PY_VERSION=%%v
for /f "tokens=*" %%v in ('%PYTHON% -c "import sys; print(sys.version_info.major)"') do set PY_MAJOR=%%v
for /f "tokens=*" %%v in ('%PYTHON% -c "import sys; print(sys.version_info.minor)"') do set PY_MINOR=%%v

if !PY_MAJOR! lss 3 (
    echo [FAIL] Python !PY_VERSION! gefunden, aber 3.6+ wird benoetigt.
    exit /b 1
)
if !PY_MAJOR! equ 3 if !PY_MINOR! lss 6 (
    echo [FAIL] Python !PY_VERSION! gefunden, aber 3.6+ wird benoetigt.
    exit /b 1
)

echo [OK] Python !PY_VERSION! (%PYTHON%)

REM 2. Check requests module
%PYTHON% -c "import requests" >nul 2>&1
if %errorlevel% equ 0 (
    for /f "tokens=*" %%v in ('%PYTHON% -c "import requests; print(requests.__version__)"') do (
        echo [OK] requests %%v
    )
) else (
    echo [WARN] Python-Modul 'requests' nicht gefunden. Wird installiert...
    %PYTHON% -m pip install --user requests
    if %errorlevel% equ 0 (
        for /f "tokens=*" %%v in ('%PYTHON% -c "import requests; print(requests.__version__)"') do (
            echo [OK] requests %%v installiert
        )
    ) else (
        echo [FAIL] Installation von 'requests' fehlgeschlagen.
        echo        Bitte manuell: %PYTHON% -m pip install requests
        exit /b 1
    )
)

REM 3. Check instances.json
if defined ATLASSIAN_INSTANCES_FILE (
    set "INSTANCES_FILE=%ATLASSIAN_INSTANCES_FILE%"
) else if defined APPDATA (
    set "INSTANCES_FILE=%APPDATA%\atlassian\instances.json"
) else (
    set "INSTANCES_FILE=%USERPROFILE%\.config\atlassian\instances.json"
)

if exist "!INSTANCES_FILE!" (
    echo [OK] instances.json gefunden: !INSTANCES_FILE!
) else (
    echo [WARN] instances.json nicht gefunden unter: !INSTANCES_FILE!

    REM Determine config dir from instances file path
    for %%F in ("!INSTANCES_FILE!") do set "CONFIG_DIR=%%~dpF"
    if not exist "!CONFIG_DIR!" mkdir "!CONFIG_DIR!"

    set "SCRIPT_DIR=%~dp0"
    if exist "!SCRIPT_DIR!instances.json.example" (
        copy "!SCRIPT_DIR!instances.json.example" "!INSTANCES_FILE!" >nul
        echo [OK] instances.json.example kopiert nach !INSTANCES_FILE!
        echo      Bitte URL und PAT in !INSTANCES_FILE! eintragen.
    ) else (
        echo [WARN] Keine Beispieldatei gefunden. Bitte instances.json manuell anlegen.
    )
)

echo.
echo Setup abgeschlossen.
echo Skripte ausfuehren mit: %PYTHON% skills\jira-dc\scripts\core\jira_issue.py get KEY-1

endlocal
