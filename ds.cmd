@echo off
rem Короткий вызов поиска из любой папки: ds "запрос" или просто ds
rem Конфиг можно переопределить переменной DOCSEARCH_CONFIG
setlocal
if "%DOCSEARCH_CONFIG%"=="" set DOCSEARCH_CONFIG=config.server.yaml
if "%~1"=="" (
    "%~dp0.venv\Scripts\docsearch.exe" -c "%~dp0%DOCSEARCH_CONFIG%" shell
) else (
    "%~dp0.venv\Scripts\docsearch.exe" -c "%~dp0%DOCSEARCH_CONFIG%" search %*
)
endlocal
