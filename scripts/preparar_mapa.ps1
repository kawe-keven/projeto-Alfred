[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [uri] $FontePmtiles,

    [double] $Oeste = -38.245,

    [double] $Sul = -11.575,

    [double] $Leste = -36.394,

    [double] $Norte = -9.515,

    [ValidateRange(0, 30)]
    [int] $ZoomMaximo = 15,

    [Parameter(Mandatory = $true)]
    [ValidateLength(1, 300)]
    [string] $AtribuicaoFonte,

    [switch] $Sobrescrever,

    [switch] $ConfirmacaoAprovada
)

$ErrorActionPreference = 'Stop'

function Get-Sha256Hex([string] $Caminho) {
    $Algoritmo = [Security.Cryptography.SHA256]::Create()
    $Fluxo = [IO.File]::OpenRead($Caminho)
    try {
        return [BitConverter]::ToString($Algoritmo.ComputeHash($Fluxo)).Replace('-', '').ToLowerInvariant()
    } finally {
        $Fluxo.Dispose()
        $Algoritmo.Dispose()
    }
}

$VersaoPmtiles = '1.31.2'
$TagPmtiles = "v$VersaoPmtiles"
$RaizProjeto = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$PastaDestino = Join-Path $RaizProjeto 'dados\mapa'
$ArquivoDestino = Join-Path $PastaDestino 'base.pmtiles'
$ArquivoAtribuicao = Join-Path $PastaDestino 'atribuicao_fonte.txt'

if ($FontePmtiles.Scheme -ne 'https') {
    throw 'A fonte PMTiles precisa usar HTTPS.'
}
if ($FontePmtiles.UserInfo) {
    throw 'Não inclua credenciais na URL da fonte PMTiles.'
}
if (-not ($Oeste -ge -180 -and $Oeste -lt $Leste -and $Leste -le 180)) {
    throw 'A longitude oeste/leste precisa estar em ordem e dentro de -180..180.'
}
if (-not ($Sul -ge -90 -and $Sul -lt $Norte -and $Norte -le 90)) {
    throw 'A latitude sul/norte precisa estar em ordem e dentro de -90..90.'
}
if ($ZoomMaximo -lt 1) {
    throw 'ZoomMaximo precisa ser pelo menos 1.'
}

$Caixa = @(
    $Oeste.ToString('R', [Globalization.CultureInfo]::InvariantCulture),
    $Sul.ToString('R', [Globalization.CultureInfo]::InvariantCulture),
    $Leste.ToString('R', [Globalization.CultureInfo]::InvariantCulture),
    $Norte.ToString('R', [Globalization.CultureInfo]::InvariantCulture)
) -join ','
if ((Test-Path -LiteralPath $ArquivoDestino) -and -not $Sobrescrever) {
    throw 'dados/mapa/base.pmtiles já existe. Revise o arquivo e use -Sobrescrever para substituí-lo explicitamente.'
}
Write-Host 'Preparação do mapa: será necessário acessar a rede para buscar a ferramenta e ler a fonte PMTiles.'
Write-Host "Ferramenta: go-pmtiles $TagPmtiles (release oficial e checksum publicado pelo projeto)."
Write-Host "Fonte pública: $($FontePmtiles.GetLeftPart([System.UriPartial]::Path))"
Write-Host "Recorte solicitado: oeste/sul/leste/norte = $Caixa; zoom máximo = $ZoomMaximo."
Write-Host "Saída local: dados\mapa\base.pmtiles; atribuição: $AtribuicaoFonte"
Write-Host 'O arquivo de origem pode ser grande; a extração solicita somente o recorte e zoom indicados quando a fonte oferece leitura HTTP por intervalos.'
$Confirmacao = if ($ConfirmacaoAprovada) { 'PREPARAR' } else { Read-Host 'Digite PREPARAR para autorizar estes downloads e a criação do arquivo local' }
if ($Confirmacao -cne 'PREPARAR') {
    Write-Host 'Preparação cancelada antes do acesso à rede.'
    exit 0
}

