@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Ambiente Python nao encontrado em .venv\Scripts\python.exe
    echo Execute este arquivo a partir da pasta do projeto Alfred.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m alfred.interfaces.configuracao_voz.app
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo O painel de voz terminou com codigo %EXIT_CODE%.
    pause
)
exit /b %EXIT_CODE%
