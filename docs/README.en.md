# TrafficCam – private traffic monitoring with speed measurement

> ⬆️ Project overview (GitHub landing page): [../README.md](../README.md)
> · 🇩🇪 Deutsche Version: [README.de.md](README.de.md) · The web UI language
> can be switched between German and English under Settings.

TrafficCam measures the speed of passing vehicles in the RTSP stream of a
surveillance camera (developed with a UniFi G4 Doorbell) – fully local,
no cloud, no AI accelerator required. Detection is based on classic motion
detection (OpenCV MOG2) with object tracking; speed comes from a
perspective-correct mapping of the road plane (homography) including
fisheye undistortion. Results are stored in SQLite and CSV, reported to
Home Assistant via MQTT, and available through a web interface with live
view, event list and statistics.

The project is designed for weak hardware: an Intel J4105 (e.g. Dell
Wyse 5070) processes a 15 FPS stream in real time. It runs natively on
Debian/Ubuntu (bare metal or LXC); a Docker variant is included but not
actively maintained.

Important up front: this is a hobby measuring device, not a certified speed
camera. The readings are fine for private analysis and as supporting
material (V85 statistics), not as legal evidence. Also: the camera films
public space – read the "Privacy" section below.

---

## Features

For each vehicle, TrafficCam records the speed (km/h), the direction of
travel (left→right / right→left) and an annotated evidence snapshot with
box, direction arrow, speed and the **measurement trail**: the ground
sample points actually used are drawn as a dotted chain with start (green)
and end markers (red) plus distance/duration – you can see directly in the
image where and over what the measurement was taken (and spot bad
measurements such as track mix-ups by a torn trail). The same trail grows
as a tail in the live view; which overlays (boxes, trail, measurement
area, measurement line) are drawn on the live stream can be toggled on the
dashboard. The additional "Mask" toggle is a diagnostic tool: it colours
the raw motion pixels red – showing directly why a box is as large as it
is (e.g. whether contact darkening under the vehicle counts as motion).
If the box bottom edge does not stick to the vehicle, a higher value for
`motion.tighten_min_fill` in config.yaml helps (e.g. 0.3): image rows then
only count towards the box above that fill ratio, thinly covered tails
below the vehicle get cut off. A trigger measurement line ensures that
only vehicles actually crossing it are counted – parked cars, pedestrians
on the pavement and motion off the road are excluded. Filters for minimum
and maximum speed are adjustable at runtime in the web UI, as is a
schedule (always / time window / sun position), e.g. to disable night-time
measurement when motion blur makes the values useless.

The statistics page provides the usual traffic metrics: count, average,
median, **V85** (the 85th percentile – the standard figure in traffic
planning), maximum and the share above a configurable speed limit, plus
charts for speed distribution, volume and speed per hour, and the last 14
days. The page also automatically checks **direction symmetry**: since the
two directions travel in different lanes but should show the same speed
distribution in the long run, a clear deviation of the direction medians
(>12 %) hints at a calibration skew on one side of the road – a self-check
without any reference drive.

For Home Assistant, sensors are created automatically via MQTT
auto-discovery (last speed, direction, vehicles/24h, online/offline). The
speed sensor is declared as `state_class: measurement` – HA builds
long-term statistics from it by itself (min/max/avg per hour/day/week),
which can be displayed with a statistics graph card.

---

## How the measurement works (short version)

A camera looking at an angle sees nearby vehicles with far more pixels per
metre than distant ones. TrafficCam solves this in two stages: first the
**fisheye distortion** of the lens is removed with a one-parameter model
(division model) – the parameter is estimated from the requirement that
edges which are straight in reality (kerb, fence) must be straight in the
undistorted image. Then a **homography** maps the road plane into a metric
top-down view; it is calibrated via at least 4 points whose pixel position
and real-world location in metres are known. For each tracked vehicle the
ground contact point (bottom-centre of the motion box) is projected into
this top-down view and followed there in real metres. The speed is a
robust linear fit of the position along the main axis of motion over time
– this averages out detection jitter, and measurements with a torn path
(track mix-up of two vehicles, recognisable by the fit residual
`speed.max_residual_m`) are discarded automatically instead of being
stored as fantasy speeds. Timestamps are taken at frame reception, not
derived from the (fluctuating) stream frame rate.

Practical consequence: the speed measurement is independent of which lane
a vehicle uses – provided the calibration is correct there. With
low-mounted cameras (doorbell height) the far lane is inherently less
precisely determined than the near one; that is what the reference
measurement wizard is for (below).

---

## Hardware & requirements

