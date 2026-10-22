param(
    [switch]$Onefile,
    [switch]$SkipTests,
    [switch]$SkipArtifactTests
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$pythonExe = "py"
$pythonArgs = @("-3.12")
if ($env:GM_PYTHON) {
    $pythonExe = $env:GM_PYTHON
    $pythonArgs = @()
}

$version = (& $pythonExe @pythonArgs scripts\check_version.py).Trim()
if (-not $version) { throw "Versionsnummer konnte nicht gelesen werden." }
Write-Host "Version: $version"

if (-not $SkipTests) {
    & $pythonExe @pythonArgs -m unittest discover -s tests
    if ($LASTEXITCODE -ne 0) { throw "Tests fehlgeschlagen." }
}

if (Test-Path dist) { Remove-Item dist -Recurse -Force }
New-Item -ItemType Directory -Force -Path dist | Out-Null

if ($Onefile) { $env:GM_ONEFILE = "1" } else { Remove-Item Env:GM_ONEFILE -ErrorAction SilentlyContinue }

& $pythonExe @pythonArgs -m PyInstaller --noconfirm --clean --distpath dist --workpath build\pyinstaller build\GaubenMaster2.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller fehlgeschlagen." }

if ($Onefile) {
    $exe = Join-Path $root "dist\GaubenMaster2.exe"
    $appDir = $null
} else {
    $appDir = Join-Path $root "dist\GaubenMaster2"
    $exe = Join-Path $appDir "GaubenMaster2.exe"
}
if (-not (Test-Path $exe)) { throw "EXE wurde nicht erzeugt." }

$probeFile = Join-Path $env:TEMP "gm2-probe-$PID.json"
$versionFile = Join-Path $env:TEMP "gm2-version-$PID.json"
$versionProcess = Start-Process -FilePath $exe -ArgumentList @("--version-out", $versionFile) -PassThru -Wait
if ($versionProcess.ExitCode -ne 0 -or -not (Test-Path $versionFile)) {
    throw "Versionsabfrage der EXE fehlgeschlagen (Exitcode $($versionProcess.ExitCode))."
}
$exeVersion = (Get-Content $versionFile -Raw | ConvertFrom-Json).version
if ($exeVersion -ne $version) { throw "EXE-Version $exeVersion passt nicht zu $version." }
$probeProcess = Start-Process -FilePath $exe -ArgumentList @("--probe-out", $probeFile) -PassThru -Wait
if ($probeProcess.ExitCode -ne 0 -or -not (Test-Path $probeFile)) {
    throw "Startprobe der EXE fehlgeschlagen (Exitcode $($probeProcess.ExitCode))."
}
$startupMs = (Get-Content $probeFile -Raw | ConvertFrom-Json).startup_ms
Remove-Item $probeFile, $versionFile -Force -ErrorAction SilentlyContinue

$exeBytes = (Get-Item $exe).Length
$appBytes = if ($appDir) {
    (Get-ChildItem $appDir -Recurse -File | Measure-Object Length -Sum).Sum
} else {
    $exeBytes
}
Write-Host ("EXE: {0:N2} MB, Startzeit: {1:N0} ms" -f ($exeBytes / 1MB), $startupMs)
if ($appDir) { Write-Host ("App-Ordner: {0:N2} MB" -f ($appBytes / 1MB)) }

$installerBytes = 0
$installer = $null
if (-not $Onefile) {
    $wix = $env:WIX
    if (-not $wix) {
        $candidate = Join-Path $env:USERPROFILE ".dotnet\tools\wix.exe"
        if (Test-Path $candidate) { $wix = $candidate }
    }
    if (-not $wix) {
        $command = Get-Command wix.exe -ErrorAction SilentlyContinue
        if ($command) { $wix = $command.Source }
    }
    if (-not $wix) {
        throw "wix.exe nicht gefunden (WiX 6 installieren oder WIX setzen)."
    }

    $installer = Join-Path $root "dist\GaubenMaster2-Setup-$version.msi"
    $wixArgs = @(
        "build", "installer\GaubenMaster2.wxs",
        "-arch", "x64",
        "-ext", "WixToolset.Util.wixext",
        "-d", "AppDir=$appDir",
        "-d", "Version=$version",
        "-d", "IconPath=$root\assets\icon.ico",
        "-o", $installer
    )
    & $wix @wixArgs
    if ($LASTEXITCODE -ne 0) { throw "WiX-Installer fehlgeschlagen." }

    if (-not (Test-Path $installer)) { throw "Installer wurde nicht erzeugt." }
    $installerBytes = (Get-Item $installer).Length
    $hash = (Get-FileHash -Algorithm SHA256 $installer).Hash.ToLowerInvariant()
    "$hash  $(Split-Path $installer -Leaf)" | Set-Content -Encoding ascii (Join-Path $root "dist\SHA256SUMS.txt")
    Write-Host ("MSI: {0:N2} MB, SHA256 {1}" -f ($installerBytes / 1MB), $hash)
}

$metrics = [ordered]@{
    version = $version
    built_at = (Get-Date).ToUniversalTime().ToString("o")
    onefile = [bool]$Onefile
    exe_bytes = $exeBytes
    app_dir_bytes = $appBytes
    installer_bytes = $installerBytes
    startup_ms = $startupMs
    sha256 = if ($installer) { (Get-FileHash -Algorithm SHA256 $installer).Hash.ToLowerInvariant() } else { $null }
}
$metrics | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $root "dist\build-metrics.json")

if (-not $SkipArtifactTests) {
    & $pythonExe @pythonArgs -m unittest discover -s tests -p "test_artifact.py"
    if ($LASTEXITCODE -ne 0) { throw "Tests der gebauten EXE fehlgeschlagen." }
}

Write-Host "Build abgeschlossen."
