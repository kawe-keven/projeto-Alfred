$ErrorActionPreference = 'Continue'

function Test-LocalService([string] $Url) {
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2 | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Start-InstalledApp([string] $AppName, [string[]] $ExecutableCandidates = @()) {
    foreach ($candidate in $ExecutableCandidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            try {
                Start-Process -FilePath $candidate
                Write-Host "$AppName iniciado."
                return $true
            } catch {
                Write-Host "Nao foi possivel iniciar $AppName pelo executavel instalado."
            }
        }
    }

    $startMenuFolders = @(
        [Environment]::GetFolderPath('StartMenu'),
        [Environment]::GetFolderPath('CommonStartMenu')
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -Unique

    $shortcut = Get-ChildItem -Path $startMenuFolders -Filter '*.lnk' -File -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.BaseName -match $AppName } |
        Select-Object -First 1

    if (-not $shortcut) {
        Write-Host "Atalho do $AppName nao encontrado no Menu Iniciar."
        return $false
    }

    try {
        # Muitos instaladores registram links de aplicativos do Windows sem TargetPath;
        # o Explorer resolve esses atalhos corretamente.
        Start-Process -FilePath "$env:WINDIR\explorer.exe" -ArgumentList ('"' + $shortcut.FullName + '"')
        Write-Host "$AppName iniciado pelo Menu Iniciar."
        return $true
    } catch {
        Write-Host "Nao foi possivel iniciar $AppName pelo atalho encontrado."
        return $false
    }
}

if (-not (Test-LocalService 'http://127.0.0.1:11434/api/tags')) {
    $ollamaCandidates = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama app.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'),
        (Join-Path $env:APPDATA 'ollama app.exe\ollama app.exe'),
        (Join-Path $env:APPDATA 'ollama app.exe\Ollama.exe')
    )
    [void](Start-InstalledApp 'Ollama' $ollamaCandidates)
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Seconds 2
        if (Test-LocalService 'http://127.0.0.1:11434/api/tags') { $ready = $true; break }
    }
    if (-not $ready) { Write-Host 'Ollama ainda nao respondeu em 127.0.0.1:11434; o Alfred sera aberto mesmo assim.' }
} else {
    Write-Host 'Ollama ja esta ativo.'
}

$configAlfred = Join-Path $PSScriptRoot '..\config.yaml'
$usaColibri = (Test-Path -LiteralPath $configAlfred) -and
    [bool](Select-String -LiteralPath $configAlfred -Pattern '^\s*provider:\s*colibri\s*$' -Quiet)
if ($usaColibri) {
    $colibriRoot = Join-Path $PSScriptRoot '..\..\colibri'
    $colibriCli = Join-Path $colibriRoot 'c\coli'
    $colibriSetup = Join-Path $env:LOCALAPPDATA 'colibri\setup.json'
    if ((Test-Path -LiteralPath $colibriCli -PathType Leaf) -and
        (Test-Path -LiteralPath $colibriSetup -PathType Leaf) -and
        -not (Test-LocalService 'http://127.0.0.1:8000/v1/models')) {
        try {
            Push-Location $colibriRoot
            & py -3 $colibriCli start --background --no-browser | Out-Null
            Pop-Location
            $ready = $false
            for ($attempt = 0; $attempt -lt 60; $attempt++) {
                Start-Sleep -Seconds 2
                if (Test-LocalService 'http://127.0.0.1:8000/v1/models') {
                    $ready = $true
                    break
                }
            }
            if (-not $ready) { Write-Host 'Colibri ainda nao respondeu em 127.0.0.1:8000.' }
        } catch {
            if ((Get-Location).Path -eq $colibriRoot) { Pop-Location }
            Write-Host 'Nao foi possivel iniciar o Colibri.'
        }
    }
}

if (-not (Test-LocalService 'http://127.0.0.1:3900/health')) {
    $voiceStudioCandidates = @(
        (Join-Path $env:ProgramFiles 'VoiceStudio\VoiceStudio.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\VoiceStudio\VoiceStudio.exe')
    )
    [void](Start-InstalledApp 'VoiceStudio|Voice Studio' $voiceStudioCandidates)
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Seconds 2
        if (Test-LocalService 'http://127.0.0.1:3900/health') { $ready = $true; break }
    }
    if (-not $ready) { Write-Host 'VoiceStudio ainda nao respondeu em 127.0.0.1:3900; confira se o aplicativo terminou de iniciar.' }
} else {
    Write-Host 'VoiceStudio ja esta ativo.'
}
