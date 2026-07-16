# TrafficCam

**A self-hosted vehicle speed camera built from an existing doorbell/security camera — no cloud, no AI accelerator, no proprietary hardware.**

TrafficCam turns an RTSP video stream (developed against a UniFi G4
Doorbell, but any RTSP camera works) into per-vehicle speed measurements.
It detects motion, tracks vehicles, corrects for lens (fisheye) distortion
and camera perspective, and computes real-world speed in km/h — entirely
on modest hardware like a $50 used thin client. Results land in SQLite and
CSV, get pushed to Home Assistant over MQTT, and are browsable through a
built-in web dashboard with live view, calibration tools, statistics and
an optional AI-assisted detection mode.

<p align="center">
  <!-- TODO: add a screenshot or GIF of the dashboard here -->
</p>

---

## ⚠️ This project is "vibe coded"

**Nearly the entire codebase, this documentation, and the commit history
were written by an AI (Claude, Anthropic), directed by a non-professional
developer through natural-language conversation rather than hand-written
line by line.** The human author (a hobbyist with a home lab, not a
software engineer by trade) provided the requirements, tested every
change against a real camera, drove the calibration workflow, and pushed
back when results looked wrong — but did not write the code directly.

What that means in practice:

- The architecture, variable names, and some design choices reflect
  what an AI produces when guided iteratively, not a from-scratch system
  design.
- Test coverage exists (the development process included unit tests for
  the tricky parts — geometry, speed fitting, calibration refinement) but
  it is not exhaustive, and there's no CI pipeline (yet).
- It has been running unattended in production on the author's own
  property for weeks and the measurements have been cross-checked against
  GPS speed on real test drives — it works. But review the code yourself
  before trusting it, especially the geometry and homography math if
  you're adapting it to a very different camera setup.
- Issues and PRs are welcome, including ones that clean up AI-flavored
  code smell.

If "AI-written home automation tool, human-tested" is not something you're
comfortable running, this project may not be for you — and that's a
completely reasonable position.

---

## Why this exists

Traffic calming in residential streets is a common complaint, but getting
real data on how fast people actually drive past your house usually means
either an expensive certified radar unit or trusting the municipality's
own (often sparse) measurements. TrafficCam is a **hobbyist measurement
tool**: not certified, not legal evidence, but accurate enough (validated
against GPS on repeated test drives) to build an honest V85 statistic and
have a data-backed conversation with your local traffic authority.

## Key features

- **No special hardware.** Runs in real time on a low-power x86 box (an
  Intel J4105 mini PC handles a 15 FPS stream comfortably). No GPU, no
  Coral/NPU accelerator required.
- **Perspective-correct speed.** Fisheye undistortion + homography mapping
  turn the camera's skewed view into a real-world top-down coordinate
  system, so vehicles are measured correctly regardless of which lane
  they're in.
- **Self-correcting quality gates.** Motion-detection glitches (shadows,
  headlight glare, track mix-ups between two vehicles) are detected via
  fit-residual analysis and discarded automatically instead of producing
  fantasy speeds.
- **Optional AI-assisted detection.** A YOLO-based hybrid mode adds
  lighting-independent vehicle anchors on top of classic motion detection,
  with an automatic fallback and a built-in benchmark so you can decide
  whether your hardware should run it.
- **Automatic day/dusk/night profiles.** Detection sensitivity adapts to
  changing light automatically — including a dedicated night profile for
  IR black-and-white footage with headlight glare.
- **Web dashboard.** Live view with detection overlays, per-event
  snapshots with a measurement trail drawn on them, filterable event
  history, statistics (V85, direction symmetry check), a guided
  calibration wizard, and a diagnostics view that plots the raw sample
  points behind any measurement.
- **Home Assistant integration** via MQTT auto-discovery.
- **Bilingual UI** (German/English), switchable at runtime.
- **Optional vehicle classification** (car/truck/bus/motorcycle/
  bicycle/pedestrian) for filtering the event history.

## Quick start

```bash
tar -xzf trafficcam.tar.gz          # or: git clone this repo
sudo mv trafficcam /opt/
cd /opt/trafficcam
sudo ./install-lxc.sh               # installs deps, creates venv + systemd service
sudo nano config/config.yaml        # set stream.url to your camera's RTSP URL
sudo systemctl enable --now trafficcam
```

Then open `http://<host-ip>:8088/` and follow the in-app calibration
wizard (also documented step by step below).

**Full documentation:** [docs/README.en.md](docs/README.en.md) (English) ·
[docs/README.de.md](docs/README.de.md) (Deutsch) — installation, hardware
requirements, the full calibration walkthrough, troubleshooting, MQTT
setup, and details on every feature above.

## Requirements

- x86 Linux host (Debian 12 / Ubuntu 22.04+), 2–4 cores, 2–3 GB RAM.
  Native or as an unprivileged Proxmox LXC.
- A camera with an RTSP stream (~480×360 to 960×720 @ ~15 FPS).
- Python 3.11+ (installed automatically by `install-lxc.sh`).
- Optional: `ultralytics`/PyTorch (CPU) for AI-assisted detection and
  vehicle classification — see the docs for the (important) CPU-only
  install command.

## ⚠️ Before you point a camera at a public street

This films public space. Depending on your jurisdiction this is subject
to data-protection law (in the EU, GDPR): use for private purposes only,
keep retention periods short, disable snapshot storage if you don't need
images, restrict access to the dashboard (it has **no built-in
authentication** — put it behind a reverse proxy with auth or keep it off
any network other people can reach), and don't publish recordings.
TrafficCam does not read number plates, but snapshots can still show
people and plates incidentally. See the Privacy section in the docs for
details.

**This is not a certified speed measurement device.** Treat every value
as an estimate for private/informal use, not as legal evidence.

## License

MIT — see [LICENSE](LICENSE).