$ApiRelease = "https://api.github.com/repos/protomaps/go-pmtiles/releases/tags/$TagPmtiles"
$Cabecalhos = @{ 'User-Agent' = 'Alfred-Offline-Map-Preparation'; 'Accept' = 'application/vnd.github+json' }
$Release = Invoke-RestMethod -Uri $ApiRelease -Headers $Cabecalhos
$PublicadoEm = [DateTimeOffset]::Parse($Release.published_at)
if ($PublicadoEm -gt [DateTimeOffset]::UtcNow.AddDays(-14)) {
    throw "A release $TagPmtiles tem menos de 14 dias; escolha uma versão antiga e fixe-a após revisão."
}

$AssetZip = @($Release.assets | Where-Object { $_.name -match '^go-pmtiles_.*_Windows_x86_64\.zip$' }) | Select-Object -First 1
if (-not $AssetZip) {
    throw "A release $TagPmtiles não publicou o zip Windows x86_64 esperado. Nenhum executável foi baixado."
}
$DigestPublicacao = [string]$AssetZip.digest
if ($DigestPublicacao -notmatch '^sha256:[0-9a-fA-F]{64}$') {
    throw "A release $TagPmtiles não publicou o zip Windows x86_64 com SHA-256 no GitHub. Nenhum executável foi baixado."
}
if (([uri]$AssetZip.browser_download_url).Host -ne 'github.com') {
    throw 'A URL do arquivo PMTiles não pertence ao domínio oficial esperado.'
}
Write-Host "Download confirmado pelo digest SHA-256 oficial do GitHub: $($AssetZip.name) ($($AssetZip.size) bytes)."

$PastaTemporaria = Join-Path ([IO.Path]::GetTempPath()) ("alfred-pmtiles-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $PastaTemporaria | Out-Null
try {
    $Zip = Join-Path $PastaTemporaria $AssetZip.name
    Invoke-WebRequest -Uri $AssetZip.browser_download_url -Headers $Cabecalhos -OutFile $Zip
    $HashEsperado = $DigestPublicacao.Substring(7).ToLowerInvariant()
    $HashObtido = Get-Sha256Hex $Zip
    if ($HashObtido -ne $HashEsperado) {
        throw 'O SHA-256 do utilitário PMTiles não corresponde ao checksum da release.'
    }

    Expand-Archive -LiteralPath $Zip -DestinationPath $PastaTemporaria
    $Executavel = Get-ChildItem -LiteralPath $PastaTemporaria -Filter 'pmtiles.exe' -File -Recurse | Select-Object -First 1
    if (-not $Executavel) {
        throw 'A release validada não contém pmtiles.exe.'
    }

    New-Item -ItemType Directory -Path $PastaDestino -Force | Out-Null
    $TemporarioDestino = Join-Path $PastaTemporaria 'base.pmtiles'
    & $Executavel.FullName extract $FontePmtiles.AbsoluteUri $TemporarioDestino "--bbox=$Caixa" "--maxzoom=$ZoomMaximo"
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $TemporarioDestino -PathType Leaf)) {
        throw 'A extração PMTiles falhou; confira se a fonte permite leitura HTTP por intervalos.'
    }

    Move-Item -LiteralPath $TemporarioDestino -Destination $ArquivoDestino -Force:$Sobrescrever
    [IO.File]::WriteAllText($ArquivoAtribuicao, $AtribuicaoFonte.Trim() + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
    $Resultado = Get-Item -LiteralPath $ArquivoDestino
    $HashResultado = Get-Sha256Hex $ArquivoDestino
    Write-Host ("Mapa criado: {0:N0} bytes; SHA-256 {1}." -f $Resultado.Length, $HashResultado)
    Write-Host 'A caixa e o centro não foram gravados em um arquivo de log pelo script.'
}
finally {
    Remove-Item -LiteralPath $PastaTemporaria -Recurse -Force -ErrorAction SilentlyContinue
}
