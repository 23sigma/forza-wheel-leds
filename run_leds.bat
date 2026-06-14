@echo off
setlocal

:: --- Configuration ---
:: The absolute path to your Python project directory
set "PROJECT_DIR=C:\Users\charl\OneDrive\Documents\Python\forza-wheel-leds"

:: The absolute path to your Python executable
set "PYTHON_EXE=C:\Users\charl\AppData\Local\Programs\Python\Python311\python.exe"
:: ---------------------

echo Launching Forza Wheel LEDs...
echo.

:: Change directory to the project folder so it can find config.ini and hidapi.dll
cd /d "%PROJECT_DIR%"

:: Run the script
"%PYTHON_EXE%" forza_wheel_leds.py

:: If the script crashes, keep the window open so you can see the error
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] The script exited with code %ERRORLEVEL%
    pause
)

endlocal
