@echo off
setlocal
:: Run from the checkout containing this script, wherever it is located.
set "MUSIC_PLAYER_PATH=%~dp0"
set "KIVY_PATH=%MUSIC_PLAYER_PATH%kivy_venv\Scripts"

set "PATH=%KIVY_PATH%;%MUSIC_PLAYER_PATH%;%PATH%"

:: To add it to the Desktop, create a shortcut rather than copying this file:
::    Right-click the .bat file and select Send to -> Desktop (create shortcut).
::    Optionally, you can change the icon by right-clicking the shortcut,
:     selecting Properties, and then choosing a different icon under the Shortcut tab.
:: Now, you can run your Kivy application by simply double-clicking the .bat file on your desktop!

cd /d "%KIVY_PATH%"
call activate
cd /d "%MUSIC_PLAYER_PATH%"
python music_player.py
:: pause shows startup errors if they occur
:: pause