An x86 machine with 2–4 cores and 2–3 GB RAM is enough (reference: Intel
J4105). Operating system Debian 12 or Ubuntu 22.04/24.04, native or as an
unprivileged Proxmox LXC (no nesting, no GPU passthrough needed). The
camera must provide an RTSP stream; with UniFi Protect, RTSP is enabled
per camera under *Settings → Advanced → RTSP*, the URL has the form
`rtsp://<NVR-IP>:7447/<streamId>`. Recommended is a stream of 480×360 to
960×720 at ~15 FPS – higher resolution improves calibration precision but
costs decoding CPU (the single most expensive item; the motion analysis
itself always runs internally at `proc_width`, default 640 px).

---

## Installation

Copy the archive to the target machine and unpack it; the target location
is `/opt/trafficcam`:

```bash
tar -xzf trafficcam.tar.gz
sudo mv trafficcam /opt/
cd /opt/trafficcam
chmod +x install-lxc.sh
sudo ./install-lxc.sh
```

The script installs system packages (ffmpeg, OpenCV dependencies), creates
a Python venv, installs the requirements, generates a `config/config.yaml`
from the example file with correct paths and sets up a systemd service.
Then:

```bash
sudo nano /opt/trafficcam/config/config.yaml   # at least set stream.url
sudo systemctl enable --now trafficcam
journalctl -u trafficcam -f
```

Web interface: `http://<host-ip>:8088/`

The most important entries in `config.yaml`: `stream.url` (RTSP source,
TCP is enforced, automatic reconnect), the `motion:` block (motion
detection parameters, defaults usually fit), `speed:` (plausibility limits
of the measurement), `storage:` (paths for database, CSV, snapshots) and
`mqtt:` (see below). Filters and the schedule deliberately do **not** live
in the config – they are maintained in the web UI and persisted in
`config/settings.yaml`. Calibration, undistortion, measurement line and
measurement area go into `config/homography.yaml`; both files are created
automatically.

---

## Setup / calibration – the roadmap

The order matters; every step happens in the browser under `/calibrate`
(or `/referenzen` for step 5). After changing the stream resolution, all
pixel values must be redone or scaled!

**1. Undistortion** ("Undistortion" mode): click ≥4 points along each of
2–3 edges that are dead straight in reality (kerb line, fence line, paving
joint) – spread across the image width, not through the image centre.
"Compute undistortion" finds the distortion parameter λ automatically.
Check via the "Undistorted preview" button: straight edges must be
straight in it. With strong fisheyes (|λ| > ~1) the outermost image
corners are outside the model range – measurement is automatically skipped
there; calibration points do not belong in the corners anyway.

**2. Calibration points** ("Calibration points" mode): click at least 4
points on the road plane that **span an area** – ideally both road edges
over several metres of length. For each point, enter the real position in
metres (X along the direction of travel, Y across; origin freely
choosable; comma and dot both allowed as decimal separators). The real
dimensions must be **measured**, not guessed. A proven method when only
one distance is directly measurable (e.g. fence post spacing): **tape
measure triangulation** – baseline P1=(0,0), P2=(L,0); for each further
point measure the distances d1 (to P1) and d2 (to P2), then
x = (d1² − d2² + L²)/(2·L) and y = √(d1² − x²). Pixel and metre values are
editable in the table at any time, points can be deleted individually;
values are stored with sub-pixel precision (tip: use browser zoom, clicks
stay precise).

**3. Check the grid:** the "Grid" toggle shows a live 1 m grid from the
current (even unsaved) values; "Check grid (server)" shows the stored,
active calibration. The grid must lie on the road like a plausible
chessboard and is deliberately only drawn around the calibration points –
so it also shows how large the reliably calibrated area is. The "Ruler"
mode measures the distance of two clicked points in metres according to
the current calibration – use it to check known distances (fence, road
width, wheelbase of a parked car).

**4. Measurement line and area:** the measurement line (2 points, across
the road, centred in the well-visible area) is the trigger – only what
crosses it is counted. The optional measurement area (polygon, ≥3 points)
limits where sample points are collected; useful to exclude parked cars at
the edge, heavily distorted border zones and occlusions. Rule of thumb:
leave 8–10 m of road length inside the area so that fast vehicles also
collect enough sample points.

**5. Reference measurements** ("Reference measurements" page): the fine
tuning, especially for the far side of the road. Pick a snapshot from
recent measurements, click both tyre contact points of a vehicle and enter
the known wheelbase (compact class ~2.60 m; better: manufacturer figure
for the recognised model). The table immediately shows the error of the
current calibration. Then, among the calibration points, leave the
"measured/fixed" ticks set only for points actually determined with a tape
measure and hit "Refine calibration" – an optimiser moves only the
uncertain points so that the reference lengths come out right. The result
is shown as a proposal with new error values and only becomes active via
"Apply". Several references at different positions (near/far lane,
left/centre/right) improve the result considerably.

