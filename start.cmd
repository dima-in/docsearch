@echo off
rem Запуск поиска по архиву. Можно просто дважды щёлкнуть по этому файлу.
rem Конфиг меняется переменной DOCSEARCH_CONFIG.
setlocal
cd /d "%~dp0"
if "%DOCSEARCH_CONFIG%"=="" set DOCSEARCH_CONFIG=config.server.yaml
if not exist "%DOCSEARCH_CONFIG%" (
    echo Нет файла %DOCSEARCH_CONFIG% — создайте его командой docsearch init
    pause
    exit /b 1
)
".venv\Scripts\docsearch.exe" -c "%DOCSEARCH_CONFIG%" serve --port 8000
rem Окно не закрываем: если приложение упало, надо увидеть причину
pause
endlocal
