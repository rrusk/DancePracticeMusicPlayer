:: Set paths for Kivy scripts and music_player.py (adjust as needed).
@echo off
set REPO_LOCATION=%USERPROFILE%\git
set KIVY_PATH=%REPO_LOCATION%\DancePracticeMusicPlayer\kivy_venv\Scripts
set MUSIC_PLAYER_PATH=%REPO_LOCATION%\DancePracticeMusicPlayer

set PATH=%KIVY_PATH%;%MUSIC_PLAYER_PATH%;%PATH%

:: To Add to Desktop
:: If you save the .bat file on the Desktop, it's already accessible.
:: If you want to add it as a shortcut:
::    Right-click the .bat file and select Send to -> Desktop (create shortcut).
::    Optionally, you can change the icon by right-clicking the shortcut,
:     selecting Properties, and then choosing a different icon under the Shortcut tab.
:: Now, you can run your Kivy application by simply double-clicking the .bat file on your desktop!

cd /d %KIVY_PATH%
call activate
cd /d %MUSIC_PLAYER_PATH%
python music_player.py
:: pause shows startup errors if they occur
:: pause
