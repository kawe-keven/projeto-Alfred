@echo off
setlocal
cd /d "%~dp0"
set "ALFRED_URL=http://127.0.0.1:8765/#memory"
set "ALFRED_ROOT=%CD%"
set "ALFRED_PYTHON=%CD%\.venv\Scripts\python.exe"

if not exist "%ALFRED_PYTHON%" (
    echo Ambiente Python nao encontrado em .venv\Scripts\python.exe
    echo Instale as dependencias do projeto antes de iniciar o painel.
    pause
    exit /b 1
)

rem Reinicia somente o painel identificado pelo cabecalho AlfredPanel/1.0.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$alfred=$false; try { $r=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8765/api/status' -TimeoutSec 2; $alfred=($r.Headers['Server'] -like 'AlfredPanel/1.0*') } catch { $resp=$_.Exception.Response; $alfred=($resp -and $resp.Headers['Server'] -like 'AlfredPanel/1.0*') }; if ($alfred) { try { Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8765/api/voice/stop' -ContentType 'application/json' -Body '{}' -TimeoutSec 3 | Out-Null } catch {}; $linha=netstat -ano -p tcp | Select-String '127\.0\.0\.1:8765\s+.*LISTENING' | Select-Object -First 1; if ($linha) { $idAlfred=[int](($linha.ToString() -split '\s+')[-1]); $proc=Get-Process -Id $idAlfred -ErrorAction SilentlyContinue; if ($proc -and $proc.ProcessName -in @('python','pythonw')) { Stop-Process -Id $idAlfred -Force -ErrorAction Stop } else { exit 2 } }; for ($i=0; $i -lt 20; $i++) { if (-not (netstat -ano -p tcp | Select-String '127\.0\.0\.1:8765\s+.*LISTENING')) { exit 0 }; Start-Sleep -Milliseconds 500 }; exit 3 }"
if errorlevel 3 (
    echo O Alfred antigo nao encerrou. Feche o painel e tente novamente.
    pause
    exit /b 1
)
if errorlevel 2 (
    echo A porta 8765 pertence a um processo inesperado. O painel nao foi encerrado.
    pause
    exit /b 1
)
if errorlevel 1 (
    echo Nao foi possivel preparar o reinicio do painel Alfred.
    pause
    exit /b 1
)

rem Inicia Ollama, Colibri e VoiceStudio sem bloquear a abertura do painel.
set "ALFRED_DEPENDENCIES_SCRIPT=%~dp0scripts\iniciar_dependencias_locais.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',$env:ALFRED_DEPENDENCIES_SCRIPT) -WindowStyle Hidden -ErrorAction Stop; exit 0 } catch { exit 1 }"
if errorlevel 1 (
    echo Nao foi possivel iniciar as dependencias locais. O Alfred sera aberto mesmo assim.
)

rem Aguarda o modelo Colibri ficar pronto antes de abrir uma nova conversa.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$cfg=Join-Path $env:ALFRED_ROOT 'config.yaml'; $colibri=(Test-Path -LiteralPath $cfg) -and [bool](Select-String -LiteralPath $cfg -Pattern '^\s*provider:\s*colibri\s*$' -Quiet); if (-not $colibri) { exit 0 }; for ($i=0; $i -lt 120; $i++) { try { Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/v1/models' -TimeoutSec 2 | Out-Null; exit 0 } catch { Start-Sleep -Seconds 1 } }; exit 1" >nul 2>&1
if errorlevel 1 echo O Colibri ainda esta carregando. O painel abrira, mas espere o status da IA ficar online.

rem Inicia o servidor Alfred atualizado.
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Start-Process -FilePath $env:ALFRED_PYTHON -ArgumentList @('-m','alfred.interfaces.web.app') -WorkingDirectory $env:ALFRED_ROOT -WindowStyle Hidden -ErrorAction Stop; exit 0 } catch { exit 1 }"
if errorlevel 1 (
    echo Nao foi possivel iniciar o servidor do dashboard Alfred.
    pause
    exit /b 1
)

rem Espera o painel responder antes de abrir o navegador.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$pronto=$false; for ($i=0; $i -lt 30; $i++) { try { $r=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8765/api/status' -TimeoutSec 2; if ($r.Headers['Server'] -like 'AlfredPanel/1.0*') { $pronto=$true; break } } catch { Start-Sleep -Milliseconds 750 } }; if ($pronto) { exit 0 } else { exit 1 }" >nul 2>&1
if errorlevel 1 (
    echo O dashboard Alfred nao respondeu em http://127.0.0.1:8765.
    echo Confira a configuracao e os registros locais do Alfred.
    pause
    exit /b 1
)

start "" "%ALFRED_URL%"
endlocal
