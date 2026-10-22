param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [switch]$SkipWatch
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$Version = $Version.TrimStart("v")
if ($Version -notmatch "^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$") {
    throw "Version muss dem Format 1.2.3 entsprechen."
}
$current = (& py -3.12 scripts\check_version.py).Trim()
if ($Version -eq $current) { throw "Version $Version ist bereits gesetzt." }
if ((git status --porcelain)) { throw "Arbeitsverzeichnis ist nicht sauber." }
if ((git rev-parse --abbrev-ref HEAD).Trim() -ne "master") {
    throw "Release wird nur von Branch master erstellt."
}

$versionFile = Join-Path $root "src\gaubenmaster\version.py"
$content = Get-Content $versionFile -Raw
$content = [regex]::Replace($content, '__version__\s*=\s*"[^"]+"', "__version__ = `"$Version`"")
Set-Content -LiteralPath $versionFile -Value $content -Encoding utf8 -NoNewline

& py -3.12 scripts\check_version.py
if ($LASTEXITCODE -ne 0) { throw "Versionsprüfung fehlgeschlagen." }
& py -3.12 -m unittest discover -s tests
if ($LASTEXITCODE -ne 0) { throw "Tests fehlgeschlagen." }

git add src\gaubenmaster\version.py
git commit -m "Release v$Version"
if ($LASTEXITCODE -ne 0) { throw "Commit fehlgeschlagen." }
git push origin master
if ($LASTEXITCODE -ne 0) { throw "Push fehlgeschlagen." }

git tag "v$Version"
git push origin "v$Version"
if ($LASTEXITCODE -ne 0) { throw "Tag-Push fehlgeschlagen." }

Write-Host "Tag v$Version veröffentlicht. GitHub Actions baut den Release."
if (-not $SkipWatch) {
    Start-Sleep -Seconds 5
    gh run list --workflow release.yml --limit 1
    Write-Host "Status: gh run watch"
}
