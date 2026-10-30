"""
Labvanced <-> Tobii eye tracker bridge
======================================

Records the gaze stream of a Tobii eye tracker and writes every event that a Labvanced study
sends over its WebSocket connection into the same recording, on the same clock. If the study
also sends its webcam gaze samples ([X,Y,T,C] arrays, message "webcam_gaze"), they are
recorded too, placed by their camera capture time T, and paired with the nearest Tobii sample.

Two tracker backends:
  --backend et5   Tobii Eye Tracker 5 (consumer device) through tobii_stream_engine.dll (ctypes)
  --backend pro   Tobii Pro trackers (Spark, Fusion, Nano, ...) through the tobii_research package

How it works
------------
* Labvanced (in the browser) connects to this script as a WebSocket client
  (Study Settings -> Special Features -> "WebSocket Connection", address ws://localhost,
  port 8081). Each "Send To Websocket" action sends {"msg": "<message>", "value": <variable value>}.
  The WebSocket server runs on its own thread.
* A background thread reads the gaze samples of the tracker.
* A small window (tkinter) shows the state of the Tobii stream, the study connection and the
  webcam stream, the output folder, and has the Stop button. Recording starts with the program.
  --no-gui runs without the window (stop with Ctrl+C).
* Once per second that thread measures the offset between the tracker clock and the computer's
  Unix clock. Labvanced timestamps ("Trigger Timestamp (Unixtime)", the webcam gaze time T) come
  from the same Unix clock of the same computer, so Labvanced events, Tobii samples and webcam
  gaze samples all end up on one time axis.

Output (one folder per run, inside --out-dir):
  gaze.csv        every Tobii gaze sample
  webcam.csv      every Labvanced webcam gaze sample received (message "webcam_gaze")
  events.csv      every other message received from Labvanced
  clock_sync.csv  the tracker clock <-> Unix clock measurements
  merged.csv      Tobii samples, webcam samples and events interleaved in time order, each webcam
                  row with the nearest Tobii sample next to it (written on Stop)

Coordinates: Tobii gaze stays as Tobii delivers it, normalized 0..1 across the screen (origin
top left). Webcam gaze arrives in Labvanced frame units and is converted into the same 0..1
space (and both into pixels), assuming the study runs in fullscreen in the "Zoom / Adaptive" display
mode with the frame size given by --frame-size (default 800x450).

Usage
-----
  start_recording.bat (double-click)                        # the normal way, opens the window
  python labvanced_tobii_bridge.py --mock                   # simulated tracker, to test the study
  python labvanced_tobii_bridge.py --label P01              # Eye Tracker 5
  python labvanced_tobii_bridge.py --no-gui --label P01     # terminal only
  python labvanced_tobii_bridge.py --backend pro --label P01
  python labvanced_tobii_bridge.py --label P01 --frame-size 1600x900
  python labvanced_tobii_bridge.py --help

See README.md for installation, the Labvanced study setup and the Tobii license note.
"""

import argparse
import asyncio
import bisect
import csv
import ctypes
import heapq
import json
import math
import os
import queue
import sys
import threading
import time
from datetime import datetime

import websockets

# ----------------------------------------------------------------------------------------------
# Clock
# ----------------------------------------------------------------------------------------------


class PreciseUnixClock:
    """
    Unix time in nanoseconds with sub-millisecond resolution.

    On Windows, Python < 3.13 reads the wall clock with GetSystemTimeAsFileTime, which only
    advances every ~15.6 ms. In that case the clock is anchored once to a tick edge of the wall
    clock and then advanced with perf_counter (QueryPerformanceCounter), which is precise.
    Python 3.13+ uses GetSystemTimePreciseAsFileTime, so time.time_ns() is used directly.
    """

    def __init__(self):
        self.useWallClockDirectly = sys.platform != "win32" or sys.version_info >= (3, 13)
        self.anchorUnixNs = 0
        self.anchorPerfNs = 0
        if not self.useWallClockDirectly:
            self._anchor()

    def _anchor(self):
        # wait for the coarse wall clock to tick, so the anchor sits on a tick edge
        start = time.time_ns()
        now = start
        while now == start:
            now = time.time_ns()
        self.anchorPerfNs = time.perf_counter_ns()
        self.anchorUnixNs = now

    def now_ns(self):
        if self.useWallClockDirectly:
            return time.time_ns()
        return self.anchorUnixNs + (time.perf_counter_ns() - self.anchorPerfNs)


class GazeSample:
    """One gaze sample in the format all backends deliver. x/y are normalized (0..1, origin top-left)."""

    def __init__(self, timestampUs, valid, x, y, pupilLeftMm=None, pupilRightMm=None):
        self.timestampUs = timestampUs
        self.valid = valid
        self.x = x
        self.y = y
        self.pupilLeftMm = pupilLeftMm
        self.pupilRightMm = pupilRightMm


# ----------------------------------------------------------------------------------------------
# Backend: Tobii Eye Tracker 5 via Stream Engine (ctypes)
# ----------------------------------------------------------------------------------------------

TOBII_ERROR_NO_ERROR = 0
TOBII_ERROR_CONNECTION_FAILED = 5
TOBII_ERROR_TIMED_OUT = 6
TOBII_VALIDITY_VALID = 1
TOBII_FIELD_OF_USE_INTERACTIVE = 1


class TobiiVersion(ctypes.Structure):
    _fields_ = [
        ("major", ctypes.c_int),
        ("minor", ctypes.c_int),
        ("revision", ctypes.c_int),
        ("build", ctypes.c_int),
    ]


class TobiiGazePoint(ctypes.Structure):
    _fields_ = [
        ("timestamp_us", ctypes.c_int64),
        ("validity", ctypes.c_int),
        ("position_xy", ctypes.c_float * 2),
    ]