**6. Validate:** drive through at constant speed yourself and compare –
use the **GPS speed** (phone app) as the reference, not the speedometer:
car speedometers over-read by 3–7 % by design. Do several passes in both
directions (= both lanes). The tooltip on the km/h value in the event list
shows distance, duration and sample count – this separates geometry errors
(distance wrong) from timing problems (duration stretched, e.g. because
the CPU cannot keep up with the stream).

---

## Web interface

All pages share a navigation bar (Dashboard, Measurements, Statistics,
Calibration, Settings, System). The UI language (German/English) can be
switched at the top of the Settings page. The **dashboard** (`/`) shows
the live view with detection overlay and FPS display, key figures (incl.
vehicles since midnight and in the last 24 h) and the most recent events —
on desktop the list fills the height of the live view, on mobile it shows
10 entries without its own scrolling. Clicking a thumbnail opens the
measurement viewer with browsing and ruler here as well (red ✕ = delete
measurement including snapshot). Filters (min./max. km/h, speed limit) and
the schedule live under **Settings** (`/einstellungen`); there is also an
expert card for the detection parameters (sensitivity, shadow threshold,
row fill, minimum blob area, merge distance, max. fit residual; an
expandable help section explains each value with a graphic, typical
symptoms and reference values). Changes there are applied **without a
restart** (the background model re-learns for a few seconds afterwards)
and are written back to config.yaml — note: its comments are lost in the
process, the documented reference is config.example.yaml. **Calibration**
bundles the sub-tabs "Geometry & measurement line" (`/calibrate`) and
"Reference measurements" (`/referenzen`). Under **All measurements**
(`/messungen`) sits the complete data set: filterable by period, speed
range, direction and class, with key figures (count, avg, median, V85,
max, share above limit) and collapsible charts matching the active filter,
pagination, and single as well as bulk deletion of the filter result – so
obvious bad measurements ("everything above 100 km/h") can be found,
inspected and removed in a targeted way. Clicking a thumbnail opens the
measurement viewer: arrow keys or the browse buttons step through the
snapshots (Esc closes), "Delete measurement" or the Delete key removes the
current entry including its snapshot and jumps to the next one, and two
clicks in the image measure a distance in metres according to the current
calibration, just like the ruler on the calibration page – handy for quick
check measurements (wheelbase!) directly on the event image. On touch
devices you browse by swiping; the browse buttons sit semi-transparently
over the image there. The **Diagnostics** button opens a
position-over-time plot of the stored sample points for each measurement
(yellow = motion detection, cyan = AI anchors) with the fit line and an
indication of which point set determined the speed — the tool for
understanding wandering points, outliers and anchor mismatches in detail
(measurements taken before this update have no point data yet). **Statistics**
(`/statistik`) offers the key figures and charts with a period switcher;
all bars show exact values on mouse-over. Under **System** (`/system`) you
find the data inventory and storage usage (database, CSV, snapshots, disk
fill level) plus data maintenance: a retention period in days (0 = off)
after which old measurements including snapshots are deleted automatically
every hour, plus a manual cleanup button. Every measurement also stores
its fit residual (`residual_m`, visible in the tooltip of the event lists)
as a quality metric.

Relevant API endpoints for your own analyses: `/api/events` (recent
measurements as JSON), `/api/events/query` (filtered query with the
parameters `from`, `to`, `min_kmh`, `max_kmh`, `richtung`, `klasse`,
`limit`, `offset`; as DELETE the same endpoint removes the filter result),
`/api/stats` (system status), `/api/statistics?range=7d` (aggregated
figures; 24h/7d/30d/all). Note that data values remain German
(`richtung=links->rechts`, `klasse=PKW` etc.) regardless of the UI
language.

Note: the web interface has **no access control**. It does not belong on
the internet and should ideally sit behind a reverse proxy with auth if
there are more people on the network than just yourself.

---

## Home Assistant / MQTT

In `config.yaml`:

```yaml
mqtt:
  enabled: true
  host: "BROKER-IP"          # e.g. HA instance with Mosquitto add-on
  port: 1883
  username: "trafficcam"     # dedicated HA user recommended
  password: "secret"
  base_topic: "trafficcam"
  discovery: true
```

