@echo off
setlocal enabledelayedexpansion

:: ============================================================
::
::   ___  _  ___  ____  ____ ___
::  / _ \/ |/ __\/ __ \/ __// _ \
:: / _  /  / /   / ___/\__ \/ // /
:: \___/_/\_\   \____//____/\___/
::
::  run_alfred.bat  v1.0
::  Inicializador do Alfred AI Assistant para Windows
::
::  Uso: Duplo clique ou adicione em shell:startup
:: ============================================================

title Alfred AI — Inicializando...
color 0A

:: ------------------------------------------------------------
:: Variaveis de caminho (tudo relativo a este .bat)
:: ------------------------------------------------------------
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

set "LOG_DIR=%ROOT%\logs"
set "BACK_LOG=%LOG_DIR%\backend.log"
set "FRONT_LOG=%LOG_DIR%\frontend.log"
set "BOOT_LOG=%LOG_DIR%\boot.log"
set "CHROMA_DB=%ROOT%\memory\vector_db"
set "VENV_ACTIVATE="

:: Cria pasta de logs se nao existir
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

:: Registra inicio de boot
echo. >> "%BOOT_LOG%"
echo ===================================================== >> "%BOOT_LOG%"
echo  Alfred iniciando em %date% as %time% >> "%BOOT_LOG%"
echo ===================================================== >> "%BOOT_LOG%"

:: Header visual
echo.
echo  =============================================
echo    ALFRED AI  ^|  Sistema de Inicializacao
echo    %date%  ^|  %time%
echo  =============================================
echo.


:: ============================================================
:: [1/5]  BANCO VETORIAL CHROMADB
::        Verifica se DB existente sera reaproveitado,
::        evitando recriacao e economia de RAM no boot.
:: ============================================================
echo  [1/5] Banco vetorial ChromaDB...

if exist "%CHROMA_DB%\chroma.sqlite3" (
    for %%F in ("%CHROMA_DB%\chroma.sqlite3") do set "DB_SIZE=%%~zF"
    echo         OK ^| Dados existentes encontrados ^(!DB_SIZE! bytes^)
    echo         Memoria de longo prazo sera CARREGADA, nao recriada.
    echo  [1/5] OK - ChromaDB: carregando dados existentes >> "%BOOT_LOG%"
) else (
    echo         INFO ^| Banco ainda nao existe.
    echo         Sera criado automaticamente na 1a execucao ^(normal^).
    echo  [1/5] INFO - ChromaDB: primeiro boot, banco sera criado >> "%BOOT_LOG%"
)
echo.


:: ============================================================
:: [2/5]  AMBIENTE VIRTUAL PYTHON
:: ============================================================
echo  [2/5] Ambiente virtual Python...

if exist "%ROOT%\.venv\Scripts\activate.bat" (
    set "VENV_ACTIVATE=%ROOT%\.venv\Scripts\activate.bat"
    echo         OK ^| Encontrado em .venv
    echo  [2/5] OK - venv: .venv >> "%BOOT_LOG%"
) else if exist "%ROOT%\venv\Scripts\activate.bat" (
    set "VENV_ACTIVATE=%ROOT%\venv\Scripts\activate.bat"
    echo         OK ^| Encontrado em venv
    echo  [2/5] OK - venv: venv >> "%BOOT_LOG%"
) else (
    echo.
    echo  ============================================
    echo   [ERRO] Ambiente virtual nao encontrado!
    echo  ============================================
    echo.
    echo  Crie o ambiente virtual executando:
    echo.
    echo    cd "%ROOT%"
    echo    python -m venv .venv
    echo    .venv\Scripts\activate
    echo    pip install -r requirements.txt
    echo.
    echo  [2/5] ERRO - venv nao encontrado >> "%BOOT_LOG%"
    echo  Boot abortado — venv ausente. >> "%BOOT_LOG%"
    pause
    exit /b 1
)

call "%VENV_ACTIVATE%"

:: Verifica dependencias criticas
python -c "import uvicorn, fastapi, chromadb" >nul 2>&1
if errorlevel 1 (
    echo         AVISO ^| Dependencias ausentes. Instalando...
    echo  [2/5] AVISO - instalando requirements.txt >> "%BOOT_LOG%"
    pip install -r "%ROOT%\requirements.txt" >> "%BACK_LOG%" 2>&1
    if errorlevel 1 (
        echo  [ERRO] Falha ao instalar dependencias Python.
        echo  Verifique: %BACK_LOG%
        echo  [2/5] ERRO - pip install falhou >> "%BOOT_LOG%"
        pause
        exit /b 1
    )
    echo         OK ^| Dependencias instaladas com sucesso.
)
echo.


:: ============================================================
:: [3/5]  BACKEND FASTAPI  (porta 8000)
:: ============================================================
echo  [3/5] Backend FastAPI (porta 8000)...

:: Cabecalho no log do backend
echo. >> "%BACK_LOG%"
echo ===================================================== >> "%BACK_LOG%"
echo  Backend iniciando — %date% %time% >> "%BACK_LOG%"
echo ===================================================== >> "%BACK_LOG%"

:: Cria script temporario para rodar backend com captura de log.
:: Tecnica necessaria para redirecionar saida de processo em background
:: sem problemas de aspas aninhadas no Windows CMD.
echo @echo off                                    > "%TEMP%\alfred_backend.bat"
echo cd /d "%ROOT%"                              >> "%TEMP%\alfred_backend.bat"
echo call "%VENV_ACTIVATE%"                      >> "%TEMP%\alfred_backend.bat"
echo uvicorn main:app --host 0.0.0.0 --port 8000 --log-level info ^>^> "%BACK_LOG%" 2^>^&1 >> "%TEMP%\alfred_backend.bat"