# TOBII_CALL is __cdecl on Windows, hence CFUNCTYPE
URL_RECEIVER = ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_void_p)
GAZE_POINT_CALLBACK = ctypes.CFUNCTYPE(None, ctypes.POINTER(TobiiGazePoint), ctypes.c_void_p)


class StreamEngineTracker:
    """
    Tobii Eye Tracker 5 through tobii_stream_engine.dll (Stream Engine 4.x, installed with Tobii
    Experience). Gaze points arrive at ~33 Hz, normalized to the screen the tracker is mounted on.
    Callbacks run inside wait_and_process(), i.e. on the tracker thread.
    """

    TIMESYNC_INTERVAL_S = 30.0  # Stream Engine recommends refreshing the device/host time sync every ~30 s

    def __init__(self, dllPath):
        self.lib = ctypes.CDLL(dllPath)
        self.api = ctypes.c_void_p()
        self.device = ctypes.c_void_p()
        self.deviceName = None
        self.version = TobiiVersion()
        self.onSample = None
        self.lastTimesyncPerf = time.perf_counter()
        self._gazeCallbackRef = None  # keeps the ctypes callback alive
        self._declare_prototypes()

    def _declare_prototypes(self):
        lib = self.lib
        lib.tobii_error_message.restype = ctypes.c_char_p
        lib.tobii_error_message.argtypes = [ctypes.c_int]
        prototypes = {
            "tobii_get_api_version": [ctypes.POINTER(TobiiVersion)],
            "tobii_api_create": [ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.c_void_p],
            "tobii_api_destroy": [ctypes.c_void_p],
            "tobii_enumerate_local_device_urls": [ctypes.c_void_p, URL_RECEIVER, ctypes.c_void_p],
            "tobii_device_create": [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)],
            "tobii_device_destroy": [ctypes.c_void_p],
            "tobii_device_reconnect": [ctypes.c_void_p],
            "tobii_update_timesync": [ctypes.c_void_p],
            "tobii_gaze_point_subscribe": [ctypes.c_void_p, GAZE_POINT_CALLBACK, ctypes.c_void_p],
            "tobii_gaze_point_unsubscribe": [ctypes.c_void_p],
            "tobii_wait_for_callbacks": [ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)],
            "tobii_device_process_callbacks": [ctypes.c_void_p],
            "tobii_system_clock": [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int64)],
        }
        for name, argtypes in prototypes.items():
            fn = getattr(lib, name)
            fn.argtypes = argtypes
            fn.restype = ctypes.c_int

    def _check(self, error, what):
        if error != TOBII_ERROR_NO_ERROR:
            message = self.lib.tobii_error_message(error).decode(errors="replace")
            raise RuntimeError("{} failed: {} (error {})".format(what, message, error))

    def connect(self):
        self._check(self.lib.tobii_get_api_version(ctypes.byref(self.version)), "tobii_get_api_version")
        if self.version.major < 4:
            raise RuntimeError(
                "Stream Engine {} is too old, this script needs 4.x (update Tobii Experience)".format(self.versionString())
            )
        self._check(self.lib.tobii_api_create(ctypes.byref(self.api), None, None), "tobii_api_create")

        urls = []

        def on_url(url, userData):
            urls.append(url.decode())

        receiver = URL_RECEIVER(on_url)
        self._check(
            self.lib.tobii_enumerate_local_device_urls(self.api, receiver, None), "tobii_enumerate_local_device_urls"
        )
        if not urls:
            raise RuntimeError("No Tobii eye tracker found. Is it plugged in and shown as ready in Tobii Experience?")
        self.deviceName = urls[0]
        self._check(
            self.lib.tobii_device_create(
                self.api, self.deviceName.encode(), TOBII_FIELD_OF_USE_INTERACTIVE, ctypes.byref(self.device)
            ),
            "tobii_device_create",
        )

    def versionString(self):
        v = self.version
        return "Stream Engine {}.{}.{}.{}".format(v.major, v.minor, v.revision, v.build)

    def subscribe_gaze(self, onSample):
        self.onSample = onSample

        def callback(gazePointPtr, userData):
            p = gazePointPtr.contents
            self.onSample(
                GazeSample(p.timestamp_us, p.validity == TOBII_VALIDITY_VALID, p.position_xy[0], p.position_xy[1])
            )

        self._gazeCallbackRef = GAZE_POINT_CALLBACK(callback)
        self._check(
            self.lib.tobii_gaze_point_subscribe(self.device, self._gazeCallbackRef, None), "tobii_gaze_point_subscribe"
        )

    def wait_and_process(self):
        """Blocks until data arrives (TIMED_OUT after a few hundred ms is normal), then runs the callbacks."""
        devices = (ctypes.c_void_p * 1)(self.device)
        error = self.lib.tobii_wait_for_callbacks(1, devices)
        if error not in (TOBII_ERROR_NO_ERROR, TOBII_ERROR_TIMED_OUT):
            self._check(error, "tobii_wait_for_callbacks")
        error = self.lib.tobii_device_process_callbacks(self.device)
        if error == TOBII_ERROR_CONNECTION_FAILED:
            print("[tobii] connection lost, reconnecting ...")
            self._check(self.lib.tobii_device_reconnect(self.device), "tobii_device_reconnect")
            return
        self._check(error, "tobii_device_process_callbacks")
        if time.perf_counter() - self.lastTimesyncPerf >= self.TIMESYNC_INTERVAL_S:
            self._check(self.lib.tobii_update_timesync(self.device), "tobii_update_timesync")
            self.lastTimesyncPerf = time.perf_counter()

    def system_clock_us(self):
        """Same clock as the gaze timestamp_us values."""
        ts = ctypes.c_int64()
        self._check(self.lib.tobii_system_clock(self.api, ctypes.byref(ts)), "tobii_system_clock")
        return ts.value

    def close(self):
        if self.device:
            self.lib.tobii_gaze_point_unsubscribe(self.device)
            self.lib.tobii_device_destroy(self.device)
            self.device = ctypes.c_void_p()
        if self.api:
            self.lib.tobii_api_destroy(self.api)
            self.api = ctypes.c_void_p()


