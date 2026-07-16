"""RTSP-Capture in eigenem Thread, mit Zeitstempeln und Reconnect."""
from __future__ import annotations

import os
import threading
import time

import cv2


class StreamCapture(threading.Thread):
    """Liest fortlaufend Frames vom RTSP-Stream.

    Hält immer nur den neuesten Frame vor (kein Stau), damit die
    Geschwindigkeitsmessung mit aktuellen Daten arbeitet. Jeder Frame
    bekommt einen monotonen Zeitstempel beim Empfang -> robust gegen
    schwankende Stream-FPS.
    """

    def __init__(self, url, rtsp_transport="tcp", reconnect_delay=3.0):
        super().__init__(daemon=True)
        self.url = url
        self.reconnect_delay = reconnect_delay
        # FFMPEG-Optionen vor dem Oeffnen setzen (TCP ist stabiler)
        os.environ.setdefault(
            "OPENCV_FFMPEG_CAPTURE_OPTIONS",
            f"rtsp_transport;{rtsp_transport}|stimeout;5000000",
        )
        self._lock = threading.Lock()
        self._frame = None
        self._ts = None
        self._seq = 0
        self._last_read = 0
        self._running = True
        self.connected = False

    def _open(self):
        cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        return cap

    def run(self):
        cap = self._open()
        while self._running:
            if not cap or not cap.isOpened():
                self.connected = False
                if cap:
                    cap.release()
                time.sleep(self.reconnect_delay)
                cap = self._open()
                continue

            ok, frame = cap.read()
            now = time.monotonic()
            if not ok or frame is None:
                self.connected = False
                cap.release()
                time.sleep(self.reconnect_delay)
                cap = self._open()
                continue

            self.connected = True
            with self._lock:
                self._frame = frame
                self._ts = now
                self._seq += 1
        if cap:
            cap.release()

    def read(self):
        """Gibt (seq, timestamp, frame) zurueck oder (None, None, None)."""
        with self._lock:
            if self._frame is None:
                return None, None, None
            return self._seq, self._ts, self._frame

    def stop(self):
        self._running = False
