param(
    [string]$Modelo = '',
    [string]$ModeloPortugues = ''
)
$ErrorActionPreference = 'Stop'
$ollieRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not $Modelo) { $Modelo = Join-Path $ollieRoot '.artifacts\wakeword\treino-ouh-lee\hey_ollie.onnx' }
& (Join-Path $PSScriptRoot 'preparar.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Falha ao preparar ambiente local de voz.' }
$ollieArguments = @((Join-Path $PSScriptRoot 'preparar_desktop.py'), '--model', $Modelo)
if ($ModeloPortugues) { $ollieArguments += @('--speech-model', $ModeloPortugues) }
& (Join-Path $ollieRoot '.artifacts\wakeword\venv\Scripts\python.exe') @ollieArguments
if ($LASTEXITCODE -ne 0) { throw 'Falha ao preparar modelos da voz do PC.' }
Write-Host 'Modelos prontos. No app de PC, clique em Ativar Ei Ollie.'