# ----------------------------------------------------------------------------------------------
# Backend: Tobii Pro trackers via tobii_research
# ----------------------------------------------------------------------------------------------


class TobiiProTracker:
    """
    Tobii Pro screen-based trackers (Spark, Fusion, Nano, Spectrum) through the tobii_research
    package (pip install tobii-research; wheels exist for Python 3.10 only). The SDK calls back on
    its own thread, so samples are queued there and written on the tracker thread.
    """

    def __init__(self):
        import tobii_research  # imported here so the ET5 and mock modes do not need the package

        self.tr = tobii_research
        self.tracker = None
        self.deviceName = None
        self.samples = queue.Queue()
        self.onSample = None

    def connect(self):
        trackers = self.tr.find_all_eyetrackers()
        if not trackers:
            raise RuntimeError("No Tobii Pro eye tracker found (is Tobii Pro Eye Tracker Manager showing it?)")
        self.tracker = trackers[0]
        self.deviceName = "{} {} ({})".format(self.tracker.model, self.tracker.serial_number, self.tracker.address)

    def versionString(self):
        return "tobii_research {}".format(self.tr.__version__)

    def _on_gaze_data(self, d):
        eyes = []
        for side in ("left", "right"):
            if d[side + "_gaze_point_validity"]:
                eyes.append(d[side + "_gaze_point_on_display_area"])
        x = sum(e[0] for e in eyes) / len(eyes) if eyes else float("nan")
        y = sum(e[1] for e in eyes) / len(eyes) if eyes else float("nan")
        pupilLeft = d["left_pupil_diameter"] if d["left_pupil_validity"] else None
        pupilRight = d["right_pupil_diameter"] if d["right_pupil_validity"] else None
        self.samples.put(GazeSample(d["system_time_stamp"], bool(eyes), x, y, pupilLeft, pupilRight))

    def subscribe_gaze(self, onSample):
        self.onSample = onSample
        self.tracker.subscribe_to(self.tr.EYETRACKER_GAZE_DATA, self._on_gaze_data, as_dictionary=True)

    def wait_and_process(self):
        try:
            sample = self.samples.get(timeout=0.2)
        except queue.Empty:
            return
        self.onSample(sample)
        while True:
            try:
                self.onSample(self.samples.get_nowait())
            except queue.Empty:
                return

    def system_clock_us(self):
        """Same clock as the system_time_stamp of the gaze samples."""
        return self.tr.get_system_time_stamp()

    def close(self):
        if self.tracker is not None:
            self.tracker.unsubscribe_from(self.tr.EYETRACKER_GAZE_DATA, self._on_gaze_data)
            self.tracker = None


# ----------------------------------------------------------------------------------------------
# Backend: simulated tracker
# ----------------------------------------------------------------------------------------------


class MockTracker:
    """Simulated tracker (33 Hz like the Eye Tracker 5, gaze circling the screen). No hardware needed."""

    def __init__(self, sampleRateHz=33.0):
        self.interval = 1.0 / sampleRateHz
        self.onSample = None
        self.deviceName = "simulated tracker"
        self.t0 = time.perf_counter()

    def connect(self):
        pass

    def versionString(self):
        return "mock"

    def subscribe_gaze(self, onSample):
        self.onSample = onSample

    def system_clock_us(self):
        return int((time.perf_counter() - self.t0) * 1e6)

    def wait_and_process(self):
        time.sleep(self.interval)
        t = self.system_clock_us()
        phase = t / 1e6 * 0.5 * 2 * math.pi
        self.onSample(GazeSample(t, True, 0.5 + 0.3 * math.cos(phase), 0.5 + 0.3 * math.sin(phase)))

    def close(self):
        pass


# ----------------------------------------------------------------------------------------------
# Recording
# ----------------------------------------------------------------------------------------------


