param(
    [Parameter(Mandatory=$true)][string]$Modelo,
    [ValidateRange(0.001,1.0)][double]$Limiar = 0.5,
    [int]$Dispositivo = -1
)
$ErrorActionPreference = 'Stop'
$ollieRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$olliePython = Join-Path $ollieRoot '.artifacts\wakeword\venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $olliePython)) { throw 'Execute tools\wakeword\preparar.ps1 primeiro.' }
$ollieArguments = @((Join-Path $PSScriptRoot 'testar.py'), 'ouvir', '--modelo', $Modelo,
    '--limiar', $Limiar.ToString([System.Globalization.CultureInfo]::InvariantCulture))
if ($Dispositivo -ge 0) { $ollieArguments += @('--dispositivo', $Dispositivo) }
& $olliePython @ollieArguments
exit $LASTEXITCODE
