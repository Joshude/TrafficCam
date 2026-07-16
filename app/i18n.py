"""UI-Uebersetzung Deutsch -> Englisch.

Die Templates in web.py bleiben die deutsche Quelle der Wahrheit. Beim
Modulstart erzeugt translate() daraus einmalig englische Varianten, indem
die PAIRS der Reihe nach ersetzt werden (lange, kontextreiche Fragmente
zuerst, kurze verankerte Token zuletzt). Datenwerte bleiben unangetastet:
Klassen-Namen (PKW, Fahrrad, ...), Richtungs-Strings (links->rechts) und
Modus-Werte (immer/zeit/sonne) sind Teil der Datenbank bzw. API und werden
nur in der Anzeige uebersetzt.

Neue UI-Texte muessen hier ein Paar bekommen - der Test in der Entwicklung
(Rest-Deutsch-Detektor) schlaegt sonst an.
"""

PAIRS = [
    # ---------------- lange Absaetze / Hinweise ----------------
    (""">&bdquo;Raster live&ldquo; rechnet das 1-m-Gitter direkt im
   Browser aus den aktuellen (auch ungespeicherten) Punkten &mdash; dicke Linien
   = 5 m. &bdquo;Gitter (Server)&ldquo; zeigt die tats&auml;chlich gespeicherte
   und aktive Kalibrierung.<""",
     """>&ldquo;Live grid&rdquo; computes the 1&nbsp;m grid directly in the
   browser from the current (even unsaved) points &mdash; thick lines
   = 5 m. &ldquo;Grid (server)&rdquo; shows the calibration that is actually
   stored and active.<"""),
    (""">, die eine Fl&auml;che aufspannen
    (z.B. beide Fahrbahnr&auml;nder). Pixel- und Meterwerte sind direkt
    editierbar &mdash; der Punkt und das Live-Raster folgen sofort.<""",
     """> spanning an area
    (e.g. both road edges). Pixel and metre values are directly
    editable &mdash; the point and the live grid follow immediately.<"""),
    (""">2 Punkte quer &uuml;ber die Fahrbahn. Nur was die Linie
    &uuml;berquert, wird gewertet.<""",
     """>2 points across the road. Only what crosses the line
    is counted.<"""),
    ("""> im Bild &mdash; angezeigt
    wird die Distanz in Metern laut aktueller Kalibrierung (inkl. Entzerrung
    und ungespeicherter &Auml;nderungen). Damit pr&uuml;fst du bekannte
    Strecken: Zaunpfosten (10 m?), Radstand eines parkenden Autos (~2,6 m),
    Fahrbahnbreite. Weicht der Wert ab, stimmt die Kalibrierung <""",
     """> in the image &mdash; shown is
    the distance in metres according to the current calibration (incl.
    undistortion and unsaved changes). Use it to check known
    distances: fence posts (10 m?), wheelbase of a parked car (~2.6 m),
    road width. If the value is off, the calibration is wrong <"""),
    (""">&ge;4 Punkte entlang einer real
    schnurgeraden Kante<""",
     """>&ge;4 points along an edge that is
    dead straight in reality<"""),
    ("""> (Bordstein, Zaun, Pflasterfuge) &mdash; m&ouml;glichst
    &uuml;ber die ganze Bildbreite und <""",
     """> (kerb, fence, paving joint) &mdash; ideally
    across the full image width and <"""),
    (""">. Dann
    &bdquo;Linie abschlie&szlig;en&ldquo; und weitere Kanten erfassen (2&ndash;3
    Linien in unterschiedlicher Bildh&ouml;he sind ideal). Zum Schluss
    berechnen &mdash; das Raster ber&uuml;cksichtigt die Kr&uuml;mmung danach
    automatisch.<""",
     """>. Then
    &ldquo;finish line&rdquo; and capture more edges (2&ndash;3 lines at
    different image heights are ideal). Finally compute &mdash; the grid
    accounts for the curvature automatically afterwards.<"""),
    (""">&ge;3 Punkte f&uuml;r den Messbereich &mdash; nur dort werden
    Messpunkte gesammelt. Beim Fisheye mittig bleiben.<""",
     """>&ge;3 points for the measurement area &mdash; sample points are only
    collected there. With a fisheye, stay near the centre.<"""),
    (""">1) Snapshot aus den letzten Messungen w&auml;hlen &middot;
   2) zwei Punkte anklicken (z.B. beide Radaufstandspunkte, Abstand = Radstand)
   &middot; 3) reale L&auml;nge eintragen &middot; 4) Referenz hinzuf&uuml;gen.
   Mehrere Referenzen von verschiedenen Fahrzeugen/Stellen erh&ouml;hen die
   Genauigkeit.<""",
     """>1) Pick a snapshot from recent measurements &middot;
   2) click two points (e.g. both tyre contact points, distance = wheelbase)
   &middot; 3) enter the real length &middot; 4) add the reference.
   Several references from different vehicles/spots increase
   accuracy.<"""),
    (""">Typische Radst&auml;nde: Kleinwagen
   ~2,45 m &middot; Kompaktklasse (Golf etc.) ~2,60 m &middot; Kombi/Mittelklasse
   ~2,70&ndash;2,85 m &middot; SUV ~2,70&ndash;2,90 m. Genauer: Herstellerangabe
   des jeweiligen Fahrzeugs nachschlagen.<""",
     """>Typical wheelbases: small car
   ~2.45 m &middot; compact (Golf etc.) ~2.60 m &middot; estate/mid-size
   ~2.70&ndash;2.85 m &middot; SUV ~2.70&ndash;2.90 m. More precise: look up
   the manufacturer figure for the specific vehicle.<"""),
    (""">Punkte abw&auml;hlen, die du <""",
     """>Untick the points you have <"""),
    ("""> exakt vermessen hast
   (z.B. per Maßband/Triangulation) &mdash; nur diese werden optimiert. Fest
   angehakte Punkte bleiben unver&auml;ndert.<""",
     """> measured exactly
   (e.g. with tape measure/triangulation) &mdash; only those get optimised.
   Points left ticked stay unchanged.<"""),
    (""">Automatische Aufbewahrung: Messungen (inkl. Snapshots), die
   &auml;lter sind als die eingestellte Frist, werden st&uuml;ndlich
   automatisch gel&ouml;scht. <""",
     """>Automatic retention: measurements (incl. snapshots) older
   than the configured period are deleted automatically once per
   hour. <"""),
    (""">0 = nie l&ouml;schen.<""", """>0 = never delete.<"""),
    ("""> Die CSV-Datei
   w&auml;chst unabh&auml;ngig davon als fortlaufendes Protokoll weiter.<""",
     """> The CSV file
   keeps growing independently as a continuous log.<"""),
    (""">Misst, wie schnell die YOLO-Objekterkennung auf dieser
   Maschine l&auml;uft &mdash; <""",
     """>Measures how fast YOLO object detection runs on this
   machine &mdash; <"""),
    (""">w&auml;hrend die normale Erkennung
   weiterl&auml;uft<""",
     """>while normal detection keeps
   running<"""),
    (""">, die Werte entstehen also unter realer Last.
   Getestet werden Vollbild und (falls definiert) der
   Messbereich-Ausschnitt. Ben&ouml;tigt das ultralytics-Paket wie die
   Snapshot-Klassifizierung; Dauer ca. 30&ndash;60&nbsp;Sekunden.<""",
     """>, so the numbers reflect real load.
   Tested are the full frame and (if defined) the measurement-area
   crop. Requires the ultralytics package, same as snapshot
   classification; takes about 30&ndash;60&nbsp;seconds.<"""),
    (""">Wirkt sofort.
    Zeitfenster darf &uuml;ber Mitternacht gehen. Sonnenstand nutzt
    Breiten-/L&auml;ngengrad, Offset verl&auml;ngert die aktive Zeit in die
    D&auml;mmerung.<""",
     """>Takes effect immediately.
    The time window may span midnight. Sun mode uses latitude/longitude;
    the offset extends the active time into
    twilight.<"""),
    (""">Wird ohne
   Neustart &uuml;bernommen &mdash; der Hintergrund lernt danach ~10&nbsp;s
   neu an. Werte landen in der config.yaml (Kommentare dort gehen beim
   Speichern verloren; Referenz ist config.example.yaml).<""",
     """>Applied without a
   restart &mdash; the background model re-learns for ~10&nbsp;s afterwards.
   Values are written to config.yaml (its comments are lost on save;
   config.example.yaml remains the documented reference).<"""),
    (""">Erweitert: MOG2 trackt in Echtzeit, YOLO liefert
    zus&auml;tzlich beleuchtungsunabh&auml;ngige Fahrzeug-Anker auf dem
    Messbereich-Ausschnitt; die Messung nutzt bevorzugt die Anker.
    Entscheidungshilfe: KI-Benchmark auf der System-Seite. Wirkt ohne
    Neustart; ohne ultralytics l&auml;uft automatisch die einfache
    Erfassung.<""",
     """>Advanced: MOG2 tracks in real time, YOLO additionally provides
    lighting-independent vehicle anchors on the measurement-area
    crop; the measurement prefers the anchors.
    Decision aid: AI benchmark on the System page. Takes effect without
    a restart; without ultralytics the simple mode runs
    automatically.<"""),
    ("""> in der venv (siehe README). Wird sofort
   aktiv; klassifiziert werden neue Ereignisse. Ob es l&auml;uft, zeigt das
   Dienst-Log beim n&auml;chsten Ereignis.<""",
     """> in the venv (see README). Takes effect
   immediately; new events get classified. The service log shows whether
   it is running on the next event.<"""),
    (""">Ben&ouml;tigt
   einmalig <""",
     """>Requires
   once: <"""),
    # ---- Hilfebereich (Experten) ----
    (""">Was
    bedeuten diese Werte? (mit Beispielen)<""",
     """>What do
    these values mean? (with examples)<"""),
    ("""> &mdash; wie stark sich ein Pixel
     vom gelernten Hintergrund unterscheiden muss, um als Bewegung zu gelten.
     <""",
     """> &mdash; how much a pixel must differ
     from the learned background to count as motion.
     <"""),
    ("""> Regen, Bl&auml;tterrauschen oder Flimmern erzeugen
     Mini-Boxen &rarr; erh&ouml;hen (40&ndash;60). Fahrzeuge zerfallen in der
     D&auml;mmerung oder fehlen &rarr; senken (20&ndash;28). Standard 32.
    <""",
     """> Rain, leaf noise or flicker create
     mini boxes &rarr; increase (40&ndash;60). Vehicles fragment at
     dusk or go missing &rarr; decrease (20&ndash;28). Default 32.
    <"""),
    ("""> &mdash; wie dunkel ein Bereich gegen&uuml;ber
     dem Hintergrund sein darf und trotzdem noch als Schatten (statt Objekt)
     durchgeht. <""",
     """> &mdash; how dark a region may be relative
     to the background and still pass as shadow (instead of
     object). <"""),
    (""">Kleiner = mehr wird als Schatten verworfen.<""",
     """>Smaller = more gets discarded as shadow.<"""),
    ("""> Box frisst den Schattenwurf bei tiefer Sonne &rarr;
     senken (0,2). Dunkle Fahrzeuge zerfallen oder verschwinden teilweise
     &rarr; erh&ouml;hen (0,4). Standard 0,3.
    <""",
     """> Box swallows the cast shadow at low sun &rarr;
     decrease (0.2). Dark vehicles fragment or partially vanish
     &rarr; increase (0.4). Default 0.3.
    <"""),
    ("""> &mdash; eine Bildzeile
     z&auml;hlt erst zur Box, wenn dieser Anteil der Boxbreite dort wirklich
     Bewegungspixel enth&auml;lt. Der Bodenmesspunkt sitzt an der Unterkante!
     <""",
     """> &mdash; an image row only counts
     towards the box once this share of the box width actually contains
     motion pixels. The ground sample point sits at the bottom edge!
     <"""),
    ("""> Unterkante h&auml;ngt unter den R&auml;dern (Maske-Haken
     zeigt d&uuml;nnes Band darunter) &rarr; erh&ouml;hen (0,25&ndash;0,35).
     R&auml;der werden abgeschnitten &rarr; senken. Standard 0,15.
    <""",
     """> Bottom edge hangs below the wheels (mask toggle
     shows a thin band underneath) &rarr; increase (0.25&ndash;0.35).
     Wheels get cut off &rarr; decrease. Default 0.15.
    <"""),
    ("""> &mdash; kleinere Bewegungen werden komplett
     ignoriert (Fl&auml;che in Pixeln der internen 640er-Analysebreite).
     <""",
     """> &mdash; smaller motions are ignored
     entirely (area in pixels of the internal 640-wide analysis).
     <"""),
    ("""> V&ouml;gel, Katzen oder wehende &Auml;ste erzeugen
     Messungen &rarr; erh&ouml;hen (500&ndash;800). Ferne/kleine Fahrzeuge
     werden nicht mehr erfasst &rarr; senken. Standard 350.
    <""",
     """> Birds, cats or swaying branches create
     measurements &rarr; increase (500&ndash;800). Distant/small vehicles
     are no longer detected &rarr; decrease. Default 350.
    <"""),
    ("""> &mdash; Bewegungs-Blobs, die n&auml;her als dieser
     Abstand liegen, gelten als ein Fahrzeug. <""",
     """> &mdash; motion blobs closer than this
     distance count as one vehicle. <"""),
    ("""> Ein Auto
     erscheint als zwei flackernde Boxen (Dachtr&auml;ger, Anh&auml;nger)
     &rarr; erh&ouml;hen. Zwei sich begegnende Fahrzeuge verschmelzen zu
     einer Box (erzeugt Track-Geister!) &rarr; senken. Standard 12.
    <""",
     """> One car
     appears as two flickering boxes (roof rack, trailer)
     &rarr; increase. Two passing vehicles merge into
     one box (creates track ghosts!) &rarr; decrease. Default 12.
    <"""),
    ("""> &mdash; wie weit die Messpunkte im Mittel von
     einer gleichm&auml;&szlig;igen Fahrt abweichen d&uuml;rfen (Meter).
     Track-Verwechslungen erzeugen Spr&uuml;nge im Pfad und damit
     Phantasie-Geschwindigkeiten &mdash; die fallen hier raus.
     <""",
     """> &mdash; how far the sample points may deviate
     on average from a steady pass (metres).
     Track mix-ups create jumps in the path and thus
     fantasy speeds &mdash; those get dropped here.
     <"""),
    ("""> Immer noch &gt;100-km/h-Geister in der Liste &rarr;
     senken (0,4). Offensichtlich echte Fahrten fehlen trotz sauberer Spur
     &rarr; erh&ouml;hen (0,8&ndash;1,0). Standard 0,6.
    <""",
     """> Still &gt;100 km/h ghosts in the list &rarr;
     decrease (0.4). Obviously real passes missing despite a clean trail
     &rarr; increase (0.8&ndash;1.0). Default 0.6.
    <"""),
    # ---- Statistik-Seite ----
    (""">&#9888;
    Richtungs-Mediane weichen ${rel.toFixed(0)}% voneinander ab - da beide
    Richtungen auf verschiedenen Spuren fahren, deutet das auf eine
    Kalibrierungs-Schieflage einer Fahrbahnseite hin (Referenzmessungen
    auf der abweichenden Spur helfen).<""",
     """>&#9888;
    Direction medians differ by ${rel.toFixed(0)}% - since the two
    directions travel in different lanes, this hints at a calibration
    skew on one side of the road (reference measurements
    on the deviating lane help).<"""),
    (""">Richtungs-Symmetrie
    ok (${rel.toFixed(0)}% Abweichung der Mediane)<""",
     """>Direction symmetry
    ok (${rel.toFixed(0)}% median deviation)<"""),
    # ---- Viewer / Dialoge / JS-Literale ----
    (""">Klick ins Bild = Lineal (2 Punkte, 3. Klick setzt zur&uuml;ck)
   &middot; &larr;/&rarr; bl&auml;ttern &middot; Esc schlie&szlig;en<""",
     """>Click in the image = ruler (2 points, 3rd click resets)
   &middot; &larr;/&rarr; browse &middot; Esc closes<"""),
    (""">Diagramme zu den
   gefilterten Ergebnissen ein-/ausklappen<""",
     """>Show/hide charts for the
   filtered results<"""),
    ("'Wirklich ALLE Messungen samt Snapshots loeschen?'",
     "'Really delete ALL measurements including snapshots?'"),
    ("'Diese Messung samt Snapshot endgueltig loeschen?'",
     "'Permanently delete this measurement including its snapshot?'"),
    ("`Wirklich ALLE ${total} gefilterten Messungen samt Snapshots l\\u00f6schen?`",
     "`Really delete ALL ${total} filtered measurements including snapshots?`"),
    ("'keine Treffer'", "'no matches'"),
    ("' Messungen geloescht'", "' measurements deleted'"),
    ("`Wirklich alle Messungen vor dem ${cut.toLocaleDateString('de-DE')} `",
     "`Really delete all measurements before ${cut.toLocaleDateString('en-GB')} `"),
    ("`inkl. Snapshots löschen?`", "`including snapshots?`"),
    ("`Modell-Lade-/Warmlaufzeit: ${s.load_s} s (fällt nur beim Start an)`",
     "`Model load/warm-up time: ${s.load_s} s (only on startup)`"),
    ("'läuft …'", "'running …'"),
    ("'gespeichert & aktiv'", "'saved & active'"),
    ("'gespeichert'", "'saved'"),
    ("'übernommen (ohne Neustart)'", "'applied (no restart)'"),
    ("'Fehler: '", "'Error: '"),
    ("'Fehler'", "'Error'"),
    ("'Tage angeben'", "'enter days'"),
    ("'alle Felder ausfuellen'", "'fill in all fields'"),
    ("'genau 2 Punkte setzen'", "'set exactly 2 points'"),
    ("'mind. 3 Punkte setzen'", "'set at least 3 points'"),
    ("'mind. 4 Punkte je Linie'", "'at least 4 points per line'"),
    ("'erst >=4 Kalibrierpunkte mit Metern eintragen'",
     "'first enter >=4 calibration points with metres'"),
    ("'Punkt ausserhalb des Entzerrungsbereichs'",
     "'point outside the undistortion range'"),
    ("'Bereich entfernt'", "'area removed'"),
    ("'entfernt'", "'removed'"),
    ("'erst 2 Punkte klicken'", "'click 2 points first'"),
    ("'mind. eine Referenz hinzufuegen'", "'add at least one reference'"),
    ("'nicht aktiv · '", "'not active · '"),
    ("`aktiv: λ=${dist.lambda} · `", "`active: λ=${dist.lambda} · `"),
    ("`${distLines.length} Linie(n) erfasst`",
     "`${distLines.length} line(s) captured`"),
    ("` + aktuelle mit ${curLine.length} Punkt(en)`",
     "` + current with ${curLine.length} point(s)`"),
    ("λ=${j.lambda}, Kruemmung -${j.verbesserung}%",
     "λ=${j.lambda}, curvature -${j.verbesserung}%"),
    ("(längs ${dx.toFixed(2)} · quer ${dy.toFixed(2)})",
     "(along ${dx.toFixed(2)} · across ${dy.toFixed(2)})"),
    ("'kalibriert + Linie'", "'calibrated + line'"),
    ("'kalibriert'", "'calibrated'"),
    ("'nicht kalibriert'", "'not calibrated'"),
    ("' | Dämmerungs-Profil'", "' | dusk profile'"),
    ("' | KI-Hybrid: '", "' | AI hybrid: '"),
    (", Fit-Fehler '", ", fit error '"),
    (" Messpunkte${", " sample points${"),
    ("Punkt ${i+1}: (${calib.world_points[i][0]}, ${calib.world_points[i][1]}) m",
     "Point ${i+1}: (${calib.world_points[i][0]}, ${calib.world_points[i][1]}) m"),
    ("${r.n} Fzg., \\u00d8 ${r.avg}, Median ${r.median} km/h",
     "${r.n} veh., \\u00d8 ${r.avg}, median ${r.median} km/h"),
    (" Fzg.)`", " veh.)`"),
    (":00 Uhr: ${s.hour_n[i]} Fahrzeuge`", ":00: ${s.hour_n[i]} vehicles`"),
    (":00 Uhr: \\u00d8 ${s.hour_avg[i]} km/h", ":00: \\u00d8 ${s.hour_avg[i]} km/h"),
    (" km/h: ${s.hist[i]} Fahrzeuge`", " km/h: ${s.hist[i]} vehicles`"),
    ("${s.days[i]}: ${s.day_n[i]} Fahrzeuge, \\u00d8 ${s.day_avg[i]||'-'} km/h`",
     "${s.days[i]}: ${s.day_n[i]} vehicles, \\u00d8 ${s.day_avg[i]||'-'} km/h`"),
    ("toLocaleString('de-DE')", "toLocaleString('en-GB')"),
    # Klassen-Anzeige im EN-UI (Werte bleiben deutsch, Anzeige uebersetzt)
    ("let lastEvents=[],evIdx=-1,rPts=[],calibG=null;",
     "const KL={\"PKW\":\"Car\",\"LKW\":\"Truck\",\"Bus\":\"Bus\","
     "\"Motorrad\":\"Motorcycle\",\"Fahrrad\":\"Bicycle\","
     "\"Fussgaenger\":\"Pedestrian\",\"Sonstige\":\"Other\"};\n"
     "let lastEvents=[],evIdx=-1,rPts=[],calibG=null;"),
    ("' \\u00b7 '+e.klasse:''", "' \\u00b7 '+(KL[e.klasse]||e.klasse):''"),
    ("?e.klasse:'-'", "?(KL[e.klasse]||e.klasse):'-'"),
    # ---- title-Attribute ----
    ('title="Diagnose: erkannte Bewegungspixel rot einfaerben"',
     'title="Diagnostics: highlight detected motion pixels in red"'),
    ('title="Messung löschen"', 'title="Delete measurement"'),
    ('title="Messung l\\u00f6schen"', 'title="Delete measurement"'),
    ('title="hoeher = unempfindlicher gegen Rauschen/Flimmern"',
     'title="higher = less sensitive to noise/flicker"'),
    ('title="kleiner = auch harte/dunkle Schatten werden ignoriert"',
     'title="smaller = even hard/dark shadows get ignored"'),
    ('title="hoeher = Box-Unterkante klebt fester am Fahrzeug"',
     'title="higher = box bottom edge sticks tighter to the vehicle"'),
    ('title="kleinere Bewegungen werden ignoriert"',
     'title="smaller motions are ignored"'),
    ('title="nahe Blobs zu einem Fahrzeug zusammenfassen"',
     'title="merge nearby blobs into one vehicle"'),
    ('title="max. Fit-Restfehler; drueber gilt als Track-Geist"',
     'title="max. fit residual; above this counts as a track ghost"'),
    ("""title="Rund um Sonnenauf-/untergang automatisch auf empfindlichere
Daemmerungs-Werte umschalten (empfindlicher, Schatten-Verwerfung aus,
niedriger Fuellgrad) - dunkle Reifen verschmelzen sonst mit der Fahrbahn\"""",
     """title="Automatically switch to more sensitive dusk values around
sunrise/sunset (more sensitive, shadow rejection off, lower row fill)
- otherwise dark tyres blend into the road surface\""""),
    ('title="${e.distanz_m} m in ${e.dauer_s} s, ${e.samples}',
     'title="${e.distanz_m} m in ${e.dauer_s} s, ${e.samples}'),
    # ---- mittellange Fragmente ----
    (">Erkennung (Experten)<", ">Detection (expert)<"),
    ("> Snapshot-Klassifizierung\n   (PKW/LKW/Fahrrad/...)<",
     "> Snapshot classification\n   (car/truck/bicycle/...)<"),
    ("> D&auml;mmerungs-Profil (automatisch per\n   Sonnenstand)<",
     "> Dusk profile (automatic via\n   sun position)<"),
    (">erweitert (KI-Hybrid, ben&ouml;tigt ultralytics)<",
     ">advanced (AI hybrid, requires ultralytics)<"),
    (">einfach (Bewegungserkennung)<", ">simple (motion detection)<"),
    (">Erfassung\n   <", ">Detection mode\n   <"),
    (">KI-Benchmark (Entscheidungshilfe: einfache vs. erweiterte Erfassung)<",
     ">AI benchmark (decision aid: simple vs. advanced detection)<"),
    (">Benchmark starten<", ">Start benchmark<"),
    (">Messungen &auml;lter als X Tage\n    jetzt l&ouml;schen<",
     ">Delete measurements older than X days\n    now<"),
    (">Aufbewahrung (Tage)<", ">Retention (days)<"),
    (">Geschwindigkeitsverteilung (km/h)<", ">Speed distribution (km/h)<"),
    (">Fahrzeuge je Stunde<", ">Vehicles per hour<"),
    (">&Oslash; km/h je Stunde<", ">&Oslash; km/h per hour<"),
    (">Letzte 14 Tage (Anzahl, Beschriftung: &Oslash;)<",
     ">Last 14 days (count, label: &Oslash;)<"),
    (">Letzte 14 Tage<", ">Last 14 days<"),
    (">\n    Letzte Ereignisse &nbsp;<", ">\n    Recent events &nbsp;<"),
    (">alle Messungen &rarr;<", ">all measurements &rarr;<"),
    (">alle l&ouml;schen<", ">delete all<"),
    (">gefilterte l&ouml;schen<", ">delete filtered<"),
    (">zur&uuml;cksetzen<", ">reset<"),
    (">&larr; zur&uuml;ck<", ">&larr; back<"),
    (">weiter &rarr;<", ">next &rarr;<"),
    (">Messung l&ouml;schen<", ">Delete measurement<"),
    (">Kalibrierung speichern<", ">Save calibration<"),
    (">Messlinie speichern<", ">Save measurement line<"),
    (">Messbereich speichern<", ">Save measurement area<"),
    (">Linie abschlie&szlig;en<", ">Finish line<"),
    (">Entzerrung berechnen<", ">Compute undistortion<"),
    (">\n       Entzerrung l&ouml;schen<", ">\n       Clear undistortion<"),
    (">\n       Bereich l&ouml;schen<", ">\n       Clear area<"),
    (">Entzerrte Vorschau<", ">Undistorted preview<"),
    (">Neues Standbild<", ">New still image<"),
    (">R&uuml;ckg&auml;ngig<", ">Undo<"),
    (">\n      Gitter (Server) pr&uuml;fen<", ">\n      Check grid (server)<"),
    (">Bewegungsmaske<", ">Motion mask<"),
    (">Referenz hinzuf&uuml;gen<", ">Add reference<"),
    (">Punkte l&ouml;schen<", ">Clear points<"),
    (">Unsichere Punkte<", ">Uncertain points<"),
    (">Vorschlag &uuml;bernehmen &amp; speichern<",
     ">Apply proposal &amp; save<"),
    (">Danach: Gitter pr&uuml;fen &rarr;<", ">Afterwards: check grid &rarr;<"),
    (">Kalibrierung verfeinern<", ">Refine calibration<"),
    (">Geometrie &amp; Messlinie<", ">Geometry &amp; measurement line<"),
    (">Referenzmessungen<", ">Reference measurements<"),
    (">System &amp; Speicher<", ">System &amp; storage<"),
    (">TrafficCam Statistik<", ">TrafficCam statistics<"),
    (">TrafficCam gesamt<", ">TrafficCam total<"),
    (">Datentr&auml;ger<", ">Disk<"),
    (">Aufr&auml;umen<", ">Cleanup<"),
    (">Datenbestand<", ">Data inventory<"),
    (">Belegter Platz<", ">Space used<"),
    (">Datenbank<", ">Database<"),
    (">&auml;lteste<", ">oldest<"),
    (">neueste<", ">newest<"),
    (">Manuell<", ">Manual<"),
    (">Einordnung<", ">Assessment<"),
    (">Variante<", ">Variant<"),
    (">Netz<", ">Net<"),
    (">ms/Bild<", ">ms/image<"),
    (">Zeitsteuerung<", ">Schedule<"),
    (">immer aktiv<", ">always active<"),
    (">Zeitfenster<", ">Time window<"),
    (">Sonnenstand<", ">Sun position<"),
    (">aktiv von<", ">active from<"),
    (">aktiv bis<", ">active until<"),
    (">Breitengrad<", ">Latitude<"),
    (">L&auml;ngengrad<", ">Longitude<"),
    (">D&auml;mmerung +min<", ">Twilight +min<"),
    (">Tempolimit<", ">Speed limit<"),
    (">Modus<", ">Mode<"),
    (">min. km/h<", ">min km/h<"),
    (">max. km/h<", ">max km/h<"),
    (">Filtern<", ">Apply filter<"),
    (">Filter<", ">Filter<"),
    (">Treffer<", ">matches<"),
    (">Richtung<", ">Direction<"),
    (">beide<", ">both<"),
    (">alle<", ">all<"),
    ("value=\"PKW\">PKW<", "value=\"PKW\">Car<"),
    ("value=\"LKW\">LKW<", "value=\"LKW\">Truck<"),
    ("value=\"Motorrad\">Motorrad<", "value=\"Motorrad\">Motorcycle<"),
    ("value=\"Fahrrad\">Fahrrad<", "value=\"Fahrrad\">Bicycle<"),
    ("value=\"Fussgaenger\">Fussgaenger<", "value=\"Fussgaenger\">Pedestrian<"),
    ("value=\"Sonstige\">Sonstige<", "value=\"Sonstige\">Other<"),
    (">unklassifiziert<", ">unclassified<"),
    (">Klasse<", ">Class<"),
    (">Strecke<", ">Distance<"),
    (">Dauer<", ">Duration<"),
    (">Bild<", ">Image<"),
    (">Zeit<", ">Time<"),
    (">L&auml;nge<", ">Length<"),
    (">aktuell<", ">current<"),
    (">Fehler<", ">Error<"),
    (">Ergebnis<", ">Result<"),
    (">neu<", ">new<"),
    (">vermessen/fix<", ">measured/fixed<"),
    (">7 Tage<", ">7 days<"),
    (">30 Tage<", ">30 days<"),
    (">alles<", ">all<"),
    (">Fahrzeuge heute<", ">Vehicles today<"),
    (">Fahrzeuge (24 h)<", ">Vehicles (24 h)<"),
    (">Fahrzeuge<", ">Vehicles<"),
    (">gesamt<", ">total<"),
    ("> Boxen<", "> Boxes<"),
    ("> Mess-Spur<", "> Trail<"),
    ("> Bereich<", "> Area<"),
    ("> Linie<", "> Line<"),
    ("> Maske<", "> Mask<"),
    ("> Kalibrier-Punkte<", "> Calibration points<"),
    ("> Messlinie<", "> Measurement line<"),
    ("> Messbereich<", "> Measurement area<"),
    ("> Entzerrung<", "> Undistortion<"),
    ("> Lineal<", "> Ruler<"),
    ("> Raster<", "> Grid<"),
    ("> Punkte<", "> Points<"),
    ("> Kanten<", "> Edges<"),
    ("> Lupe<", "> Loupe<"),
    (">Kalibrierung<", ">Calibration<"),
    (">Messungen<", ">Measurements<"),
    (">Alle Messungen<", ">All measurements<"),
    (">Statistik<", ">Statistics<"),
    (">Einstellungen<", ">Settings<"),
    (">Speichern<", ">Save<"),
    (">Klicke <", ">Click <"),
    (">&ge;4 Punkte<", ">&ge;4 points<"),
    (">2 Punkte<", ">2 points<"),
    (">nicht durch die Bildmitte<", ">not through the image centre<"),
    (">nicht.<", ">not.<"),
    (">nicht<", ">not<"),
    # SVG-Hilfegrafiken
    (">zu niedrig: Rauschen wird erkannt<", ">too low: noise gets detected<"),
    (">passend: nur das Fahrzeug<", ">right: only the vehicle<"),
    (">Empfindlichkeit (var_threshold)<", ">Sensitivity (var_threshold)<"),
    (">\n    Empfindlichkeit (var_threshold)<",
     ">\n    Sensitivity (var_threshold)<"),
    (">Schatten wird Teil der Box<", ">shadow becomes part of the box<"),
    (">Schatten wird ignoriert<", ">shadow is ignored<"),
    (">Schatten-Schwelle (0..1)<", ">Shadow threshold (0..1)<"),
    (">\n    Schatten-Schwelle (0..1)<", ">\n    Shadow threshold (0..1)<"),
    (">Schatten-Schwelle<", ">Shadow threshold<"),
    (">Auslaeufer zieht Messpunkt runter<",
     ">tail drags the sample point down<"),
    (">Kante sitzt an den Raedern<", ">edge sits at the wheels<"),
    (">Zeilen-F&uuml;llgrad (tighten_min_fill)<",
     ">Row fill (tighten_min_fill)<"),
    (">\n    Zeilen-F&uuml;llgrad (0..1)<", ">\n    Row fill (0..1)<"),
    (">Vogel: zu klein<", ">bird: too small<"),
    (">Auto: gross genug<", ">car: large enough<"),
    (">zu hoch: fernes<", ">too high: distant<"),
    (">Auto fehlt<", ">car missing<"),
    (">min. Blob-Fl&auml;che (px)<", ">Min. blob area (px)<"),
    (">\n    min. Blob-Fl&auml;che (px)<", ">\n    Min. blob area (px)<"),
    (">min. Blob-Fl&auml;che<", ">Min. blob area<"),
    (">zerfallenes Auto &rarr; eine Box<", ">fragmented car &rarr; one box<"),
    (">zu hoch: 2 Autos verschmelzen<", ">too high: 2 cars merge<"),
    (">Merge-Abstand (px)<", ">Merge distance (px)<"),
    (">\n    Merge-Abstand (px)<", ">\n    Merge distance (px)<"),
    (">Merge-Abstand<", ">Merge distance<"),
    (">saubere Spur: wird gespeichert<", ">clean trail: gets stored<"),
    (">Sprung (ID-Tausch): verworfen<", ">jump (ID swap): discarded<"),
    (">max. Restfehler (m)<", ">Max. residual (m)<"),
    (">\n    max. Restfehler (m)<", ">\n    Max. residual (m)<"),
    (">max. Restfehler<", ">Max. residual<"),
    (">Symptom:<", ">Symptom:<"),
    # Diagnose-Ansicht im Viewer
    (">Diagnose</button>", ">Diagnostics</button>"),
    ("'keine Punktdaten (Messung vor dem Update)'",
     "'no point data (measurement predates the update)'"),
    ("`Fit ${(Math.abs(k)*3.6).toFixed(1)} km/h (${\n  e.erfassung==='erweitert'?'KI-Anker':'MOG2'})`",
     "`Fit ${(Math.abs(k)*3.6).toFixed(1)} km/h (${\n  e.erfassung==='erweitert'?'AI anchors':'MOG2'})`"),
    ("'Position (m) über Zeit (s) · gelb=MOG2 · cyan=KI-Anker'",
     "'position (m) over time (s) · yellow=MOG2 · cyan=AI anchors'"),
    # Nacht-Profil
    (" Nacht-Profil (IR-Modus, gegen\n   Scheinwerfer-Streulicht)<",
     " Night profile (IR mode, against\n   headlight glare)<"),
    ("' | Nacht-Profil'", "' | night profile'"),
    ("""title="Tiefe Nacht (IR-Schwarzweissbild): unempfindlichere Werte, damit
Scheinwerferkegel und Streulicht nicht als Fahrzeuge zaehlen. Greift ab
~45min nach Sonnenuntergang; dazwischen gilt das Daemmerungs-Profil\"""",
     """title="Deep night (IR black-and-white image): less sensitive values so
headlight cones and stray light do not count as vehicles. Applies from
~45 min after sunset; in between the dusk profile applies\""""),
    # Sprache-Karte
    (">Sprache / Language<", ">Language / Sprache<"),
    # Nachzuegler aus dem Detektor-Lauf
    ("'keine Kalibrierung'", "'no calibration'"),
    (":00 Uhr: Ø ", ":00: Ø "),
    ("} Fahrzeuge, Ø ", "} vehicles, Ø "),
    (">Mess-Werkzeug: Klicke <b>", ">Measuring tool: click <b>"),
    (">Fisheye-Korrektur: Klicke <b>", ">Fisheye correction: click <b>"),
    ('placeholder="reale L&auml;nge in m, z.B. 2,60"',
     'placeholder="real length in m, e.g. 2.60"'),
    ("'keine Kalibrierung gefunden - erst unter \"Kalibrierung\" anlegen'",
     "'no calibration found - create one under \"Calibration\" first'"),
    # sonstiges
    ("<html lang=de>", "<html lang=en>"),
    ("=4 Kalibrierpunkte", "=4 calibration points"),
]

