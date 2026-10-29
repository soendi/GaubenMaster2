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
- Beschriftete Seiten, Eckpunkte und Winkel
- Höhenteilung über `ha`, `hb` oder `hc`
- Teilung in 2–20 gleiche Teile oder in Abschnitte à 0,1–50 cm
- Farbige Einzelteile mit Fläche, Kantenlängen und Hover-Hervorhebung
- Um den Zuschnitt erweiterte, bemaßte Einzelteil-Zeichnungen mit Fv/Fh-Falzen
- Doppelklick auf ein Einzelteil öffnet eine Großansicht im 800 × 800-Pixel-Fenster
- Zuschnittangaben für Länge sowie vorderen und hinteren Falz
- Plattenplanung auf einer Coil mit fester Breite von 1 m
- Polygon-Verschachtelung mit freier Drehung der Einzelteile und berechneter Coil-Länge
- Platzierung inklusive Fv/Fh/Länge+ mit Verschnittanzeige
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

## Plattenplanung

**Extras → Plattenplanung...** oder die gleichnamige Schaltfläche im Bereich
Höhen-Teilung legt die Einzelteile auf eine Coil mit fester Breite von 100 cm.
Die Teile werden inklusive `Länge+`, `Fv` und `Fh` zugeschnitten und als
Polygone mit ihren echten Konturen verschachtelt. Die Standardwerte der
Zuschnittfelder sind `Länge+ = 3,0 cm`, `Fv = 3,5 cm` und `Fh = 4,5 cm`;
das Fenster öffnet mit 1400 × 900 Pixeln.

Die Optimierung verfolgt zwei Ziele gemeinsam: **Materialverschnitt
minimieren** und **modellierte Schnittanzahl minimieren**. Vier
Drehungsphasen (A: 0°/180°, B: 90°/270°, C: alternative Winkel mit
Verfeinerung, D: gemischte Drehungen je Teil) konkurrieren ohne Vorrang
einer Phase über die gewählte Bewertung (Verschnitt priorisieren,
Schnittanzahl priorisieren oder ausgewogen, Standard). Paar- und
Gruppenbildungen (2–4 Teile) sind auflösbar; die Kollisionsprüfung arbeitet
auf echten Konturen, nicht nur auf Bounding Boxes.

Die **modellierte Schnittanzahl** trennt geometrische Trennlinie,
zusammenhängenden Schnittweg und tatsächlichen Schnittvorgang: gemeinsame
Linien werden einmal gezählt, Berührungen gelten nicht als gemeinsame
Schnittlinie, Materialrandkanten werden nicht geschnitten, Schnittfugenbreite
ist 0 cm. Die Annahmen sind konfigurierbar (Ansatz am Materialrand ja/nein).

Mehrere Startreihenfolgen und lokale Verbesserungen liefern bis zu fünf
unterschiedliche, vollständig geometrisch geprüfte Anordnungen mit Rang,
Gesamtbewertung, Länge, Verschnittfläche/-anteil, modellierte Schnittanzahl,
Schnittmodell-Annahmen, Winkeln, Positionen, Paar-/Gruppenbildungen, Anzahl
Einzelteile/Gruppen, gemeinsamen Schnittlinien und Rechenzeit. Eine
Pareto-Front über (Verschnitt, Schnitte) wird zusätzlich als
Zielkonflikt-Tabelle angezeigt. Die Anzeige kennzeichnet die Lösung als
heuristisch gefunden, nicht als nachgewiesenes Optimum.

Im Modus **Schnittanzahl priorisieren** belohnt die Heuristik zusätzlich
durchgehende gerade Schnittlinien: Gleiche Breiten werden bevorzugt in
Spalten (bzw. Zeilen) gestapelt, die Teile abwechselnd um 180° gedreht, sodass
ihre Kanten ohne Versatz über viele Teile weiterlaufen. Eine lange Linie zählt
als ein Schnittweg, statt viele kurze Einzelanschnitte zu benötigen. Eine
solche Anordnung mit der längsten durchgehenden Linie ist immer unter den
angebotenen fünf Lösungen.

Während der Berechnung zeigt die Live-Ansicht die Materialfläche, die aktuell
getestete Platzierung, die beste bisherige Anordnung, Teilnummern, Winkel,
Koordinaten, Suchstrategie, aktuelle Paar-/Gruppenbildungen, Schnittanzahl,
Bewertung beider Ziele, Verschnitt und ob ein Kandidat gültig ist oder
verworfen wurde. Die Checkbox **Live-Ansicht während der Berechnung anzeigen**
ist standardmäßig aktiv und beeinflusst weder Suchstrategie noch Ergebnis.
Das Zeitbudget steht standardmäßig auf 60 s (einstellbar 3–60 s), der
Winkelschritt auf 5°. Ein Abbruch oder Timeout liefert die beste bisherige
gültige Lösung. Bei weniger als fünf unterschiedlichen Lösungen wird dies
gekennzeichnet.

Als Solver ist standardmäßig die eigene Heuristik aktiv. Ist das optionale
Paket `spyrrow` installiert, kann in der Combobox zusätzlich **Sparrow
(extern)** gewählt werden. Schlägt Sparrow fehl oder liefert es keine gültige
Anordnung, fällt die Berechnung automatisch auf die eigene Heuristik zurück.

## Aufbau

- `geometry.py`: validierte Dreiecksberechnung und Höhenteilung ohne UI
- `cutmodel.py`: transparentes Schnittkostenmodell (Annahmen, Segmente, Plan)
- `plot.py`: interaktive Tkinter-Zeichenfläche und Hover-Erkennung
- `partdraw.py`: scrollbare Einzelteil-Zeichnungen und Großansicht
- `nesting.py`: Polygon-Nesting-Engine (4 Phasen, Gruppen, Pareto, Top-5)
- `plateplanning.py`: Plattenplanungsfenster mit Live-Ansicht und Ergebniswahl
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
