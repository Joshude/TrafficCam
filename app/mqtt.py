"""MQTT-Anbindung fuer Home Assistant (mit Auto-Discovery).

Publiziert je Messung ein JSON-Ereignis + laufende Statistik. Ueber
MQTT Discovery legt Home Assistant die Sensoren automatisch an:
Geschwindigkeit (state_class: measurement -> HA-Langzeitstatistik),
Richtung, Laenge, Zaehler 24h.
"""
from __future__ import annotations

import json
import threading


class MqttPublisher:
    def __init__(self, cfg):
        self.cfg = cfg
        self.base = cfg.get("base_topic", "trafficcam").strip("/")
        self.client = None
        self.error = None
        self._lock = threading.Lock()

    def start(self):
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            self.error = "paho-mqtt nicht installiert (pip install paho-mqtt)"
            return False
        try:
            try:  # paho >= 2.0
                c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                client_id="trafficcam")
            except (AttributeError, TypeError):  # paho 1.x
                c = mqtt.Client(client_id="trafficcam")
            user = self.cfg.get("username") or None
            if user:
                c.username_pw_set(user, self.cfg.get("password") or None)
            c.will_set(f"{self.base}/status", "offline", retain=True)
            c.on_connect = self._on_connect
            c.connect_async(self.cfg.get("host", "localhost"),
                            int(self.cfg.get("port", 1883)), keepalive=60)
            c.loop_start()
            self.client = c
            return True
        except Exception as e:
            self.error = f"MQTT-Verbindung fehlgeschlagen: {e}"
            return False

    def _on_connect(self, client, *args, **kwargs):
        client.publish(f"{self.base}/status", "online", retain=True)
        if self.cfg.get("discovery", True):
            self._publish_discovery(client)

    def _publish_discovery(self, client):
        prefix = self.cfg.get("discovery_prefix", "homeassistant").strip("/")
        device = {
            "identifiers": ["trafficcam"],
            "name": "TrafficCam",
            "manufacturer": "DIY",
            "model": "Verkehrsueberwachung",
        }
        common = {
            "availability_topic": f"{self.base}/status",
            "device": device,
        }
        sensors = [
            ("geschwindigkeit", {
                "name": "Letzte Geschwindigkeit",
                "state_topic": f"{self.base}/event",
                "value_template": "{{ value_json.speed_kmh }}",
                "unit_of_measurement": "km/h",
                "state_class": "measurement",
                "icon": "mdi:speedometer",
            }),
            ("richtung", {
                "name": "Letzte Richtung",
                "state_topic": f"{self.base}/event",
                "value_template": "{{ value_json.richtung }}",
                "icon": "mdi:arrow-left-right",
            }),
            ("fahrzeuge_24h", {
                "name": "Fahrzeuge 24h",
                "state_topic": f"{self.base}/stats",
                "value_template": "{{ value_json.letzte_24h }}",
                "state_class": "measurement",
                "icon": "mdi:counter",
            }),
        ]
        for key, conf in sensors:
            conf.update(common)
            conf["unique_id"] = f"trafficcam_{key}"
            client.publish(
                f"{prefix}/sensor/trafficcam/{key}/config",
                json.dumps(conf), retain=True)
        # frueher vorhandenen Laengen-Sensor in HA entfernen
        client.publish(f"{prefix}/sensor/trafficcam/laenge/config",
                       "", retain=True)

    def publish_event(self, result, stats, ts):
        if self.client is None:
            return
        with self._lock:
            try:
                self.client.publish(
                    f"{self.base}/event",
                    json.dumps({
                        "speed_kmh": result["speed_kmh"],
                        "richtung": result["direction"],
                        "distanz_m": result["distance_m"],
                        "ts": round(ts, 1),
                    }), retain=True)
                self.client.publish(f"{self.base}/stats",
                                    json.dumps(stats), retain=True)
            except Exception as e:
                self.error = f"MQTT-Publish fehlgeschlagen: {e}"
