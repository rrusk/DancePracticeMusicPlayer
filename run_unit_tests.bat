:: Set paths for Kivy scripts and music_player.py (adjust as needed).
@echo off
set REPO_LOCATION=%USERPROFILE%\git
set KIVY_PATH=%REPO_LOCATION%\DancePracticeMusicPlayer\kivy_venv\Scripts
set MUSIC_PLAYER_PATH=%REPO_LOCATION%\DancePracticeMusicPlayer

set PATH=%KIVY_PATH%;%MUSIC_PLAYER_PATH%;%PATH%
:: Activate the Kivy virtual environment and run the unit tests.
:: Adjust the paths above if your setup is different.
:: Ensure the paths are correct before running the script.
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
if not exist "%MUSIC_PLAYER_PATH%\test_music_player.py" (
    echo Test script not found: %MUSIC_PLAYER_PATH%\test_music_player.py
    exit /b 1
)
echo Activating Kivy virtual environment and running tests...
:: Change to the Kivy virtual environment directory and activate it.
:: Then change to the Music Player directory and run the tests.
:: Use 'call' to ensure the script continues after activation.
cd /d %KIVY_PATH%
call activate
cd /d %MUSIC_PLAYER_PATH%
python -m unittest test_music_player.py
if %ERRORLEVEL% neq 0 (
    echo Unit tests failed.
    exit /b %ERRORLEVEL%
) else (
    echo Unit tests passed successfully.
)
exit /b 0
:: End of script
echo Done.
pause
:: This script sets up the environment and runs unit tests for the Music Player.
:: Make sure to adjust the paths according to your local setup.
:: It checks for the existence of necessary directories and files before proceeding.
:: If any checks fail, it will output an error message and exit with a non-zero status.
:: If the tests pass, it will output a success message and exit with a zero status.
:: The script ends with a pause to allow the user to see the output before closing.
:: This script is intended to be run in a Windows environment.
:: Ensure you have Python and Kivy installed in the specified virtual environment.
:: The script assumes that the Kivy virtual environment is set up correctly.
:: Adjust the script as necessary for your specific project structure and requirements.
:: The script is designed to be run from the command line.
:: It will not work if run directly from a text editor or IDE without command line support. 