# Backend-Status (dynamische Strings aus /api/stats, /api/benchmark)
STATUS_EN = {
    "aktiv": "active",
    "aktiv (Zeitfenster)": "active (time window)",
    "pausiert (Zeitfenster)": "paused (time window)",
    "aktiv (Tageslicht)": "active (daylight)",
    "pausiert (Nacht)": "paused (night)",
    "Zeitfenster ungueltig - aktiv": "time window invalid - active",
    "Sonnenberechnung fehlgeschlagen - aktiv": "sun calc failed - active",
    "aus": "off",
    "startet": "starting",
    "ultralytics fehlt": "ultralytics missing",
}

BENCH_EN = {
    "Vollbild": "Full frame",
    "Vollbild, kleine Aufl\u00f6sung": "Full frame, low resolution",
    "Messbereich-Ausschnitt": "Measurement-area crop",
    "Messbereich-Ausschnitt, klein": "Measurement-area crop, small",
    "Voll-KI je Frame in Echtzeit m\u00f6glich":
        "Full AI per frame feasible in real time",
    "KI je Frame mit reduzierter Rate machbar":
        "AI per frame feasible at reduced rate",
    "Hybrid empfohlen: KI-Boxkorrektur alle paar Frames":
        "Hybrid recommended: AI box correction every few frames",
    "nur f\u00fcr Snapshot-Klassifizierung geeignet":
        "only suitable for snapshot classification",
    "Modell wird geladen \u2026": "Loading model \u2026",
}


def translate(html):
    """Wendet alle PAIRS der Reihe nach an (deutsch -> englisch)."""
    for de, en in PAIRS:
        html = html.replace(de, en)
    return html


def status_en(s):
    return STATUS_EN.get(s, s)


def bench_en(status):
    """Uebersetzt einen Benchmark-Status-Dict (Kopie)."""
    out = dict(status)
    if out.get("progress"):
        p = out["progress"]
        p = p.replace("Variante", "Variant")
        for de, en in BENCH_EN.items():
            p = p.replace(de, en)
        out["progress"] = p
    if out.get("state") == "error" and out.get("error"):
        out["error"] = out["error"].replace(
            "ultralytics ist nicht installiert. Installation:",
            "ultralytics is not installed. Install:")
    out["results"] = [dict(r, variante=BENCH_EN.get(r["variante"],
                                                    r["variante"]),
                           einordnung=BENCH_EN.get(r["einordnung"],
                                                   r["einordnung"]))
                      for r in out.get("results", [])]
    return out