start "Alfred-Backend" /min "%TEMP%\alfred_backend.bat"

echo         Processo iniciado em background ^(janela minimizada^).
echo         Logs salvos em: logs\backend.log
echo  [3/5] OK - Backend iniciado >> "%BOOT_LOG%"

echo         Aguardando inicializacao ^(14s — carregando modelos de embeddings^)...
timeout /t 14 /nobreak > nul

:: Testa se o backend ja respondeu
curl -sf http://localhost:8000/health > nul 2>&1
if errorlevel 1 (
    echo         AVISO ^| Backend ainda inicializando. Aguardando mais 10s...
    timeout /t 10 /nobreak > nul
    curl -sf http://localhost:8000/health > nul 2>&1
    if errorlevel 1 (
        echo         ERRO ^| Backend nao respondeu. Verifique: logs\backend.log
        echo  [3/5] ERRO - health check falhou >> "%BOOT_LOG%"
    ) else (
        echo         OK ^| Backend respondendo em http://localhost:8000
        echo  [3/5] OK - health check passou ^(2a tentativa^) >> "%BOOT_LOG%"
    )
) else (
    echo         OK ^| Backend respondendo em http://localhost:8000
    echo  [3/5] OK - health check passou >> "%BOOT_LOG%"
)
echo.


:: ============================================================
:: [4/5]  FRONTEND VITE  (porta 3000)
:: ============================================================
echo  [4/5] Frontend Vite (porta 3000)...

:: Instala node_modules se necessario
if not exist "%ROOT%\frontend\node_modules" (
    echo         INFO ^| node_modules ausente — executando npm install...
    echo  [4/5] INFO - npm install necessario >> "%BOOT_LOG%"
    cd /d "%ROOT%\frontend"
    npm install >> "%FRONT_LOG%" 2>&1
    if errorlevel 1 (
        echo  [ERRO] Falha no npm install. Verifique: %FRONT_LOG%
        echo  [4/5] ERRO - npm install falhou >> "%BOOT_LOG%"
        pause
        exit /b 1
    )
    echo         OK ^| Dependencias Node instaladas.
)

:: Cabecalho no log do frontend
echo. >> "%FRONT_LOG%"
echo ===================================================== >> "%FRONT_LOG%"
echo  Frontend iniciando — %date% %time% >> "%FRONT_LOG%"
echo ===================================================== >> "%FRONT_LOG%"

:: Detecta Node.js para garantir que npm esteja no PATH do frontend
set "NODE_PATH="
if exist "C:\Program Files\nodejs\npm.cmd"       set "NODE_PATH=C:\Program Files\nodejs"
if exist "C:\Program Files (x86)\nodejs\npm.cmd" set "NODE_PATH=C:\Program Files (x86)\nodejs"
if "%NODE_PATH%"=="" (
    for /f "delims=" %%i in ('where npm 2^>nul') do set "NODE_PATH=%%~dpi"
)
if "%NODE_PATH%"=="" (
    echo         ERRO ^| Node.js nao encontrado no sistema!
    echo         Instale em: https://nodejs.org
    echo  [4/5] ERRO - Node.js ausente >> "%BOOT_LOG%"
    pause
    exit /b 1
)
echo         OK ^| Node.js encontrado em: %NODE_PATH%

:: Script temporario para o frontend
echo @echo off                                            > "%TEMP%\alfred_frontend.bat"
echo set "PATH=%NODE_PATH%;%%PATH%%"                     >> "%TEMP%\alfred_frontend.bat"
echo cd /d "%ROOT%\frontend"                            >> "%TEMP%\alfred_frontend.bat"
echo npm run dev ^>^> "%FRONT_LOG%" 2^>^&1              >> "%TEMP%\alfred_frontend.bat"

start "Alfred-Frontend" /min "%TEMP%\alfred_frontend.bat"

echo         Processo iniciado em background ^(janela minimizada^).
echo         Logs salvos em: logs\frontend.log
echo  [4/5] OK - Frontend iniciado >> "%BOOT_LOG%"

echo         Aguardando frontend ^(6s^)...
timeout /t 6 /nobreak > nul
echo.


:: ============================================================
:: [5/5]  ABRE O NAVEGADOR
:: ============================================================
echo  [5/5] Abrindo Alfred no navegador...
timeout /t 4 /nobreak > nul
start "" "http://localhost:3000"
echo         OK ^| http://localhost:3000 aberto.
echo  [5/5] OK - navegador aberto >> "%BOOT_LOG%"
echo.


:: ============================================================
::  CONCLUSAO
:: ============================================================
echo  =============================================
echo   Alfred esta operacional. Bom dia, senhor.
echo  =============================================
echo.
echo   Backend:   http://localhost:8000
echo   Frontend:  http://localhost:3000
echo   API Docs:  http://localhost:8000/docs
echo.
echo   Logs de debug:
echo     Boot:      logs\boot.log
echo     Backend:   logs\backend.log
echo     Frontend:  logs\frontend.log
echo.
echo  Boot concluido com sucesso. >> "%BOOT_LOG%"
echo  =============================================
echo.
echo  Este terminal pode ser fechado com seguranca.
echo  Os servicos continuarao rodando em background.
echo.

timeout /t 8 /nobreak > nul

endlocal
exit /b 0
