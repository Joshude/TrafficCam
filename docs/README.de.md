# TrafficCam – private Verkehrsüberwachung mit Geschwindigkeitsmessung

> ⬆️ Projekt-Übersicht (GitHub-Landingpage): [../README.md](../README.md)
> · 🇬🇧 English version: [README.en.md](README.en.md) · Die Sprache der
> Weboberfläche (Deutsch/Englisch) ist in den Einstellungen umschaltbar.

TrafficCam misst die Geschwindigkeit vorbeifahrender Fahrzeuge im RTSP-Stream
einer Überwachungskamera (entwickelt mit einer UniFi G4 Doorbell) – komplett
lokal, ohne Cloud und ohne KI-Beschleuniger. Die Erkennung basiert auf
klassischer Bewegungserkennung (OpenCV MOG2) mit Objekt-Tracking; die
Geschwindigkeit entsteht aus einer perspektivisch korrekten Abbildung der
Straßenebene (Homographie) inklusive Fisheye-Entzerrung. Ergebnisse landen in
SQLite und CSV, werden per MQTT an Home Assistant gemeldet und sind über eine
Weboberfläche mit Live-Bild, Ereignisliste und Statistik einsehbar.

Das Projekt ist für schwache Hardware ausgelegt: Ein Intel J4105 (z.B. Dell
Wyse 5070) verarbeitet einen 15-FPS-Stream in Echtzeit. Es läuft nativ auf
Debian/Ubuntu (bare metal oder LXC); eine Docker-Variante liegt bei, wird aber
nicht aktiv gepflegt.

Wichtig vorab: Das ist ein Hobby-Messgerät, kein geeichter Blitzer. Die
Messwerte taugen für private Auswertungen und als Argumentationshilfe
(V85-Statistik), nicht als Beweismittel. Und: Die Kamera filmt öffentlichen
Raum – Abschnitt „Datenschutz" unten lesen.

---

## Funktionsumfang

Erfasst wird pro Fahrzeug die Geschwindigkeit (km/h), die Fahrtrichtung
(links→rechts / rechts→links) und ein annotierter Beweis-Snapshot mit Box,
Richtungspfeil, Tempo und der **Mess-Spur**: Die tatsächlich verwendeten
Bodenmesspunkte werden als Punktkette mit Start- (grün) und Endmarker (rot)
sowie Strecke/Dauer eingezeichnet – man sieht also direkt im Bild, wo und
worüber gemessen wurde (und erkennt Fehlmessungen wie Track-Verwechslungen
an einer zerrissenen Spur). Im Live-Bild wächst dieselbe Spur als Schweif
mit; welche Overlays (Boxen, Mess-Spur, Messbereich, Messlinie) im
Live-Stream gezeichnet werden, ist im Dashboard per Haken schaltbar. Der
zusätzliche Haken „Maske" ist ein Diagnose-Werkzeug: Er färbt die rohen
Bewegungspixel rot ein – damit sieht man direkt, warum eine Box so groß ist,
wie sie ist (z.B. ob Kontakt-Abdunklung unter dem Fahrzeug als Bewegung
zählt). Klebt die Box-Unterkante nicht am Fahrzeug, hilft ein höherer Wert
für `motion.tighten_min_fill` in der config.yaml (z.B. 0.3): Bildzeilen
zählen dann erst ab diesem Füllgrad zur Box, dünn belegte Ausläufer unter
dem Fahrzeug werden abgeschnitten. Eine Auslöse-Messlinie sorgt dafür, dass nur
Fahrzeuge zählen, die sie tatsächlich überqueren – parkende Autos, Fußgänger
auf dem Gehweg und Bewegung abseits der Fahrbahn fallen raus. Filter für
Mindest- und Höchstgeschwindigkeit sind zur Laufzeit in der Weboberfläche
einstellbar, ebenso eine Zeitsteuerung (immer / Zeitfenster / Sonnenstand),
mit der sich z.B. die nächtliche Messung abschalten lässt, wenn Motion Blur
die Werte unbrauchbar macht.