With Home Assistant's Mosquitto add-on, any HA user works as an MQTT
login; a dedicated user is recommended (Settings → People → Users, "local
login only", no admin). After connecting, the sensors appear automatically
under a "TrafficCam" device. For weekly/daily analysis in HA, a statistics
graph card on the speed sensor is all you need. Connection test from the
TrafficCam host:
`mosquitto_sub -h <broker> -u <user> -P '<pass>' -t test -C 1 -W 5`
("not authorised" = wrong credentials; timeout without error = connection
ok). The MQTT entity names are currently German.

---

## Advanced detection (AI hybrid)

Under **Settings → Detection (expert)** the detection mode can be switched
between **simple** and **advanced** (takes effect without a restart). In
advanced mode, motion detection (MOG2) remains the real-time tracker at
full frame rate; in addition, a decoupled AI worker computes YOLO vehicle
boxes on the measurement-area crop ("anchors", visible as cyan dots in the
live view and snapshot). These anchors are lighting-independent — dark
tyres blending into the road, or wandering body bottom edges, do not
distort them. Anchors are double-checked: the AI box must clearly overlap the motion
box (against mismatches onto parked vehicles), and the anchor must lie
close to the track's existing trail (max. 3 m) — otherwise it is
discarded. If at least 3 anchors exist for a pass, the speed is
computed preferably from them; otherwise (or if the anchor fit has too
high a residual) the measurement automatically falls back to the classic
motion points. Without the ultralytics package installed, the simple mode
runs throughout; the status chip on the dashboard shows the state (active
with inference time / starting / ultralytics missing).

Hardware demand: ~80 ms per AI run on an Intel J4105 (crop, net size 320)
yields 4–6 anchors per pass — the built-in benchmark on the System page
provides the numbers for your own machine. Fine tuning in config.yaml:
`detector.hybrid_imgsz` (net size) and `detector.hybrid_intervall_s`
(minimum gap between AI runs).

---

## AI benchmark (System page)

Under **System** there is a built-in benchmark as a decision aid on which
detection mode your hardware can carry: it measures the YOLO inference
time on the current camera image — full frame and, if defined, the cropped
measurement area at several net resolutions. The benchmark runs while
normal detection keeps working; the FPS numbers therefore reflect real
load. Each result comes with an assessment (full AI in real time / reduced
rate / hybrid with box correction every few frames / snapshot
classification only). Requires the ultralytics package in the venv, same
as classification.

---

## Dusk profile (automatic)

At dusk, dark tyres blend into the road surface: the motion box then ends
at the bright body instead of the tyre contact patch, the ground sample
point sits too far back and the speeds are off; sometimes vehicles are not
detected at all. Two effects combine: too little contrast (sensitivity)
and — counter-intuitively — the shadow detection, which discards dark
vehicle parts as "shadow" in greyish twilight.

The **dusk profile** toggle in Settings (Detection/expert) therefore
switches detection to adapted values around sunrise and sunset
automatically (more sensitive, shadow rejection practically off, lower row
fill) and back during the day — via sun position computed from the
latitude/longitude of the schedule, without a restart. The status chip on
the dashboard shows when the profile is active. Window and values can be
adjusted in config.yaml under `motion_dusk`
(`vor_sonnenuntergang_min`/`nach_sonnenaufgang_min`, default 60 each). For deep night there is additionally the **night profile** (its own
toggle): once the camera works in IR black-and-white mode, wandering
headlight cones dominate the image — with the sensitive dusk values,
masses of stray light would count as vehicles. The night profile applies
from ~45 min after sunset (until ~45 min before sunrise, `motion_nacht`
in config.yaml) and switches to the opposite: much less sensitive
(var_threshold 70), higher row fill and a larger minimum blob area, so
that only the compact bright vehicle core counts and diffuse cone halos
drop out. The evening sequence is thus three-staged: day → dusk
(sensitive) → night (strict). If you do not want to measure at night at
all (motion blur makes the speeds fuzzy anyway), the schedule remains the
right tool — without light there is simply nothing left to measure at
some point.

---

## Vehicle classification (optional)

On request, TrafficCam classifies each event after the fact from the raw
snapshot (car, truck, bus, motorcycle, bicycle, pedestrian, other) — as a
filter criterion on the measurements page, e.g. to review and delete all
bicycles in one go. Classification deliberately does **not** run in the
real-time pipeline (YOLO is too slow for that on weak hardware) but once
per stored event in a background thread — a few hundred milliseconds of
CPU per vehicle, the measurement does not notice it.

Activation in two steps. First the packages into the project venv
(important: torch as the CPU variant, otherwise pip pulls several GB of
CUDA libraries):

```bash
sudo /opt/trafficcam/.venv/bin/pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
sudo /opt/trafficcam/.venv/bin/pip install ultralytics
```

Then under Settings → "Detection (expert)" tick **Snapshot
classification** and save — takes effect without a restart (the switch is
stored as `detector.classify_snapshots` in config.yaml). On the first
event, the model (yolo11n, ~5 MB) is downloaded once from the internet.
Without the package installed, the feature stays silently disabled;
existing events remain "unclassified" (filter option available),
classification starts from activation. Note: the mapping is that of the
COCO dataset — vans/minibuses tend to land as car or truck; for the
purpose of "sorting out bicycles and pedestrians" the hit rate is very
good. The class values stored in the database are German (PKW, LKW,
Fahrrad, ...); the English UI translates them for display.

---

## Updates

Copy the new release archive to the host, then:

```bash
./update.sh ~/trafficcam.tar.gz
```

The script (included in the archive, copy it to your home once) stops the
service, backs up the old installation time-stamped to
`/opt/trafficcam.bak-<date>`, unpacks the new release, restores
`config/*.yaml`, the complete `data/` folder and the existing venv,
installs any new dependencies and starts the service. On errors it aborts
before changing anything; the backups allow a manual rollback at any time
and can be deleted after a successful update.

---

## Troubleshooting

If **no events** arrive, check in order: does the status chip show
"Stream" and "calibrated"? Without calibration nothing is measured;
"tracking paused" points to the schedule. If a measurement line is set,
only crossings count – the box colour switches to yellow in the live view
when a vehicle is counted. Speeds outside the filter limits are discarded.

For **systematically wrong speeds**, first re-measure known distances on
the driving lane with the ruler (geometry), then read the tooltip of a
test drive: if the distance is right but the duration is too long, the
processing cannot keep up with the stream (compare the FPS display with
the stream FPS; growing image delay when waving at the camera is the
proof). Remedy: lower stream resolution, less competing load, more CPU
priority.

**Box clearly larger than the vehicle / speeds too low in sunshine:** the
motion box swallows the cast shadow – the box bottom edge slips below the
tyres, the ground point is assumed too close to the camera and the speed
is underestimated. Remedy: lower `motion.shadow_threshold` (default 0.3
also catches hard midday shadows; the MOG2 default would be 0.5). If dark
vehicles get "holes" as a result, raise the value towards 0.4–0.5. Against
noise phantoms, `motion.var_threshold` helps (higher = less sensitive) and
`min_area`.

**Wild grid / absurd metre values:** the calibration points span too
little area or lie almost on one line – the UI warns on save; spread the
points across both road edges. **Service crashes on start:** read
`journalctl -u trafficcam -n 40`; the most common case after updates is a
missing new dependency (`.venv/bin/pip install -r requirements.txt`).
**HEVC warnings** (`Could not find ref with POC`) in the log are harmless
decoder messages from the camera stream.

---

## Privacy

The camera films public traffic space; snapshots can show people and
number plates. This is delicate under data protection law (GDPR): use for
private purposes only, keep retention short, set `save_snapshots: false`
if images are not needed, restrict access to the host and the web
interface, and do not publish recordings. Number plates are not read by
TrafficCam.

---

## Project structure

```
trafficcam/
├── run.py                 # entry point (capture + pipeline + web)
├── install-lxc.sh         # initial install (Debian/Ubuntu, bare metal/LXC)
├── update.sh              # update with backup & restore
├── requirements.txt
├── config/
│   ├── config.example.yaml
│   ├── config.yaml        # created at install (stream, MQTT, paths)
│   ├── homography.yaml    # created via web UI (calibration, undistortion,
│   │                      #   measurement line, measurement area)
│   └── settings.yaml      # created via web UI (filters, schedule, language)
├── data/                  # events.db, events.csv, snapshots/
└── app/
    ├── capture.py         # RTSP thread, timestamps, reconnect
    ├── motion.py          # MOG2 motion detection + centroid tracker
    ├── geometry.py        # undistortion, homography, speed fit
    ├── refine.py          # calibration refinement via reference lengths
    ├── schedule.py        # time window / sun position control
    ├── hybrid.py          # AI anchor worker (advanced detection)
    ├── classify.py        # snapshot classification (optional)
    ├── benchmark.py       # built-in AI benchmark
    ├── i18n.py            # UI translation (German -> English)
    ├── pipeline.py        # main loop: detection→tracking→measurement→log
    ├── storage.py         # SQLite + CSV + snapshots
    ├── settings.py        # runtime settings (web-editable)
    ├── mqtt.py            # Home Assistant integration (auto-discovery)
    ├── web.py             # Flask: dashboard, statistics, calibration, wizard
    └── config.py          # configuration defaults + loader
```

---

*This documentation is part of the release archive and is kept in sync
with project changes.*
