:: Runs the whole test suite on Windows.
@echo off
setlocal

:: Set paths for Kivy scripts and music_player.py (adjust as needed).
set REPO_LOCATION=%USERPROFILE%\git
set KIVY_PATH=%REPO_LOCATION%\DancePracticeMusicPlayer\kivy_venv\Scripts
set MUSIC_PLAYER_PATH=%REPO_LOCATION%\DancePracticeMusicPlayer

set PATH=%KIVY_PATH%;%MUSIC_PLAYER_PATH%;%PATH%

echo Running unit tests for Music Player...
if not exist "%KIVY_PATH%" (
    echo Kivy path does not exist: %KIVY_PATH%
    exit /b 1
)
if not exist "%MUSIC_PLAYER_PATH%" (
    echo Music Player path does not exist: %MUSIC_PLAYER_PATH%
    exit /b 1
)
if not exist "%KIVY_PATH%\activate" (
    echo Kivy virtual environment activation script not found: %KIVY_PATH%\activate
    exit /b 1
)
if not exist "%MUSIC_PLAYER_PATH%\tests" (
    echo Tests folder not found: %MUSIC_PLAYER_PATH%\tests
    exit /b 1
)

echo Activating Kivy virtual environment and running tests...
cd /d %KIVY_PATH%
call activate
cd /d %MUSIC_PLAYER_PATH%

:: Stop Kivy from consuming the test runner's command line arguments. Kivy does
:: still open its SDL window while the tests run: the editor tests build real
:: widgets and fail without a window provider, so there is no headless option
:: here. Harmless on a desktop, but the tests are not suitable for a session
:: with no display.
set KIVY_NO_ARGS=1

:: Run every test in tests/, not just one file. pytest is preferred because it
:: reports coverage as well, but the suite is plain unittest, so a machine
:: without pytest installed still runs all of it through unittest discovery.
::
:: "if errorlevel 1" rather than "if %ERRORLEVEL% equ 0": cmd expands %VAR% when
:: it parses the whole parenthesised block, so a nested %ERRORLEVEL% would hold
:: the value from before the block ran, and a machine with pytest but without
:: pytest-cov would still try the coverage run.
python -c "import pytest" >nul 2>&1
if errorlevel 1 (
    echo pytest not installed; using unittest discovery.
    python -m unittest discover -s tests -t . -p "test_*.py" -v
) else (
    echo Using pytest.
    python -c "import pytest_cov" >nul 2>&1
    if errorlevel 1 (
        python -m pytest -q
    ) else (
        python -m pytest -q --cov --cov-report=term
    )
)

if errorlevel 1 (
    echo.
    echo Unit tests FAILED.
    pause
    exit /b 1
)

echo.
echo Unit tests passed successfully.
pause
exit /b 0

:: This script sets up the environment and runs the tests for the Music Player.
:: Make sure to adjust the paths according to your local setup.
:: It checks for the existence of necessary directories and files before
:: proceeding, and exits non-zero if any check or any test fails.
::
:: Note for Windows: several code paths only run here -- the delayed play
:: workaround, the GStreamer priming, hiding the console, and the fallback to
:: the per-user data directory when the install directory is read-only. Those
:: are the parts least covered by tests, so a manual run of the player after
:: this script is still worth doing.