Die Statistik-Seite liefert die üblichen Verkehrskennzahlen: Anzahl,
Durchschnitt, Median, **V85** (das 85%-Perzentil – die Standardgröße der
Verkehrsplanung), Maximum und den Anteil über einem einstellbaren Tempolimit,
dazu Diagramme für Geschwindigkeitsverteilung, Aufkommen und Tempo je Stunde
sowie die letzten 14 Tage. Zusätzlich prüft die Seite automatisch die
**Richtungs-Symmetrie**: Da beide Fahrtrichtungen auf verschiedenen Spuren
fahren, aber langfristig dieselbe Geschwindigkeitsverteilung haben müssten,
deutet eine deutliche Abweichung der Richtungs-Mediane (>12 %) auf eine
Kalibrierungs-Schieflage einer Fahrbahnseite hin – ein Selbst-Check ganz ohne
Referenzfahrt.

Für Home Assistant werden per MQTT Auto-Discovery automatisch Sensoren
angelegt (letzte Geschwindigkeit, Richtung, Fahrzeuge/24h, online/offline).
Der Geschwindigkeits-Sensor ist als `state_class: measurement` deklariert –
HA erzeugt daraus von selbst Langzeitstatistiken (min/max/Ø pro
Stunde/Tag/Woche), die sich mit einer Statistik-Graph-Karte anzeigen lassen.

---

## Wie die Messung funktioniert (Kurzfassung)

Eine schräg blickende Kamera sieht nahe Fahrzeuge mit viel mehr Pixeln pro
Meter als ferne. TrafficCam löst das zweistufig: Zuerst wird die
**Fisheye-Verzerrung** der Linse mit einem Ein-Parameter-Modell (Division
Model) herausgerechnet – der Parameter wird daraus geschätzt, dass real
gerade Kanten (Bordstein, Zaun) im entzerrten Bild gerade sein müssen. Danach
bildet eine **Homographie** die Straßenebene in eine metrische Draufsicht ab;
kalibriert wird sie über mindestens 4 Punkte, deren Pixelposition und reale
Lage in Metern bekannt sind. Für jedes getrackte Fahrzeug wird der
Bodenkontaktpunkt (Unterkante-Mitte der Bewegungsbox) in diese Draufsicht
projiziert und dort in echten Metern verfolgt. Die Geschwindigkeit ist ein
robuster linearer Fit der Position entlang der Hauptbewegungsachse über die
Zeit – das mittelt Erkennungs-Zittern weg, und Messungen mit zerrissenem
Pfad (Track-Verwechslung zweier Fahrzeuge, erkennbar am Fit-Restfehler
`speed.max_residual_m`) werden automatisch verworfen statt als
Phantasie-Geschwindigkeit gespeichert.
Zeitstempel werden beim Frame-Empfang gesetzt, nicht aus der (schwankenden)
Stream-Framerate abgeleitet.

Konsequenz für die Praxis: Die Geschwindigkeitsmessung ist unabhängig davon,
auf welcher Spur ein Fahrzeug fährt – vorausgesetzt, die Kalibrierung stimmt
dort. Bei niedrig montierten Kameras (Türklingelhöhe) ist die ferne Spur
prinzipbedingt unschärfer bestimmt als die nahe; dafür gibt es den
Referenzmessungen-Wizard (unten).

---

## Hardware & Voraussetzungen

Ein x86-Rechner mit 2–4 Kernen und 2–3 GB RAM reicht (Referenz: Intel J4105).
Betriebssystem Debian 12 oder Ubuntu 22.04/24.04, nativ oder als
unprivilegierter Proxmox-LXC (kein Nesting, kein GPU-Passthrough nötig). Die
Kamera muss einen RTSP-Stream liefern; bei UniFi Protect wird RTSP je Kamera
unter *Settings → Advanced → RTSP* aktiviert, die URL hat die Form
`rtsp://<NVR-IP>:7447/<streamId>`. Empfohlen ist ein Stream mit 480×360 bis
960×720 bei ~15 FPS – höhere Auflösung verbessert die Kalibrier-Präzision,
kostet aber Decoding-CPU (das ist der teuerste Einzelposten; die
Bewegungsanalyse selbst rechnet intern immer auf `proc_width`, Standard
640 px).

---

## Installation

Archiv auf den Zielrechner kopieren und entpacken; Zielort ist
`/opt/trafficcam`:

```bash
tar -xzf trafficcam.tar.gz
sudo mv trafficcam /opt/
cd /opt/trafficcam
chmod +x install-lxc.sh
sudo ./install-lxc.sh
```

Das Skript installiert Systempakete (ffmpeg, OpenCV-Abhängigkeiten), legt
eine Python-venv an, installiert die Requirements, erzeugt aus der
Beispieldatei eine `config/config.yaml` mit korrekten Pfaden und richtet
einen systemd-Dienst ein. Danach:

```bash
sudo nano /opt/trafficcam/config/config.yaml   # mindestens stream.url eintragen
sudo systemctl enable --now trafficcam
journalctl -u trafficcam -f
```

Weboberfläche: `http://<host-ip>:8088/`

Die wichtigsten Einträge der `config.yaml`: `stream.url` (RTSP-Quelle, TCP
wird erzwungen, automatischer Reconnect), der `motion:`-Block (Parameter der
Bewegungserkennung, Defaults passen meist), `speed:` (Plausibilitätsgrenzen
der Messung), `storage:` (Pfade für Datenbank, CSV, Snapshots) und `mqtt:`
(siehe unten). Filter und Zeitsteuerung stehen bewusst **nicht** in der
Config – sie werden in der Weboberfläche gepflegt und in
`config/settings.yaml` persistiert. Kalibrierung, Entzerrung, Messlinie und
Messbereich landen in `config/homography.yaml`; beide Dateien entstehen
automatisch.

---

## Einrichtung / Kalibrierung – der Fahrplan

Die Reihenfolge ist wichtig, jeder Schritt passiert im Browser unter
`/calibrate` (bzw. `/referenzen` für Schritt 5). Nach einem Wechsel der
Stream-Auflösung müssen alle Pixel-Angaben neu gemacht bzw. skaliert werden!

