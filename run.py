"""Einstiegspunkt: Capture + Pipeline + Webserver starten."""
from __future__ import annotations

import os

from app.capture import StreamCapture
from app.config import Config
from app.mqtt import MqttPublisher
from app.pipeline import Pipeline
from app.settings import Settings
from app.storage import Storage
from app.web import create_app


def main():
    cfg_path = os.environ.get("CONFIG", "/config/config.yaml")
    config = Config(cfg_path)
    c = config.get()

    storage = Storage(**c["storage"])

    sf = c.get("settings_file") or os.path.join(
        os.path.dirname(c["calibration_file"]), "settings.yaml")
    settings = Settings(sf)

    capture = StreamCapture(
        url=c["stream"]["url"],
        rtsp_transport=c["stream"]["rtsp_transport"],
        reconnect_delay=c["stream"]["reconnect_delay"],
    )
    capture.start()

    mqtt = None
    if c.get("mqtt", {}).get("enabled"):
        mqtt = MqttPublisher(c["mqtt"])
        if not mqtt.start():
            print(f"WARNUNG: {mqtt.error}")

    pipeline = Pipeline(capture, config, storage, settings, mqtt)
    pipeline.start()

    app = create_app(pipeline, storage, config, settings)
    app.run(host=c["web"]["host"], port=c["web"]["port"],
            threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
