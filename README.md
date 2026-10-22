# GaubenMaster2

GaubenMaster2 ist eine schlanke Windows-Anwendung für die Gaubenplanung.
Dieses Repository enthält das Grundgerüst, die Versionsverwaltung und ein
automatisches, prüfsummengesichertes Update über GitHub Releases.

## Technik

- Python 3.12, ausschließlich Standardbibliothek (`tkinter`, `urllib`)
- PyInstaller als **Onedir**-Build für schnellen Start
- MSI-Installer (WiX) pro Benutzer, keine Administratorrechte erforderlich
- GitHub Actions für Tests, Build und Release

## Installation

Den aktuellen Installer `GaubenMaster2-Setup-<Version>.msi` von den
[Releases](https://github.com/soendi/GaubenMaster2/releases/latest)
herunterladen und ausführen.

- Installationsordner: `%LOCALAPPDATA%\Programs\GaubenMaster2`
- Benutzerdaten: `%LOCALAPPDATA%\GaubenMaster2`
- Deinstallation über die Windows-Apps

Benutzerdaten bleiben bei Updates und bei der Deinstallation erhalten.

### Umstieg von der NSIS-Version

Versionen bis 1.0.3 wurden mit NSIS installiert. Sie können nicht automatisch
auf den MSI-Installer aktualisieren. Einmalig den neuen MSI-Installer
herunterladen und ausführen; er entfernt die alten NSIS-Verknüpfungen und
übernimmt die vorhandenen Benutzerdaten.

## Updates

Beim Start prüft die Anwendung höchstens alle sechs Stunden die neueste
stabile GitHub-Version. Ein Update wird nur angeboten, wenn:

- das Release nicht als Entwurf oder Vorabversion markiert ist,
- Tag und Dateiname exakt zum erwarteten Schema passen,
- Installer und `SHA256SUMS.txt` vorhanden sind,
- Downloadgröße und SHA-256-Prüfsumme stimmen.

Nach der Bestätigung beendet sich die Anwendung, der MSI-Installer läuft
still, und die neue Version wird automatisch gestartet. Schlägt die
Installation fehl, rollt Windows Installer die Änderungen zurück.

## Entwicklung

```powershell
py -3.12 -m unittest discover -s tests -v
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build.ps1
```

Voraussetzungen: Python 3.12, PyInstaller (`requirements-dev.txt`) und WiX 6.
Der Build erzeugt MSI, Prüfsumme und `build-metrics.json` unter `dist`.

```powershell
dotnet tool install --global wix --version 6.0.2
wix extension add -g WixToolset.Util.wixext/6.0.2
```

### Automatisierte Prüfungen der EXE

```powershell
dist\GaubenMaster2\GaubenMaster2.exe --version-out out.json
dist\GaubenMaster2\GaubenMaster2.exe --probe-out out.json
dist\GaubenMaster2\GaubenMaster2.exe --check-update-out out.json
dist\GaubenMaster2\GaubenMaster2.exe --install-update-out out.json --no-restart
```

## Release

1. Version in `src/gaubenmaster/version.py` erhöhen.
2. Änderungen committen und nach `master` pushen.
3. Tag `v<Version>` pushen.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\release.ps1 -Version 1.1.0
```

Der Release-Workflow prüft Tag und Version, baut den MSI-Installer, testet das
Artefakt und veröffentlicht Installer, `SHA256SUMS.txt` und
`build-metrics.json`.

## Messwerte

Der Build schreibt Größe, Startzeit und SHA-256 nach `dist/build-metrics.json`.
Damit lassen sich Releases objektiv vergleichen.
