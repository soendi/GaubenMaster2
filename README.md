# GaubenMaster2

GaubenMaster2 berechnet und visualisiert Dreiecke für die Gaubenplanung.
Dazu kommen Höhenteilung, Einzelteil-Zeichnungen und ein automatisches,
prüfsummengesichertes Update über GitHub Releases.

## Funktionen

- Eingabe der Seiten `a`, `b`, `c` in cm mit Dezimalkomma oder Dezimalpunkt
- Prüfung auf positive Seiten und die Dreiecksungleichung
- Winkel, Fläche, Umfang, Höhen, Inkreis- und Umkreisradius
- Interaktive Zeichnung: Verschieben per Mauszug, Drehen mit Strg+Mauszug, Zoomen per Mausrad
- Anzeige-Panel für Zoom, Schriftgröße und einzelne Maßhilfen
- Beschriftete Seiten, Eckpunkte, Winkel und Bounding-Boxen
- Höhenteilung über `ha`, `hb` oder `hc`
- Teilung in 2–20 gleiche Teile oder in Abschnitte à 0,1–50 cm
- Farbige Einzelteile mit Fläche, Kantenlängen und Hover-Hervorhebung
- Um den Zuschnitt erweiterte, bemaßte Einzelteil-Zeichnungen mit Fv/Fh-Falzen
- Doppelklick auf ein Einzelteil öffnet eine Großansicht im 800 × 800-Pixel-Fenster
- Zuschnittangaben für Länge sowie vorderen und hinteren Falz
- PDF-Export mit Hauptzeichnung und allen Einzelteilen (Zoomfenster-Stil, vier Teile pro A4-Seite)
- Update-Prüfung beim Start mit Benachrichtigung und stiller MSI-Installation
- Einstellungen für Auto-Update, Prüfintervall und Repository-URL

Die Fenstergröße startet mit 1400 × 900 Pixeln; die linke Steuerspalte ist 240 Pixel breit.

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

Beim Start prüft die Anwendung die neueste stabile GitHub-Version. Das
Prüfintervall, die automatische Suche und die Repository-URL lassen sich
unter **Extras → Einstellungen** ändern. Ein Update wird nur angeboten, wenn:

- das Release nicht als Entwurf oder Vorabversion markiert ist,
- Tag und Dateiname exakt zum erwarteten Schema passen,
- Installer und `SHA256SUMS.txt` vorhanden sind,
- Downloadgröße und SHA-256-Prüfsumme stimmen.

Nach der Bestätigung beendet sich die Anwendung, der MSI-Installer läuft
still, und die neue Version wird automatisch gestartet. Schlägt die
Installation fehl, rollt Windows Installer die Änderungen zurück.

## Aufbau

- `geometry.py`: validierte Dreiecksberechnung und Höhenteilung ohne UI
- `plot.py`: interaktive Tkinter-Zeichenfläche und Hover-Erkennung
- `partdraw.py`: scrollbare Einzelteil-Zeichnungen und Großansicht
- `ui.py`: Fenster, Eingaben, Einzelteil-Seitenleiste, Einstellungen, Updates
- `updater.py`: Release-Prüfung, Download, Prüfsumme und MSI-Installation
- `paths.py`: Installations-, Daten- und Cache-Pfade

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
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\release.ps1 -Version 1.2.0
```

Der Release-Workflow prüft Tag und Version, baut den MSI-Installer, testet das
Artefakt und veröffentlicht Installer, `SHA256SUMS.txt` und
`build-metrics.json`.

## Messwerte

Der Build schreibt Größe, Startzeit und SHA-256 nach `dist/build-metrics.json`.
Damit lassen sich Releases objektiv vergleichen.