**1. Entzerrung** (Modus „Entzerrung"): Entlang 2–3 real schnurgerader Kanten
(Bordsteinkante, Zaunlinie, Pflasterfuge) je ≥4 Punkte klicken – über die
Bildbreite verteilt, nicht durch die Bildmitte. „Entzerrung berechnen" findet
den Verzerrungsparameter λ automatisch. Kontrolle über den Knopf „Entzerrte
Vorschau": Gerade Kanten müssen darin gerade sein. Bei starken Fisheyes
(|λ| > ~1) sind die äußersten Bildecken außerhalb des Modellbereichs – dort
wird automatisch nicht gemessen; Kalibrierpunkte gehören ohnehin nicht in die
Ecken.

**2. Kalibrierpunkte** (Modus „Kalibrier-Punkte"): Mindestens 4 Punkte auf
der Straßenebene klicken, die eine **Fläche aufspannen** – idealerweise beide
Fahrbahnränder über mehrere Meter Länge. Zu jedem Punkt die reale Position in
Metern eintragen (X entlang der Fahrtrichtung, Y quer; Nullpunkt frei
wählbar; Komma und Punkt als Dezimaltrenner erlaubt). Die realen Maße müssen
**gemessen** sein, nicht geschätzt. Bewährtes Verfahren, wenn nur eine
Strecke direkt messbar ist (z.B. Zaunpfosten-Abstand): **Maßband-
Triangulation** – Basislinie P1=(0,0), P2=(L,0); für jeden weiteren Punkt die
Distanzen d1 (zu P1) und d2 (zu P2) messen, dann gilt
x = (d1² − d2² + L²)/(2·L) und y = √(d1² − x²). Pixel- und Meterwerte sind in
der Tabelle jederzeit editierbar, Punkte einzeln löschbar; gespeichert wird
mit Subpixel-Genauigkeit (Tipp: Browser-Zoom nutzen, Klicks bleiben präzise).

**3. Gitter prüfen:** Der Haken „Raster" zeigt live ein 1-m-Gitter aus den
aktuellen (auch ungespeicherten) Werten; „Gitter (Server) prüfen" zeigt die
gespeicherte, aktive Kalibrierung. Das Gitter muss wie ein plausibles
Schachbrett auf der Fahrbahn liegen und wird bewusst nur im Umfeld der
Kalibrierpunkte gezeichnet – es zeigt damit auch, wie groß der verlässlich
kalibrierte Bereich ist. Der Modus „Lineal" misst die Distanz zweier
angeklickter Punkte in Metern laut aktueller Kalibrierung – damit bekannte
Strecken kontrollieren (Zaun, Fahrbahnbreite, Radstand eines parkenden
Autos).

**4. Messlinie und Messbereich:** Die Messlinie (2 Punkte, quer über die
Fahrbahn, mittig im gut einsehbaren Bereich) ist der Auslöser – nur was sie
überquert, wird gewertet. Der optionale Messbereich (Polygon, ≥3 Punkte)
begrenzt, wo Messpunkte gesammelt werden; sinnvoll, um parkende Autos am
Rand, stark verzerrte Randzonen und Verdeckungen auszublenden. Faustregel:
8–10 m Fahrbahnlänge im Bereich lassen, damit auch schnelle Fahrzeuge genug
Messpunkte sammeln.

**5. Referenzmessungen** (Seite „Referenzmessungen"): Der Feinschliff, vor
allem für die ferne Fahrbahnseite. Aus den Snapshots der letzten Messungen
eines auswählen, die beiden Radaufstandspunkte eines Fahrzeugs anklicken und
den bekannten Radstand eintragen (Kompaktklasse ~2,60 m; besser:
Herstellerangabe des erkannten Modells). Die Tabelle zeigt sofort den Fehler
der aktuellen Kalibrierung. Dann bei den Kalibrierpunkten die Häkchen
„vermessen/fix" nur bei tatsächlich per Maßband bestimmten Punkten gesetzt
lassen und „Kalibrierung verfeinern" – ein Optimierer verschiebt
ausschließlich die unsicheren Punkte so, dass die Referenzlängen stimmen.
Das Ergebnis wird als Vorschlag mit neuen Fehlerwerten angezeigt und erst
durch „Übernehmen" aktiv. Mehrere Referenzen an verschiedenen Positionen
(nahe/ferne Spur, links/Mitte/rechts) verbessern das Ergebnis deutlich.

**6. Validieren:** Selbst mit konstantem Tempo durchfahren und vergleichen –
dabei die **GPS-Geschwindigkeit** (Handy-App) als Referenz nehmen, nicht den
Tacho: Autotachos zeigen konstruktionsbedingt 3–7 % zu viel an. Mehrere
Durchfahrten in beiden Richtungen (= beide Fahrspuren) machen. Der Tooltip auf dem km/h-Wert in der Ereignisliste zeigt
Strecke, Dauer und Messpunktzahl – damit lassen sich Geometriefehler
(Strecke falsch) von Timing-Problemen (Dauer gedehnt, z.B. weil die CPU dem
Stream nicht folgt) unterscheiden.

---

## Weboberfläche

Alle Seiten teilen sich eine Navigationsleiste (Dashboard, Messungen,
Statistik, Kalibrierung, Einstellungen, System); die Sprache der Oberfläche
(Deutsch/Englisch) wird oben auf der Einstellungen-Seite umgeschaltet. Das **Dashboard** (`/`)
zeigt Live-Bild mit Erkennungs-Overlay und FPS-Anzeige, Kennzahlen (inkl.
Fahrzeuge seit Tagesbeginn und in den letzten 24 h) und die letzten
Ereignisse — die Liste füllt auf dem Desktop die Höhe der Live-Ansicht, auf
Mobilgeräten zeigt sie 10 Einträge ohne eigenes Scrollen. Ein Klick auf ein
Vorschaubild öffnet auch hier den Messungs-Viewer mit Blättern und Lineal
(rotes ✕ = Messung samt Snapshot löschen). Filter (min./max. km/h, Tempolimit) und Zeitsteuerung
liegen unter **Einstellungen** (`/einstellungen`); dort gibt es außerdem
eine Experten-Karte für die Erkennungsparameter (Empfindlichkeit,
Schatten-Schwelle, Zeilen-Füllgrad, Blob-Mindestfläche, Merge-Abstand,
max. Fit-Restfehler; ein ausklappbarer Hilfebereich erklärt jeden Wert mit
Grafik, typischen Symptomen und Richtwerten). Änderungen dort werden
**ohne Neustart** übernommen
(der Hintergrund lernt danach einige Sekunden neu an) und in die
config.yaml zurückgeschrieben — Achtung: deren Kommentare gehen dabei
verloren, die dokumentierte Referenz ist config.example.yaml. Die **Kalibrierung**
bündelt als Untertabs „Geometrie & Messlinie" (`/calibrate`) und
„Referenzmessungen" (`/referenzen`). Unter **Alle Messungen** (`/messungen`)
liegt der komplette Datenbestand: filterbar nach Zeitraum,
Geschwindigkeitsbereich und Richtung, mit Kennzahlen (Anzahl, Ø, Median,
V85, Max, Anteil über Limit) und einklappbaren Diagrammen passend zum
aktiven Filter, Seitenblättern und Einzel- wie Massenlöschung des
Filterergebnisses – so lassen sich z.B.
offensichtliche Fehlmessungen („alles über 100 km/h") gezielt finden,
begutachten und entfernen. Ein Klick auf ein Vorschaubild öffnet den
Messungs-Viewer: Mit Pfeiltasten bzw. den Blätter-Buttons geht es durch die
Snapshots (Esc schließt), „Messung löschen" bzw. die Entf-Taste entfernt
den aktuellen Eintrag samt Snapshot und springt zum nächsten, und zwei
Klicks ins Bild messen wie mit dem
Lineal der Kalibrierseite eine Distanz in Metern laut aktueller
Kalibrierung – praktisch für schnelle Kontrollmessungen (Radstand!) direkt
am Ereignisbild. Auf Touch-Geräten wird per Wisch-Geste geblättert, die
Blätter-Buttons liegen dort halbtransparent über dem Bild. Der Knopf
**Diagnose** öffnet zu jeder Messung einen Position-über-Zeit-Plot der
gespeicherten Messpunkte (gelb = Bewegungserkennung, cyan = KI-Anker) samt
Fit-Gerade und Angabe, welche Punktmenge die Geschwindigkeit bestimmt hat —
das Werkzeug, um wandernde Punkte, Ausreißer und Anker-Fehlzuordnungen im
Detail zu verstehen (Messungen vor diesem Update haben noch keine
Punktdaten). Die **Statistik** (`/statistik`) bietet die
Kennzahlen und Diagramme mit Zeitraum-Umschalter; alle Balken zeigen per
Mouse-Over die exakten Werte. Unter **System** (`/system`) stehen
Datenbestand und Speicherverbrauch (Datenbank, CSV, Snapshots,
Datenträger-Füllstand) sowie die Datenpflege: eine Aufbewahrungsfrist in
Tagen (0 = aus), nach der alte Messungen samt Snapshots stündlich
automatisch gelöscht werden, plus ein manueller Aufräum-Knopf. Jede Messung
speichert zudem ihren Fit-Restfehler (`residual_m`, sichtbar im Tooltip der
Ereignislisten) als Qualitätsmaß. Unter **Kalibrierung** (`/calibrate`) liegen
alle Geometrie-Werkzeuge mit ein-/ausblendbaren Overlays, unter
**Referenzmessungen** (`/referenzen`) der Verfeinerungs-Wizard.

Relevante API-Endpunkte für eigene Auswertungen: `/api/events` (letzte
Messungen als JSON), `/api/events/query` (gefilterte Abfrage mit den
Parametern `from`, `to`, `min_kmh`, `max_kmh`, `richtung`, `limit`,
`offset`; als DELETE löscht derselbe Endpunkt das Filterergebnis),
`/api/stats` (Systemstatus), `/api/statistics?range=7d` (aggregierte
Kennzahlen; 24h/7d/30d/all).

Hinweis: Die Weboberfläche hat **keinen Zugriffsschutz**. Sie gehört nicht
ins Internet und idealerweise hinter einen Reverse Proxy mit Auth, wenn
mehr Leute im Netz sind als man selbst.

---

## Home Assistant / MQTT

In der `config.yaml`:

```yaml
mqtt:
  enabled: true
  host: "IP-DES-BROKERS"     # z.B. HA-Instanz mit Mosquitto-Addon
  port: 1883
  username: "trafficcam"     # eigener HA-Benutzer empfohlen
  password: "geheim"
  base_topic: "trafficcam"
  discovery: true
```

Beim Mosquitto-Addon von Home Assistant funktioniert jeder HA-Benutzer als
MQTT-Login; empfehlenswert ist ein dedizierter User (Einstellungen →
Personen → Benutzer, „nur lokal anmelden", kein Admin). Nach dem Verbinden
erscheinen die Sensoren automatisch unter einem Gerät „TrafficCam". Für die
Wochen-/Tagesauswertung in HA reicht eine Statistik-Graph-Karte auf den
Geschwindigkeits-Sensor. Verbindungstest vom TrafficCam-Host:
`mosquitto_sub -h <broker> -u <user> -P '<pass>' -t test -C 1 -W 5`
(„not authorised" = Zugangsdaten falsch; Timeout ohne Fehler = Verbindung ok).

---

## Erweiterte Erfassung (KI-Hybrid)

Unter **Einstellungen → Erkennung (Experten)** lässt sich die Erfassung
zwischen **einfach** und **erweitert** umschalten (wirkt ohne Neustart).
Im erweiterten Modus bleibt die Bewegungserkennung (MOG2) der
Echtzeit-Tracker bei voller Framerate; zusätzlich läuft ein entkoppelter
KI-Worker, der auf dem Messbereich-Ausschnitt YOLO-Fahrzeugboxen berechnet
(„Anker", im Live-Bild und Snapshot als cyanfarbene Punkte sichtbar). Diese
Anker sind beleuchtungsunabhängig — dunkle Reifen, die mit der Fahrbahn
verschmelzen, oder wandernde Karosserie-Unterkanten verfälschen sie nicht.
Anker werden doppelt abgesichert: Die KI-Box muss die Bewegungsbox deutlich
überlappen (gegen Fehl-Zuordnung auf geparkte Fahrzeuge), und der Anker
muss in der Nähe der bisherigen Spur desselben Tracks liegen (max. 3 m) —
sonst wird er verworfen. Liegen für eine Durchfahrt mindestens 3 Anker vor,
wird die Geschwindigkeit bevorzugt aus ihnen berechnet; sonst (oder wenn der Anker-Fit einen zu
hohen Restfehler hat) fällt die Messung automatisch auf die klassischen
Bewegungspunkte zurück. Ohne installiertes ultralytics-Paket läuft
durchgehend die einfache Erfassung; der Status-Chip im Dashboard zeigt den
Zustand (aktiv mit Inferenzzeit / startet / ultralytics fehlt).

Hardware-Bedarf: ~80 ms pro KI-Lauf auf einem Intel J4105 (Ausschnitt,
Netz 320) ergeben 4–6 Anker pro Durchfahrt — der eingebaute Benchmark auf
der System-Seite liefert die Werte für die eigene Maschine.
Feinjustierung in der config.yaml: `detector.hybrid_imgsz` (Netzgröße)
und `detector.hybrid_intervall_s` (Mindestabstand zwischen KI-Läufen).

---

## KI-Benchmark (System-Seite)

Unter **System** gibt es einen eingebauten Benchmark als Entscheidungshilfe,
welche Erfassungsstufe die Hardware tragen kann: Er misst die YOLO-Inferenzzeit auf dem aktuellen Kamerabild —
Vollbild und, falls definiert, den zugeschnittenen Messbereich-Ausschnitt in
mehreren Netz-Auflösungen. Der Benchmark läuft, während die normale
Erkennung weiterarbeitet; die FPS-Werte entstehen also unter realer Last.
Zu jedem Ergebnis gibt es eine Einordnung (Voll-KI in Echtzeit / reduzierte
Rate / Hybrid mit Box-Korrektur alle paar Frames / nur
Snapshot-Klassifizierung). Benötigt wie die Klassifizierung das
ultralytics-Paket in der venv.

---

## Dämmerungs-Profil (automatisch)

In der Dämmerung verschmelzen dunkle Reifen mit der Fahrbahn: Die
Bewegungsbox endet dann an der hellen Karosserie statt am Radaufstand, der
Bodenmesspunkt liegt zu weit hinten und die Geschwindigkeiten stimmen nicht
mehr; teils werden Fahrzeuge gar nicht erst erkannt. Zwei Effekte wirken
zusammen: zu wenig Kontrast (Empfindlichkeit) und — kontraintuitiv — die
Schattenerkennung, die im gräulichen Dämmerlicht dunkle Fahrzeugteile als
„Schatten" verwirft.

Der Haken **Dämmerungs-Profil** in den Einstellungen (Erkennung/Experten)
schaltet die Erkennung deshalb rund um Sonnenauf- und -untergang automatisch
auf angepasste Werte um (empfindlicher, Schatten-Verwerfung praktisch aus,
niedriger Zeilen-Füllgrad) und tagsüber wieder zurück — per
Sonnenstandsberechnung aus Breiten-/Längengrad der Zeitsteuerung, ohne
Neustart. Aktives Profil zeigt der Status-Chip im Dashboard. Fenster und
Werte lassen sich in der config.yaml unter `motion_dusk` anpassen
(`vor_sonnenuntergang_min`/`nach_sonnenaufgang_min`, Standard je 60).
Für die tiefe Nacht gibt es zusätzlich das **Nacht-Profil** (eigener
Haken): Sobald die Kamera im IR-Schwarzweißmodus arbeitet, dominieren
wandernde Scheinwerferkegel das Bild — mit den empfindlichen
Dämmerungswerten würde massenhaft Streulicht als Fahrzeug zählen. Das
Nacht-Profil greift ab ~45 min nach Sonnenuntergang (bis ~45 min vor
Sonnenaufgang, `motion_nacht` in der config.yaml) und schaltet auf das
Gegenteil um: deutlich unempfindlicher (var_threshold 70), höherer
Zeilen-Füllgrad und größere Blob-Mindestfläche, damit nur der kompakte
helle Fahrzeugkern zählt und diffuse Kegel-Halos herausfallen. Der Ablauf
über den Abend ist damit dreistufig: Tag → Dämmerung (empfindlich) →
Nacht (streng). Wer nachts gar nicht messen will (Motion Blur macht die
Tempi ohnehin unscharf), nutzt weiterhin die Zeitsteuerung — ohne Licht
gibt es irgendwann schlicht nichts mehr zu messen.

---

## Fahrzeug-Klassifizierung (optional)

Auf Wunsch klassifiziert TrafficCam jedes Ereignis nachträglich anhand des
Roh-Snapshots (PKW, LKW, Bus, Motorrad, Fahrrad, Fußgänger, Sonstige) — als
Filterkriterium auf der Messungen-Seite, z.B. um alle Fahrräder gesammelt zu
kontrollieren und zu löschen. Die Klassifizierung läuft bewusst **nicht** in
der Echtzeit-Pipeline (dafür ist YOLO auf schwacher Hardware zu langsam),
sondern einmal pro gespeichertem Ereignis in einem Hintergrund-Thread —
wenige hundert Millisekunden CPU pro Fahrzeug, die Messung merkt davon
nichts.

Aktivierung in zwei Schritten. Erst die Pakete in die venv des Projekts
(wichtig: Torch als CPU-Variante, sonst zieht pip mehrere GB
CUDA-Bibliotheken):

```bash
sudo /opt/trafficcam/.venv/bin/pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
sudo /opt/trafficcam/.venv/bin/pip install ultralytics
```

Dann unter Einstellungen → „Erkennung (Experten)" den Haken
**Snapshot-Klassifizierung** setzen und speichern — wird ohne Neustart
aktiv (der Schalter landet als `detector.classify_snapshots` in der
config.yaml). Beim ersten Ereignis lädt das Modell
(yolo11n, ~5 MB) einmalig aus dem Internet nach. Ohne installiertes Paket
bleibt die Funktion still deaktiviert; bereits vorhandene Ereignisse bleiben
„unklassifiziert" (Filteroption vorhanden), klassifiziert wird ab
Aktivierung. Hinweis: Die Zuordnung ist die des COCO-Datensatzes — Kleinbus/
Transporter landen gern als PKW oder LKW; für den Zweck „Fahrräder und
Fußgänger aussortieren" ist die Trefferquote aber sehr gut.

---

## Updates

Neues Release-Archiv auf den Host kopieren, dann:

```bash
./update.sh ~/trafficcam.tar.gz
```

Das Skript (liegt im Archiv, einmalig ins Home kopieren) stoppt den Dienst,
sichert die alte Installation zeitgestempelt nach
`/opt/trafficcam.bak-<datum>`, entpackt das neue Release, stellt
`config/*.yaml`, den kompletten `data/`-Ordner und die bestehende venv
wieder her, installiert ggf. neue Abhängigkeiten nach und startet den Dienst.
Bei Fehlern bricht es ab, bevor etwas verändert wird; die Backups erlauben
jederzeit ein manuelles Zurückrollen und können nach erfolgreichem Update
gelöscht werden.

---

## Fehlersuche

Wenn **keine Ereignisse** ankommen, der Reihe nach prüfen: Zeigt der
Status-Chip „Stream" und „kalibriert"? Ohne Kalibrierung wird nichts
gemessen; „Tracking pausiert" deutet auf die Zeitsteuerung. Ist eine
Messlinie gesetzt, zählen nur Überquerungen – Boxfarbe wechselt im Livebild
auf gelb, wenn ein Fahrzeug gewertet wird. Liegen Geschwindigkeiten
außerhalb der Filtergrenzen, werden sie verworfen.

Bei **systematisch falschen Geschwindigkeiten** zuerst mit dem Lineal
bekannte Strecken auf der Fahrspur nachmessen (Geometrie), dann den Tooltip
einer Testfahrt lesen: Stimmt die Strecke, aber die Dauer ist zu lang, kommt
die Verarbeitung dem Stream nicht nach (FPS-Anzeige gegen Stream-FPS
vergleichen; wachsende Bildverzögerung beim Winken vor der Kamera ist der
Beweis). Abhilfe: kleinere Stream-Auflösung, weniger konkurrierende Last,
mehr CPU-Priorität.

**Box deutlich größer als das Fahrzeug / Geschwindigkeiten bei Sonne zu
niedrig:** Die Bewegungsbox frisst den Schattenwurf – die Box-Unterkante
rutscht unter die Reifen, der Bodenpunkt wird zu nah an der Kamera
angenommen und die Geschwindigkeit unterschätzt. Abhilfe:
`motion.shadow_threshold` senken (Standard 0.3 erfasst auch harte
Mittagsschatten; MOG2-Standard wäre 0.5). Bekommen dunkle Fahrzeuge
dadurch „Löcher", Wert Richtung 0.4–0.5 erhöhen. Gegen Rausch-Phantome
hilft `motion.var_threshold` (höher = unempfindlicher) und `min_area`.

**Wildes Gitter / absurde Meterwerte:** Kalibrierpunkte spannen zu wenig
Fläche auf oder liegen fast auf einer Linie – die UI warnt beim Speichern;
Punkte über beide Fahrbahnränder verteilen. **Dienst crasht beim Start:**
`journalctl -u trafficcam -n 40` lesen; häufigster Fall nach Updates ist
eine fehlende neue Abhängigkeit (`.venv/bin/pip install -r
requirements.txt`). **HEVC-Warnungen** (`Could not find ref with POC`) im
Log sind harmlose Decoder-Meldungen des Kamerastreams.

---

## Datenschutz

Die Kamera filmt öffentlichen Verkehrsraum; Snapshots können Personen und
Kennzeichen zeigen. Das ist datenschutzrechtlich (DSGVO) heikel: nur für den
privaten Eigenbedarf nutzen, Aufbewahrung kurz halten, `save_snapshots:
false` setzen, wenn Bilder nicht gebraucht werden, Zugriff auf den Host und
die Weboberfläche beschränken und keine Aufnahmen veröffentlichen.
Kennzeichen werden von TrafficCam nicht ausgelesen.

---

## Projektstruktur

```
trafficcam/
├── run.py                 # Einstiegspunkt (Capture + Pipeline + Web)
├── install-lxc.sh         # Erstinstallation (Debian/Ubuntu, bare metal/LXC)
├── update.sh              # Update mit Backup & Wiederherstellung
├── requirements.txt
├── config/
│   ├── config.example.yaml
│   ├── config.yaml        # entsteht bei Installation (Stream, MQTT, Pfade)
│   ├── homography.yaml    # entsteht per Web-UI (Kalibrierung, Entzerrung,
│   │                      #   Messlinie, Messbereich)
│   └── settings.yaml      # entsteht per Web-UI (Filter, Zeitsteuerung)
├── data/                  # events.db, events.csv, snapshots/
└── app/
    ├── capture.py         # RTSP-Thread, Zeitstempel, Reconnect
    ├── motion.py          # MOG2-Bewegungserkennung + Centroid-Tracker
    ├── geometry.py        # Entzerrung, Homographie, Geschwindigkeits-Fit
    ├── refine.py          # Kalibrier-Verfeinerung per Referenzlängen
    ├── schedule.py        # Zeitfenster / Sonnenstands-Steuerung
    ├── hybrid.py          # KI-Anker-Worker (erweiterte Erfassung)
    ├── classify.py        # Snapshot-Klassifizierung (optional)
    ├── benchmark.py       # eingebauter KI-Benchmark
    ├── i18n.py            # UI-Übersetzung (Deutsch -> Englisch)
    ├── pipeline.py        # Hauptschleife: Erkennung→Tracking→Messung→Log
    ├── storage.py         # SQLite + CSV + Snapshots
    ├── settings.py        # Laufzeit-Einstellungen (Web-editierbar)
    ├── mqtt.py            # Home-Assistant-Anbindung (Auto-Discovery)
    ├── web.py             # Flask: Dashboard, Statistik, Kalibrierung, Wizard
    └── config.py          # Konfigurations-Defaults + Loader
```

---

*Diese Dokumentation gehört zum Release-Archiv und wird bei Änderungen am
Projekt mitgepflegt.*
