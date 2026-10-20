param([switch]$Instalar)
$ErrorActionPreference = 'Stop'
$ollieBackend = Split-Path -Parent $PSScriptRoot
$ollieAndroid = 'D:\Programacao\Projetos\AssistenteCell'
$olliePython = Join-Path $ollieBackend '.venvs\Scripts\python.exe'
$env:JAVA_HOME = 'C:\Program Files\Android\Android Studio\jbr'
$env:Path = "$env:JAVA_HOME\bin;$env:Path"
Push-Location -LiteralPath $ollieBackend
try {
    & $olliePython 'scripts\preparar_revisao_android.py' apply
    if ($LASTEXITCODE -ne 0) { throw 'O Android mudou. Revise antes de aplicar os arquivos.' }
    & $olliePython 'scripts\verificar_revisao_android.py'
    if ($LASTEXITCODE -ne 0) { throw 'Recursos ou vocabulario invalidos.' }
    & (Join-Path $ollieAndroid 'gradlew.bat') -p $ollieAndroid --offline :app:testDebugUnitTest :app:assembleDebug :app:assembleDebugAndroidTest --console=plain --no-configuration-cache '-Dorg.gradle.java.installations.paths=C:\Users\lucba\.gradle\jdks\eclipse_adoptium-17-amd64-windows.2'
    if ($LASTEXITCODE -ne 0) { throw 'A compilacao ou os testes falharam. Nenhum APK foi instalado.' }
    if ($Instalar) {
        $ollieAdb = Join-Path $env:LOCALAPPDATA 'Android\Sdk\platform-tools\adb.exe'
        $ollieDevices = @(& $ollieAdb devices | Select-String '\sdevice$')
        if ($ollieDevices.Count -ne 1) { throw 'Deixe exatamente um celular conectado e autorizado.' }
        & $ollieAdb install -r (Join-Path $ollieAndroid 'app\build\outputs\apk\debug\app-debug.apk')
        if ($LASTEXITCODE -ne 0) { throw 'Falha na instalacao do APK.' }
        & $ollieAdb shell am start -n com.example.assistentecell/.MainActivity
    }
} finally { Pop-Location }