class ClockMapping:
    """
    Latest measured offset between the tracker clock (us) and the Unix clock (ns):
    unixNs = trackerUs * 1000 + offsetNs. Written by the tracker thread, read by the WebSocket thread.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.offsetNs = None

    def set(self, offsetNs):
        with self.lock:
            self.offsetNs = offsetNs

    def get(self):
        with self.lock:
            return self.offsetNs


class Recording:
    """Owns the output folder and the CSV files of one run."""

    GAZE_HEADER = [
        "unix_time_ms",
        "tobii_timestamp_us",
        "tobii_x_norm",
        "tobii_y_norm",
        "tobii_x_px",
        "tobii_y_px",
        "tobii_valid",
        "pupil_left_mm",
        "pupil_right_mm",
    ]
    WEBCAM_HEADER = [
        "unix_time_ms",
        "tobii_timestamp_us",
        "webcam_x_frame",
        "webcam_y_frame",
        "webcam_x_norm",
        "webcam_y_norm",
        "webcam_x_px",
        "webcam_y_px",
        "webcam_confidence",
        "received_unix_ms",
        "processing_lag_ms",
    ]
    EVENT_HEADER = [
        "unix_time_ms",
        "tobii_timestamp_us",
        "labvanced_msg",
        "labvanced_value",
        "labvanced_unix_ms",
        "transfer_delay_ms",
    ]
    SYNC_HEADER = ["unix_before_ms", "tobii_clock_us", "unix_after_ms", "offset_ms", "round_trip_ms"]
    # Tobii columns are filled on "tobii" rows and, on "webcam" rows, with the nearest Tobii sample
    # (tobii_dt_ms = webcam T minus the time of that Tobii sample).
    MERGED_HEADER = (
        ["unix_time_ms", "tobii_timestamp_us", "row_type"]
        + GAZE_HEADER[2:]
        + WEBCAM_HEADER[2:9]
        + ["tobii_dt_ms"]
        + EVENT_HEADER[2:5]
    )

    def __init__(self, outDir, label):
        self.outDir = outDir
        self.stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.label = clean_label(label)
        self.folder = self._folder_for(self.label)
        os.makedirs(self.folder, exist_ok=True)
        self.gazePath = os.path.join(self.folder, "gaze.csv")
        self.webcamPath = os.path.join(self.folder, "webcam.csv")
        self.eventsPath = os.path.join(self.folder, "events.csv")
        self.syncPath = os.path.join(self.folder, "clock_sync.csv")
        self.mergedPath = os.path.join(self.folder, "merged.csv")
        self.gazeFile, self.gazeWriter = self._open(self.gazePath, self.GAZE_HEADER)
        self.webcamFile, self.webcamWriter = self._open(self.webcamPath, self.WEBCAM_HEADER)
        self.eventsFile, self.eventsWriter = self._open(self.eventsPath, self.EVENT_HEADER)
        self.syncFile, self.syncWriter = self._open(self.syncPath, self.SYNC_HEADER)
        self.gazeCount = 0
        self.gazeValidCount = 0
        self.webcamCount = 0
        self.eventCount = 0

    def _folder_for(self, label):
        return os.path.join(self.outDir, "{}_{}".format(self.stamp, label) if label else self.stamp)

    def apply_label(self, label):
        """Renames the run folder to include the label (call after close(), when no file is open)."""
        label = clean_label(label)
        if label == self.label:
            return
        newFolder = self._folder_for(label)
        os.rename(self.folder, newFolder)
        self.folder = newFolder
        self.label = label

    def _open(self, path, header):
        f = open(path, "w", newline="", encoding="utf-8")
        writer = csv.writer(f)
        writer.writerow(header)
        return f, writer

    def close(self):
        for f in (self.gazeFile, self.webcamFile, self.eventsFile, self.syncFile):
            f.close()

    def _read(self, path, rowType):
        with open(path, newline="", encoding="utf-8") as f:
            rows = [dict(row, row_type=rowType) for row in csv.DictReader(f)]
        # webcam rows are written in arrival order, which is not guaranteed to be T order
        rows.sort(key=lambda r: float(r["unix_time_ms"]))
        return rows

    def write_merged(self):
        """Interleaves Tobii samples, webcam samples and events by Unix time."""
        tobiiRows = self._read(self.gazePath, "tobii")
        webcamRows = self._read(self.webcamPath, "webcam")
        eventRows = self._read(self.eventsPath, "event")

        tobiiTimes = [float(r["unix_time_ms"]) for r in tobiiRows]
        for row in webcamRows:
            t = float(row["unix_time_ms"])
            i = bisect.bisect_left(tobiiTimes, t)
            candidates = [j for j in (i - 1, i) if 0 <= j < len(tobiiRows)]
            if not candidates:
                continue
            nearest = min(candidates, key=lambda j: abs(tobiiTimes[j] - t))
            for column in self.GAZE_HEADER[2:]:
                row[column] = tobiiRows[nearest][column]
            row["tobii_dt_ms"] = "{:.3f}".format(t - tobiiTimes[nearest])

        with open(self.mergedPath, "w", newline="", encoding="utf-8") as m:
            out = csv.DictWriter(m, fieldnames=self.MERGED_HEADER, extrasaction="ignore")
            out.writeheader()
            # on equal times: event first, then webcam, then Tobii
            for row in heapq.merge(eventRows, webcamRows, tobiiRows, key=lambda r: float(r["unix_time_ms"])):
                out.writerow(row)


class ScreenGeometry:
    """
    Puts both trackers in Tobii's representation: normalized 0..1 across the screen (origin top
    left), plus screen pixels.

    Labvanced webcam gaze comes in frame units. In the "Zoom / Adaptive" display mode with the study in
    fullscreen, the player scales the frame by s = min(screenW / frameW, screenH / frameH) and
    centers it (PlayerFrame.coordinateTransform); frame_units_to_normalized() inverts that. Only
    the screen's aspect ratio enters the result, so Windows display scaling does not matter. If
    frame and screen have the same aspect ratio, this is simply x / frameW, y / frameH.
    """

    def __init__(self, screenSize, frameSize):
        self.screenSize = screenSize
        self.frameSize = frameSize

    def to_pixels(self, x, y):
        return x * self.screenSize[0], y * self.screenSize[1]

    def frame_units_to_normalized(self, x, y):
        screenW, screenH = self.screenSize
        frameW, frameH = self.frameSize
        scale = min(screenW / frameW, screenH / frameH)  # screen pixels per frame unit
        return 0.5 + (x - frameW / 2) * scale / screenW, 0.5 + (y - frameH / 2) * scale / screenH


def clean_label(label):
    """Keeps only characters that are safe in a folder name."""
    return "".join(c for c in label.strip() if c.isalnum() or c in "-_")


def format_ms(ns):
    return "{:.3f}".format(ns / 1e6)


def format_optional(value, pattern):
    return pattern.format(value) if value is not None else ""


def looks_like_unix_ms(value):
    # Labvanced "Trigger Timestamp (Unixtime)" / "Current Time: UNIX Timestamp" values (years 2001..2286)
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 1e12 <= value < 1e13


class TrackerThread(threading.Thread):
    """Reads gaze samples, writes gaze.csv and measures the tracker <-> Unix clock offset once per second."""

    SYNC_INTERVAL_S = 1.0

    def __init__(self, tracker, recording, clock, mapping, geometry):
        super().__init__(daemon=True)
        self.tracker = tracker
        self.recording = recording
        self.clock = clock
        self.mapping = mapping
        self.geometry = geometry
        self.stopEvent = threading.Event()
        self.ready = threading.Event()
        self.error = None
        self.lastSyncPerf = 0.0

    def _measure_offset(self):
        # three reads, keep the one with the shortest round trip
        best = None
        for _ in range(3):
            before = self.clock.now_ns()
            trackerUs = self.tracker.system_clock_us()
            after = self.clock.now_ns()
            if best is None or after - before < best[2] - best[0]:
                best = (before, trackerUs, after)
        before, trackerUs, after = best
        offsetNs = (before + after) // 2 - trackerUs * 1000
        self.mapping.set(offsetNs)
        self.recording.syncWriter.writerow(
            [format_ms(before), trackerUs, format_ms(after), format_ms(offsetNs), format_ms(after - before)]
        )
        self.lastSyncPerf = time.perf_counter()

    def _on_sample(self, s):
        unixMs = format_ms(s.timestampUs * 1000 + self.mapping.get())
        xPx = yPx = ""
        if s.valid and self.geometry.screenSize:
            xPx, yPx = ("{:.1f}".format(v) for v in self.geometry.to_pixels(s.x, s.y))
        self.recording.gazeWriter.writerow(
            [
                unixMs,
                s.timestampUs,
                "{:.5f}".format(s.x),
                "{:.5f}".format(s.y),
                xPx,
                yPx,
                1 if s.valid else 0,
                format_optional(s.pupilLeftMm, "{:.3f}"),
                format_optional(s.pupilRightMm, "{:.3f}"),
            ]
        )
        self.recording.gazeCount += 1
        if s.valid:
            self.recording.gazeValidCount += 1

    def run(self):
        try:
            self.tracker.connect()
            self._measure_offset()  # before the first sample, so every sample has an offset
            self.tracker.subscribe_gaze(self._on_sample)
            self.ready.set()
            while not self.stopEvent.is_set():
                self.tracker.wait_and_process()
                if time.perf_counter() - self.lastSyncPerf >= self.SYNC_INTERVAL_S:
                    self._measure_offset()
                    self.recording.gazeFile.flush()
                    self.recording.syncFile.flush()
        except Exception as err:  # reported to the main thread, which stops the script
            self.error = err
            self.ready.set()
        finally:
            self.tracker.close()


class LabvancedServer:
    """
    WebSocket server that the Labvanced study connects to. Webcam gaze samples (message webcamMsg,
    value [X,Y,T,C] or [X,Y,T]) go to webcam.csv, every other message to events.csv.
    """

    def __init__(self, recording, clock, mapping, trackerThread, echo, webcamMsg, geometry):
        self.recording = recording
        self.clock = clock
        self.mapping = mapping
        self.trackerThread = trackerThread
        self.echo = echo
        self.webcamMsg = webcamMsg
        self.geometry = geometry
        self.openConnections = 0  # read by the window
        self.everConnected = False

    def _status(self):
        if self.trackerThread.error is not None:
            return "error: {}".format(self.trackerThread.error)
        return "recording"

    async def on_connect(self, websocket):
        print("[labvanced] study connected")
        self.openConnections += 1
        self.everConnected = True
        try:
            async for message in websocket:
                receivedNs = self.clock.now_ns()  # first thing: the receive time
                data = self._write_event(message, receivedNs)
                # A study can ask whether the tracker records: "Send To Websocket" with message "tobii_status".
                # The answer arrives as a "Websocket Trigger" with message "tobii_status" and Data "recording".
                if isinstance(data, dict) and data.get("msg") == "tobii_status":
                    await websocket.send(json.dumps({"msg": "tobii_status", "value": self._status()}))
        finally:
            self.recording.eventsFile.flush()
            self.recording.webcamFile.flush()
            self.openConnections -= 1
            print("[labvanced] study disconnected")

    def _write_webcam_sample(self, value, receivedNs):
        x, y, tMs = value[0], value[1], value[2]
        confidence = value[3] if len(value) > 3 else None
        trackerUs = int((tMs * 1e6 - self.mapping.get()) // 1000)
        xNorm = yNorm = xPx = yPx = ""
        if x is not None and y is not None and self.geometry.frameSize:
            nx, ny = self.geometry.frame_units_to_normalized(x, y)
            px, py = self.geometry.to_pixels(nx, ny)
            xNorm, yNorm, xPx, yPx = "{:.5f}".format(nx), "{:.5f}".format(ny), "{:.1f}".format(px), "{:.1f}".format(py)
        self.recording.webcamWriter.writerow(
            [
                "{:.3f}".format(tMs),
                trackerUs,
                format_optional(x, "{}"),
                format_optional(y, "{}"),
                xNorm,
                yNorm,
                xPx,
                yPx,
                format_optional(confidence, "{}"),
                format_ms(receivedNs),
                "{:.3f}".format(receivedNs / 1e6 - tMs),
            ]
        )
        if self.recording.webcamCount == 0:
            print("[webcam] receiving webcam gaze samples")
        self.recording.webcamCount += 1

    def _write_event(self, message, receivedNs):
        data = None
        if isinstance(message, bytes):
            msg, value = "binary", "<{} bytes>".format(len(message))
        else:
            try:
                data = json.loads(message)
                msg, value = data.get("msg", ""), data.get("value")
            except (ValueError, AttributeError):
                msg, value = "raw", message
        # a malformed webcam sample falls through and is kept in events.csv, so nothing is lost
        if msg == self.webcamMsg and isinstance(value, list) and len(value) >= 3 and looks_like_unix_ms(value[2]):
            self._write_webcam_sample(value, receivedNs)
            return data
        trackerUs = (receivedNs - self.mapping.get()) // 1000
        labvancedMs = value if looks_like_unix_ms(value) else ""
        delayMs = "{:.3f}".format(receivedNs / 1e6 - labvancedMs) if labvancedMs != "" else ""
        valueText = value if isinstance(value, str) else json.dumps(value)
        self.recording.eventsWriter.writerow([format_ms(receivedNs), trackerUs, msg, valueText, labvancedMs, delayMs])
        self.recording.eventsFile.flush()
        self.recording.eventCount += 1
        if self.echo:
            print("[event] {:<24} value={}".format(msg, valueText))
        return data


async def serve(server, host, port, stopEvent):
    async with websockets.serve(server.on_connect, host, port):
        print("[labvanced] waiting for the study on ws://{}:{}/".format(host, port))
        while not stopEvent.is_set():
            await asyncio.sleep(0.2)


DEFAULT_FRAME_SIZE = "800x450"  # Labvanced's default frame (16:9 desktop preset), width x height in frame units


class SetupError(Exception):
    """A problem before the recording could start (shown to the user, no traceback)."""


def parse_size(text):
    if not text:
        return None
    w, h = text.lower().split("x")
    return int(w), int(h)


def detect_screen_size():
    """Resolution of the primary monitor in physical pixels (Windows only, otherwise None)."""
    if sys.platform != "win32":
        return None
    user32 = ctypes.windll.user32
    user32.SetProcessDPIAware()  # report physical pixels, not the Windows-scaled ones
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def default_dll_path():
    return os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Tobii", "Tobii EyeX", "tobii_stream_engine.dll")


def create_tracker(args):
    if args.mock:
        return MockTracker()
    if args.backend == "pro":
        return TobiiProTracker()
    if not os.path.isfile(args.dll):
        raise SetupError(
            "tobii_stream_engine.dll not found at\n{}\n\nPass its location with --dll (see README, section 3.3).".format(args.dll)
        )
    return StreamEngineTracker(args.dll)


class BridgeSession:
    """
    One recording session: starts recording the tracker as soon as it is created, runs the
    WebSocket server for the study on its own thread, and saves everything on stop().
    Used by both the window and the terminal mode.
    """

    def __init__(self, args):
        screenSize = parse_size(args.screen_size) or detect_screen_size()
        if screenSize is None:
            raise SetupError("Could not detect the screen resolution, pass it with --screen-size, e.g. --screen-size 1920x1080")
        self.geometry = ScreenGeometry(screenSize, parse_size(args.frame_size))
        self.tracker = create_tracker(args)
        self.clock = PreciseUnixClock()
        self.mapping = ClockMapping()
        self.recording = Recording(args.out_dir, args.label)
        self.trackerThread = TrackerThread(self.tracker, self.recording, self.clock, self.mapping, self.geometry)
        self.server = LabvancedServer(
            self.recording,
            self.clock,
            self.mapping,
            self.trackerThread,
            echo=not args.quiet,
            webcamMsg=args.webcam_msg,
            geometry=self.geometry,
        )
        self.host = args.host
        self.port = args.port
        self.stopEvent = threading.Event()
        self.serverThread = threading.Thread(target=self._run_server, daemon=True)
        self.serverError = None
        self.startedAt = None
        self.stopped = False
        self.summary = None

        print("[geometry] screen {}x{} px, Labvanced frame {}x{} units".format(*(screenSize + self.geometry.frameSize)))
        self.trackerThread.start()
        self.trackerThread.ready.wait(timeout=15)
        if self.trackerThread.error is not None or not self.trackerThread.ready.is_set():
            self.trackerThread.stopEvent.set()
            self.recording.close()
            raise SetupError("The eye tracker could not start:\n{}".format(self.trackerThread.error or "timeout"))
        self.startedAt = datetime.now()
        print("[tobii] connected to {} ({})".format(self.tracker.deviceName, self.tracker.versionString()))
        print("[rec] writing to {}".format(os.path.abspath(self.recording.folder)))
        self.serverThread.start()

    def _run_server(self):
        try:
            asyncio.run(serve(self.server, self.host, self.port, self.stopEvent))
        except Exception as err:  # e.g. the port is already in use; shown by the window / terminal
            self.serverError = err
            print("[labvanced] WebSocket server stopped: {}".format(err))

    def is_running(self):
        return not self.stopped and self.serverThread.is_alive() and self.trackerThread.is_alive()

    def stop(self, label=None):
        """Stops both streams, writes merged.csv, applies the label to the folder name. Returns a summary."""
        if not self.stopped:
            self.stopped = True
            self.stopEvent.set()
            self.trackerThread.stopEvent.set()
            self.serverThread.join(timeout=3)
            self.trackerThread.join(timeout=3)
            self.recording.close()
            self.recording.write_merged()
            if label is not None:
                self.recording.apply_label(label)
            self.summary = "{} Tobii samples, {} webcam samples, {} events".format(
                self.recording.gazeCount, self.recording.webcamCount, self.recording.eventCount
            )
            print("[rec] " + self.summary)
            print("[rec] compare the webcam sample count with the Labvanced export to check that none were lost")
            print("[rec] files in {}".format(os.path.abspath(self.recording.folder)))
        return self.summary


# ----------------------------------------------------------------------------------------------
# Window
# ----------------------------------------------------------------------------------------------


class RateMeter:
    """Samples per second of a growing counter, over the last ~1 s."""

    WINDOW_S = 1.0

    def __init__(self):
        self.history = []  # (perf_counter, count)

    def update(self, count):
        now = time.perf_counter()
        self.history.append((now, count))
        while len(self.history) > 2 and now - self.history[1][0] >= self.WINDOW_S:
            self.history.pop(0)
        t0, c0 = self.history[0]
        return (count - c0) / (now - t0) if now - t0 >= self.WINDOW_S * 0.5 else None


class StatusRow:
    """One line of the window: colored dot, name, status text and a detail line."""

    COLORS = {"ok": "#2e9e44", "warn": "#e69500", "error": "#d23c3c", "idle": "#9aa0a6"}

    def __init__(self, tk, parent, row, name):
        self.dot = tk.Canvas(parent, width=18, height=18, highlightthickness=0)
        self.oval = self.dot.create_oval(2, 2, 16, 16, fill=self.COLORS["idle"], outline="")
        self.dot.grid(row=row, column=0, rowspan=2, sticky="n", padx=(0, 10), pady=(4, 0))
        tk.Label(parent, text=name, font=("TkDefaultFont", 11, "bold"), anchor="w").grid(row=row, column=1, sticky="w")
        self.text = tk.Label(parent, anchor="w", font=("TkDefaultFont", 11))
        self.text.grid(row=row, column=2, sticky="w", padx=(12, 0))
        # two lines reserved, so the window does not jump when a status text gets longer
        self.detail = tk.Label(parent, anchor="nw", fg="#666666", wraplength=520, justify="left", height=2)
        self.detail.grid(row=row + 1, column=1, columnspan=2, sticky="w", pady=(0, 10))

    def set(self, state, text, detail=""):
        self.dot.itemconfigure(self.oval, fill=self.COLORS[state])
        self.text.configure(text=text)
        self.detail.configure(text=detail)


class BridgeWindow:
    """
    Status window. Recording starts with the program (no start button to forget); the window
    shows whether the Tobii stream, the study connection and the webcam stream are alive, where
    the files go, and has the stop button.
    """

    REFRESH_MS = 500

    def __init__(self, session, args):
        import tkinter as tk
        from tkinter import messagebox

        self.tk = tk
        self.messagebox = messagebox
        self.session = session
        self.port = args.port
        self.tobiiRate = RateMeter()
        self.tobiiValidRate = RateMeter()
        self.webcamRate = RateMeter()

        self.root = tk.Tk()
        self.root.title("Labvanced + Tobii recorder")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        frame = tk.Frame(self.root, padx=20, pady=16)
        frame.pack(fill="both", expand=True)

        self.header = tk.Label(frame, font=("TkDefaultFont", 14, "bold"), anchor="w")
        self.header.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 14))

        self.tobiiRow = StatusRow(tk, frame, 1, "Tobii eye tracker")
        self.studyRow = StatusRow(tk, frame, 3, "Labvanced study")
        self.webcamRow = StatusRow(tk, frame, 5, "Webcam gaze")

        tk.Frame(frame, height=1, bg="#dddddd").grid(row=7, column=0, columnspan=3, sticky="ew", pady=(4, 12))

        tk.Label(frame, text="Participant ID", anchor="w").grid(row=8, column=1, sticky="w")
        self.labelVar = tk.StringVar(value=session.recording.label)
        self.labelEntry = tk.Entry(frame, textvariable=self.labelVar, width=20)
        self.labelEntry.grid(row=8, column=2, sticky="w", padx=(12, 0))
        tk.Label(frame, text="can be typed any time, the folder name gets it on stop", fg="#666666").grid(
            row=9, column=2, sticky="w", padx=(12, 0), pady=(0, 8)
        )

        self.folderCaption = tk.Label(frame, text="Saving to", anchor="w")
        self.folderCaption.grid(row=10, column=1, sticky="nw")
        self.folderLabel = tk.Label(frame, anchor="w", justify="left", wraplength=520)
        self.folderLabel.grid(row=10, column=2, sticky="w", padx=(12, 0))
        tk.Button(frame, text="Open folder", command=self._open_folder).grid(row=11, column=2, sticky="w", padx=(12, 0), pady=(4, 14))

        self.stopButton = tk.Button(
            frame, text="Stop recording and save", font=("TkDefaultFont", 12, "bold"), command=self._on_stop, padx=16, pady=8
        )
        self.stopButton.grid(row=12, column=0, columnspan=3, sticky="ew")
        self.summaryLabel = tk.Label(frame, anchor="w", justify="left", wraplength=560)
        self.summaryLabel.grid(row=13, column=0, columnspan=3, sticky="w", pady=(10, 0))

        self._refresh()

    def run(self):
        self.root.mainloop()

    # -- status -----------------------------------------------------------------------------

    def _refresh(self):
        if self.session.stopped:
            return
        rec = self.session.recording
        elapsed = datetime.now() - self.session.startedAt
        self.header.configure(
            text="Recording since {}   ({})".format(self.session.startedAt.strftime("%H:%M:%S"), str(elapsed).split(".")[0])
        )
        self.folderLabel.configure(text=os.path.abspath(rec.folder))
        self._refresh_tobii(rec)
        self._refresh_study(rec)
        self._refresh_webcam(rec)
        self.root.after(self.REFRESH_MS, self._refresh)

    def _refresh_tobii(self, rec):
        tracker = self.session.tracker
        detail = "{} ({}) · {} samples recorded".format(tracker.deviceName, tracker.versionString(), rec.gazeCount)
        rate = self.tobiiRate.update(rec.gazeCount)
        validRate = self.tobiiValidRate.update(rec.gazeValidCount)
        error = self.session.trackerThread.error
        if error is not None:
            self.tobiiRow.set("error", "Stopped with an error", str(error))
        elif rate is None:
            self.tobiiRow.set("idle", "Starting ...", detail)
        elif rate == 0:
            self.tobiiRow.set("warn", "Connected, but no samples in the last second", detail)
        elif validRate == 0:
            self.tobiiRow.set(
                "warn", "Recording, but no eyes detected · {:.0f} samples/s".format(rate), "Is the participant in front of the tracker? " + detail
            )
        else:
            self.tobiiRow.set(
                "ok", "Recording · {:.0f} samples/s · {:.0f} % valid".format(rate, 100 * validRate / rate), detail
            )

    def _refresh_study(self, rec):
        server = self.session.server
        if self.session.serverError is not None:
            self.studyRow.set(
                "error",
                "WebSocket server stopped",
                "{}\nIs another copy of this program still running (port {})?".format(self.session.serverError, self.port),
            )
        elif server.openConnections > 0:
            self.studyRow.set("ok", "Connected · {} events".format(rec.eventCount), "ws://localhost:{}/".format(self.port))
        elif server.everConnected:
            self.studyRow.set(
                "warn",
                "Disconnected · {} events".format(rec.eventCount),
                "Normal when the study has ended or its tab was closed. The study does not reconnect by itself.",
            )
        else:
            self.studyRow.set(
                "idle",
                "Waiting for the study",
                "Open the study in Chrome now (Chrome asks once to 'access other apps and services': click Allow).",
            )

    def _refresh_webcam(self, rec):
        server = self.session.server
        rate = self.webcamRate.update(rec.webcamCount)
        total = "{} samples received".format(rec.webcamCount)
        if rec.webcamCount > 0 and rate:
            self.webcamRow.set("ok", "Receiving · {:.0f} samples/s".format(rate), total)
        elif rec.webcamCount > 0:
            self.webcamRow.set(
                "warn" if server.openConnections > 0 else "idle",
                "No samples in the last second",
                total + " · normal on frames without eye tracking or after the study ended",
            )
        elif server.openConnections > 0:
            self.webcamRow.set("idle", "No samples yet", "They start once Labvanced eye tracking runs (after its calibration).")
        else:
            self.webcamRow.set("idle", "Waiting for the study")

    # -- actions ----------------------------------------------------------------------------

    def _open_folder(self):
        path = os.path.abspath(self.session.recording.folder)
        if sys.platform == "win32":
            os.startfile(path)
        else:
            import subprocess

            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])

    def _on_stop(self):
        if self.session.stopped:
            self.root.destroy()
            return
        self.stopButton.configure(text="Saving ...", state="disabled")
        self.root.update_idletasks()
        self.session.stop(self.labelVar.get())
        rec = self.session.recording
        self.tobiiRow.set("idle", "Stopped · {} samples saved".format(rec.gazeCount))
        self.studyRow.set("idle", "Closed · {} events saved".format(rec.eventCount))
        self.webcamRow.set("idle", "Stopped · {} samples saved".format(rec.webcamCount))
        self.header.configure(text="Recording stopped and saved")
        self.folderCaption.configure(text="Saved in")
        self.folderLabel.configure(text=os.path.abspath(rec.folder))
        self.labelEntry.configure(state="disabled")
        self.summaryLabel.configure(
            text="merged.csv is written. Compare the {} webcam samples with the Labvanced export "
            "to check that none were lost.".format(rec.webcamCount)
        )
        self.stopButton.configure(text="Close", state="normal")

    def _on_close(self):
        if self.session.stopped:
            self.root.destroy()
        elif self.messagebox.askokcancel("Stop recording?", "Stop the recording and save the files?", parent=self.root):
            self.session.stop(self.labelVar.get())
            self.root.destroy()


def show_setup_error(message, useWindow):
    print("Could not start: {}".format(message))
    if useWindow:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Labvanced + Tobii recorder", message)
        root.destroy()


def build_parser():
    parser = argparse.ArgumentParser(description="Record Tobii gaze data together with Labvanced events.")
    parser.add_argument("--backend", choices=["et5", "pro"], default="et5", help="et5 = Eye Tracker 5 (Stream Engine), pro = Tobii Pro trackers (tobii_research)")
    parser.add_argument("--dll", default=default_dll_path(), help="path to tobii_stream_engine.dll (et5 backend)")
    parser.add_argument("--host", default="localhost", help="WebSocket host (default: localhost)")
    parser.add_argument("--port", type=int, default=8081, help="WebSocket port, same as in the Labvanced study settings (default: 8081)")
    parser.add_argument("--out-dir", default="recordings", help="folder for the recordings (default: ./recordings)")
    parser.add_argument("--label", default="", help="added to the run folder name, e.g. a participant id")
    parser.add_argument(
        "--screen-size",
        default="",
        help="resolution of the screen the tracker is mounted on, e.g. 1920x1080 (default: primary monitor, detected)",
    )
    parser.add_argument(
        "--frame-size",
        default=DEFAULT_FRAME_SIZE,
        help="frame size of the Labvanced study in frame units, width x height (default: {}), used to convert the webcam gaze to Tobii's 0..1 screen coordinates".format(
            DEFAULT_FRAME_SIZE
        ),
    )
    parser.add_argument("--mock", action="store_true", help="simulate a tracker (no hardware needed)")
    parser.add_argument("--quiet", action="store_true", help="do not print each event")
    parser.add_argument("--webcam-msg", default="webcam_gaze", help="message name of the webcam gaze samples (default: webcam_gaze)")
    parser.add_argument("--no-gui", action="store_true", help="no window, run in the terminal only (stop with Ctrl+C)")
    return parser


def main():
    args = build_parser().parse_args()
    useWindow = not args.no_gui

    try:
        session = BridgeSession(args)
    except SetupError as err:
        show_setup_error(str(err), useWindow)
        sys.exit(1)

    if useWindow:
        window = BridgeWindow(session, args)
        try:
            window.run()
        finally:
            session.stop()  # no-op if the window already stopped it
        return

    print("Press Ctrl+C to stop the recording.")
    try:
        while session.is_running():
            time.sleep(0.3)
    except KeyboardInterrupt:
        pass
    finally:
        session.stop()


if __name__ == "__main__":
    main()
