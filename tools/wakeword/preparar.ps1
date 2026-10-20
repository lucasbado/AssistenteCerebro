$ErrorActionPreference = 'Stop'
$ollieRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$ollieEnv = Join-Path $ollieRoot '.artifacts\wakeword\venv'
$olliePython = Join-Path $ollieEnv 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $olliePython)) {
    & (Join-Path $ollieRoot '.venvs\Scripts\python.exe') -m venv $ollieEnv
    if ($LASTEXITCODE -ne 0) { throw 'Nao consegui criar o ambiente de teste.' }
}
& $olliePython -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Falha ao instalar dependencias de avaliacao.' }
& $olliePython -m pip install --no-deps openwakeword==0.6.0
if ($LASTEXITCODE -ne 0) { throw 'Falha ao instalar openWakeWord.' }
& $olliePython (Join-Path $PSScriptRoot 'testar.py') preparar
if ($LASTEXITCODE -ne 0) { throw 'Falha ao preparar os modelos compartilhados.' }
& $olliePython -m pip freeze | Set-Content -LiteralPath (Join-Path $ollieRoot '.artifacts\wakeword\pacotes-instalados.txt') -Encoding UTF8
Write-Host 'Pronto. O modelo Hey Ollie ainda precisa ser treinado no Colab.'
