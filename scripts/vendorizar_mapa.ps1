[CmdletBinding()]
param([switch] $ConfirmacaoAprovada)

$ErrorActionPreference = 'Stop'

function Get-HashHex([string] $Caminho, [string] $NomeAlgoritmo) {
    $Algoritmo = [Security.Cryptography.HashAlgorithm]::Create($NomeAlgoritmo)
    $Fluxo = [IO.File]::OpenRead($Caminho)
    try {
        return [BitConverter]::ToString($Algoritmo.ComputeHash($Fluxo)).Replace('-', '').ToLowerInvariant()
    } finally {
        $Fluxo.Dispose()
        $Algoritmo.Dispose()
    }
}

function Get-Sha512Base64([string] $Caminho) {
    $Algoritmo = [Security.Cryptography.SHA512]::Create()
    $Fluxo = [IO.File]::OpenRead($Caminho)
    try {
        return [Convert]::ToBase64String($Algoritmo.ComputeHash($Fluxo))
    } finally {
        $Fluxo.Dispose()
        $Algoritmo.Dispose()
    }
}

$VersaoMapLibre = '5.6.0'
$RaizProjeto = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$PastaVendor = Join-Path $RaizProjeto 'ui\vendor\maplibre-gl'
$PastaTemporaria = Join-Path ([IO.Path]::GetTempPath()) ("alfred-maplibre-" + [guid]::NewGuid().ToString('N'))
$Registro = 'https://registry.npmjs.org/maplibre-gl'
$NomesArquivos = @('maplibre-gl.js', 'maplibre-gl.css', 'maplibre-gl-csp-worker.js', 'LICENSE.txt')

Write-Host "Este script acessará o registro oficial npm para maplibre-gl@$VersaoMapLibre."
Write-Host 'Serão extraídos somente os arquivos de runtime JavaScript, CSS, worker CSP e licença; nenhum pacote será instalado.'
$Confirmacao = if ($ConfirmacaoAprovada) { 'VENDORIZAR' } else { Read-Host 'Digite VENDORIZAR para autorizar o download do tarball npm' }
if ($Confirmacao -cne 'VENDORIZAR') {
    Write-Host 'Vendorização cancelada antes do acesso à rede.'
    exit 0
}

New-Item -ItemType Directory -Path $PastaTemporaria | Out-Null
try {
    $Metadados = Invoke-RestMethod -Uri $Registro
    $Versao = $Metadados.versions.$VersaoMapLibre
    if (-not $Versao -or -not $Versao.dist.tarball -or -not $Versao.dist.integrity) {
        throw "O registro npm não retornou tarball e integridade para maplibre-gl@$VersaoMapLibre."
    }
    if (([uri]$Versao.dist.tarball).Scheme -ne 'https' -or ([uri]$Versao.dist.tarball).Host -ne 'registry.npmjs.org') {
        throw 'A URL do tarball não pertence ao registro oficial npm.'
    }
    $PublicadoEm = [DateTimeOffset]::Parse($Metadados.time.$VersaoMapLibre)
    if ($PublicadoEm -gt [DateTimeOffset]::UtcNow.AddDays(-14)) {
        throw "maplibre-gl@$VersaoMapLibre tem menos de 14 dias; nenhuma dependência foi vendorizada."
    }

    $Tarball = Join-Path $PastaTemporaria 'maplibre-gl.tgz'
    Invoke-WebRequest -Uri $Versao.dist.tarball -OutFile $Tarball
    $Integridade = [string]$Versao.dist.integrity
    if ($Integridade -notmatch '^sha512-(.+)$') {
        throw 'O registro npm não forneceu uma integridade SHA-512 compatível.'
    }
    $Sha512Esperado = $Matches[1]
    $Sha512Obtido = Get-Sha512Base64 $Tarball
    if ($Sha512Obtido -cne $Sha512Esperado) {
        throw 'A integridade SHA-512 do tarball não corresponde ao registro npm.'
    }

    $PastaExtraida = Join-Path $PastaTemporaria 'extraido'
    New-Item -ItemType Directory -Path $PastaExtraida | Out-Null
    & tar -xzf $Tarball -C $PastaExtraida package/dist/maplibre-gl.js package/dist/maplibre-gl.css package/dist/maplibre-gl-csp-worker.js package/LICENSE.txt
    if ($LASTEXITCODE -ne 0) {
        throw 'Não foi possível extrair os arquivos selecionados do tarball.'
    }
    foreach ($Nome in $NomesArquivos) {
        $CaminhoNoPacote = if ($Nome -eq 'LICENSE.txt') {
            Join-Path $PastaExtraida 'package\LICENSE.txt'
        } else {
            Join-Path (Join-Path $PastaExtraida 'package\dist') $Nome
        }
        $Arquivo = $CaminhoNoPacote
        if (-not (Test-Path -LiteralPath $Arquivo -PathType Leaf)) {
            throw "O tarball não contém o arquivo esperado: $Nome"
        }
    }

    New-Item -ItemType Directory -Path $PastaVendor -Force | Out-Null
    $HashesArquivos = @{}
    foreach ($Nome in $NomesArquivos) {
        $Destino = Join-Path $PastaVendor $Nome
        $CaminhoNoPacote = if ($Nome -eq 'LICENSE.txt') {
            Join-Path $PastaExtraida 'package\LICENSE.txt'
        } else {
            Join-Path (Join-Path $PastaExtraida 'package\dist') $Nome
        }
        Copy-Item -LiteralPath $CaminhoNoPacote -Destination $Destino -Force
        $HashesArquivos[$Nome] = Get-HashHex $Destino 'SHA256'
    }
    $Manifesto = [ordered]@{
        pacote = 'maplibre-gl'
        versao = $VersaoMapLibre
        publicado_em = $PublicadoEm.ToString('yyyy-MM-ddTHH:mm:ssZ')
        origem_tarball = $Versao.dist.tarball
        integridade_registro = $Integridade
        sha256_tarball = Get-HashHex $Tarball 'SHA256'
        arquivos_sha256 = $HashesArquivos
    }
    $ManifestoPath = Join-Path $PastaVendor 'manifesto.json'
    [IO.File]::WriteAllText($ManifestoPath, (($Manifesto | ConvertTo-Json -Depth 5) + [Environment]::NewLine), [Text.UTF8Encoding]::new($false))
    Write-Host "Vendorização concluída para maplibre-gl@$VersaoMapLibre."
    Write-Host "Integridade npm verificada: $Integridade"
    Write-Host "Manifesto SHA-256: ui/vendor/maplibre-gl/manifesto.json"
}
finally {
    Remove-Item -LiteralPath $PastaTemporaria -Recurse -Force -ErrorAction SilentlyContinue
}
