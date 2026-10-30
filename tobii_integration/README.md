# Labvanced + Tobii Eye Tracker 5: parallel recording

`labvanced_tobii_bridge.py` lets you record a **Tobii Eye Tracker 5** and **Labvanced webcam
eye tracking** at the same time, in one session, on one time axis.

While your Labvanced study runs in the browser, the script:

* records every gaze sample of the Tobii Eye Tracker 5,
* receives the events your study sends (frame starts, clicks, responses, ...),
* receives every Labvanced webcam gaze sample,
* and writes everything into one table (`merged.csv`), sorted by time. Each webcam sample sits
  next to the nearest Tobii sample, with both converted into the same screen coordinates.

A small window shows whether the Tobii stream, the study and the webcam stream are running, where
the files are saved, and has the **Stop** button. Recording starts as soon as you open the program;
there is no start button to forget.

> **Status: mostly untested.** So far this program has only been tested with a simulated eye
> tracker, not with a real Tobii Eye Tracker 5. Please test it extensively before you use it for
> data collection, especially by looking closely at the merged data output (`merged.csv`) of a
> few pilot sessions (see [section 12](#12-recommended-pilot-check)).

```
  Browser: your Labvanced study                          Same computer
  (webcam eye tracking runs here)
                                       WebSocket
  "Send To Websocket" actions  ----  ws://localhost:8081  ---->  labvanced_tobii_bridge.py
     - events (frame start, click, ...)                              |        ^
     - webcam gaze samples [X,Y,T,C]                                  |        | USB
                                                                      v        |
                                                   recordings/...   Tobii Eye Tracker 5
                                                   gaze.csv, webcam.csv, events.csv, merged.csv
```

Contents:

1. [Before you start: Tobii's license](#1-before-you-start-tobiis-license)
2. [What you need](#2-what-you-need)
3. [Installation](#3-installation-one-time)
4. [Setting up the Labvanced study](#4-setting-up-the-labvanced-study-one-time)
5. [Testing without the eye tracker](#5-testing-without-the-eye-tracker)
6. [Running a session](#6-running-a-session)
7. [Command line options](#7-command-line-options)
8. [Output files](#8-output-files)
9. [Coordinates: how the two trackers are made comparable](#9-coordinates-how-the-two-trackers-are-made-comparable)
10. [Timing: how the clocks are aligned](#10-timing-how-the-clocks-are-aligned)
11. [Analysis example (Python)](#11-analysis-example-python)
12. [Recommended pilot check](#12-recommended-pilot-check)
13. [Troubleshooting](#13-troubleshooting)
14. [Using a Tobii Pro tracker instead](#14-using-a-tobii-pro-tracker-instead)

---

## 1. Before you start: Tobii's license

The Tobii Eye Tracker 5 is sold as a gaming device. Tobii's end-user license treats storing gaze
data for research ("Analytical Use", which explicitly includes behavior research and usability
testing) as a use that requires a **special license from Tobii**. Tobii's research SDK (Tobii Pro
SDK) does not support the Eye Tracker 5.

Before collecting study data with the Eye Tracker 5, please ask Tobii's licensing team for
written permission for research use (contact via https://gaming.tobii.com/terms-of-sales/).
If that is not possible, Tobii Pro trackers (e.g. the Tobii Pro Spark) are licensed for research,
and this script supports them too (see [section 14](#14-using-a-tobii-pro-tracker-instead)).

Tobii, Tobii Eye Tracker 5 and Tobii Pro are trademarks of Tobii AB. This program is not
affiliated with, endorsed by or supported by Tobii. It contains no Tobii software: it uses the
Tobii software that Tobii Experience (or the Tobii Pro SDK) installed on your computer.

## 2. What you need

* A **Windows** PC (Windows 10 or 11) with the Tobii Eye Tracker 5 mounted on the screen you run
  the study on.
* **Tobii Experience** (Tobii's app for the Eye Tracker 5).
* **Python 3.13 or newer, 64-bit**.
* **Google Chrome** (or another Chromium browser) to run the Labvanced study.
* A webcam for Labvanced eye tracking (a built-in laptop camera works).
* The files of this package, in a folder of their own, e.g. `C:\tobii_bridge\`:
  * `labvanced_tobii_bridge.py`: the program
  * `start_recording.bat`: double-click to start a recording
  * `test_without_tracker.bat`: double-click to test with a simulated tracker
  * `README.md`: this documentation

## 3. Installation (one time)

### 3.1 Tobii Experience and calibration

1. Install **Tobii Experience** (from the Microsoft Store or Tobii's website) and
   plug in the Eye Tracker 5.
2. In Tobii Experience, set up the tracker for the screen it is mounted on, and **run the
   calibration**. The script uses this calibration; without it all gaze points come out wrong.
   Re-calibrate in Tobii Experience for every new participant.

### 3.2 Python

1. Download Python 3.13 (or newer) for Windows, 64-bit, from https://www.python.org/downloads/.
2. In the installer, tick **"Add python.exe to PATH"**, then click "Install Now". (The default
   installation includes "tcl/tk", which the window needs; do not remove it under "Customize".)

That is all. The one extra Python package the program needs (`websockets`) is installed
automatically by `start_recording.bat` the first time you start it (this needs an internet
connection once).

> Why 3.13: older Python versions on Windows read the computer clock in steps of about 15 ms.
> The script works around that, but Python 3.13+ reads the clock precisely and also follows
> clock adjustments the same way the browser does (see [section 10](#10-timing-how-the-clocks-are-aligned)).

### 3.3 Check that the script finds the tracker

The script talks to the tracker through `tobii_stream_engine.dll`, which Tobii Experience
installs. By default it looks for it in:

```
C:\Program Files\Tobii\Tobii EyeX\tobii_stream_engine.dll
```

Test it: sit in front of the tracker and **double-click `start_recording.bat`**. A black console
window opens (it shows a technical log, leave it open) and then the recorder window:

* `Tobii eye tracker` should be green: `Recording · 33 samples/s · ... % valid`.
* `Labvanced study` and `Webcam gaze` are grey (`Waiting for the study`), which is correct, as no
  study is open yet.

Click **Stop recording and save**, then **Close**. A test folder was created in
`C:\tobii_bridge\recordings\`; you can delete it.

If instead a message says `tobii_stream_engine.dll not found`, search for
`tobii_stream_engine.dll` in Windows Explorer (in `C:\Program Files\Tobii\` and
`C:\Program Files (x86)\Tobii\`). Then open `start_recording.bat` with Notepad (right-click →
Edit) and add its location to the line `python labvanced_tobii_bridge.py %*` near the end:

```
python labvanced_tobii_bridge.py --dll "C:\Program Files\Tobii\...\tobii_stream_engine.dll" %*
```

## 4. Setting up the Labvanced study (one time)

### 4.1 WebSocket connection

**Study Settings → Special Features → `WebSocket Connection`**: tick the checkbox and keep the
defaults:

* `WebSocket Address`: `ws://localhost`
* `Port`: `8081`

### 4.2 Display settings

The script converts the webcam gaze into the Tobii coordinate system. For that it has to know how
the study is shown on the screen:

* **Study Settings → Main → Defaults**:
  * `Display Mode`: **`Zoom / Adaptive`** (the default). The other modes (`Fixed in Pixels`,
    `Fixed in Millimeter`, `Fixed in Visual Degree`) are not supported by the conversion.
  * `Default Frame Size`: note the size, e.g. **800 x 450** (the default). If it is not
    800 x 450, open `start_recording.bat` with Notepad and add `--frame-size <width>x<height>` to
    the line `python labvanced_tobii_bridge.py %*` near the end, e.g. `python labvanced_tobii_bridge.py --frame-size 1600x900 %*`.
* **Study Settings → Controls → Screen**: tick **`Start Study in Fullscreen`**.
* If you changed `Display Mode` or the frame size for individual tasks in the task editor, use
  the same values for all tasks you record.

Run the study on the screen the Eye Tracker 5 is mounted on.

### 4.3 Send the webcam gaze samples to the script

When you enable eye tracking in a task, Labvanced offers to create an event
**`Record gaze timeseries [X,Y,T,C]`** (on all frames). Use that event (or your own event with the
`Eyetracking Gaze` trigger that records the `Coord. + Time + Confidence [X,Y,T,C] Array` into an
array variable) and add **one action** at the end of it:

* **`API Actions` → `Send To Websocket`**
  * `Data Type`: `Text / JSON`
  * `Trigger / message to send`: **`webcam_gaze`** (exactly like this)
  * `Send Variable`: the array variable the event records the `[X,Y,T,C]` array into

So the event does two things for every webcam sample: record it in Labvanced as usual, and send
the same `[X,Y,T,C]` array to the script. The Labvanced recording stays complete and remains your
backup and reference.

The script uses `T` from the array (the time the camera took the picture), not the time the
message arrived, so the transfer time does not affect the timing.

### 4.4 Send events (markers)

For every moment you want marked in the recording (stimulus onset, response, ...), add an event:

1. **Trigger**: e.g. `Frame Start Trigger`, a mouse click on an object, a key press, a button.
2. **Action 1**: `Set / Record Variable`: set a numeric variable (create one, e.g. `lv_time`) to
   the trigger's `Trigger Timestamp (Unixtime)`.
3. **Action 2**: `API Actions` → `Send To Websocket`:
   * `Data Type`: `Text / JSON`
   * `Trigger / message to send`: a label, e.g. `frame_start_image` or `click_left`
   * `Send Variable`: `lv_time`

The label becomes the event name in the recording, and the variable gives Labvanced's own time of
the event. You can also send other variables instead (trial number, condition); their value is
stored as is. Then the event time is when the script received it, typically less than 1 ms later.

### 4.5 Optional: only start when the tracker records

On a start frame, add:

* an event with `Frame Start Trigger` → `Send To Websocket` with message `tobii_status`,
* an event with **`API/External Trigger` → `Websocket Trigger`**, message `tobii_status`. The
  script answers with `Data` = `recording` once it is recording. Use this event to continue to
  the next frame (or show a message to the experimenter if it never comes).

## 5. Testing without the eye tracker

To check the study setup without the tracker (or on a computer without Tobii Experience),
double-click **`test_without_tracker.bat`**. It simulates a tracker (gaze circling around the
screen); everything else works exactly as in a real session.

Open the study and watch the window: `Labvanced study` should turn green (`Connected`), the event
count should go up with each event, and `Webcam gaze` should turn green (`Receiving · ~30
samples/s`) once the Labvanced eye tracking runs. Then click Stop, open the folder and check that
`events.csv` contains your events and `webcam.csv` your webcam samples.

## 6. Running a session

Checklist before each participant:

1. Tracker plugged in, Tobii Experience shows it ready, **calibrated for this participant**.
2. Close other programs that use the webcam.

Then:

1. **Double-click `start_recording.bat`.** The recording starts right away. In the window:
   * type the **participant ID** into the `Participant ID` field (any time during the session;
     the folder gets the ID when you stop),
   * check that `Tobii eye tracker` is **green**.
2. **Open the study** in Chrome on the same computer.
   * The first time, Chrome asks whether labvanced.com may *"access other apps and services on
     this device"*: click **Allow**. This is the connection to the recorder.
   * `Labvanced study` turns **green** (`Connected · N events`), and the event count goes up as the
     study runs.
3. Run the study as usual (including the Labvanced webcam calibration). Once the Labvanced eye
   tracking runs, `Webcam gaze` turns **green** (`Receiving · ~30 samples/s`).
4. When the study is finished, click **Stop recording and save**. The window then shows how many
   Tobii samples, webcam samples and events were saved, and where (`Open folder`). Click
   **Close**.

What the window shows:

| Line | Green | Orange | Grey | Red |
|---|---|---|---|---|
| `Tobii eye tracker` | recording, with samples/s and % valid samples | connected but no samples, or no eyes detected (participant not in front of the tracker) | starting | stopped with an error (message shown below it) |
| `Labvanced study` | study connected, with the number of events | study disconnected: normal at the end of the study, otherwise see below | waiting for the study to be opened | the connection for the study could not be opened (e.g. the recorder runs twice) |
| `Webcam gaze` | receiving webcam samples, with samples/s | no samples in the last second although they came before (frames without eye tracking, or the end of the study) | no samples yet (before the Labvanced eye tracking starts) | |

Important:

* **Keep the recorder open** for the whole session, and open the study only after the recorder.
  The study connects once, at its start, and does not reconnect. If the recorder is closed in the
  middle, the rest of the session is not recorded by the recorder (the Labvanced data recording
  itself is not affected). If `Labvanced study` turns orange (`Disconnected`) before the study
  has ended, the tab was closed or reloaded: the rest of that session is missing from the
  recorder.
* One recorder run = one participant session. Close it and double-click `start_recording.bat`
  again for the next participant.
* Closing the window with the X also stops and saves (after asking).

## 7. Command line options

Options go on the line `python labvanced_tobii_bridge.py %*` near the end of `start_recording.bat` (open it with Notepad), before `%*`, or
after the script name when you start it from a terminal (`python labvanced_tobii_bridge.py ...`).

| Option | Default | Meaning |
|---|---|---|
| `--label P01` | none | participant ID for the folder name (can also be typed in the window) |
| `--frame-size 800x450` | `800x450` | frame size of the Labvanced study (width x height, frame units), see 4.2 |
| `--screen-size 1920x1080` | detected | resolution of the screen with the tracker; only needed if the study runs on a second monitor |
| `--out-dir recordings` | `recordings` | folder in which the run folders are created |
| `--dll "C:\...\tobii_stream_engine.dll"` | Tobii Experience path | location of the Tobii DLL, see 3.3 |
| `--port 8081` | `8081` | WebSocket port; must match the study settings (4.1) |
| `--webcam-msg webcam_gaze` | `webcam_gaze` | message name of the webcam samples, see 4.3 |
| `--quiet` | off | do not print each event in the console log |
| `--mock` | off | simulated tracker, see section 5 |
| `--no-gui` | off | no window; runs in the terminal only and stops with Ctrl+C |
| `--backend pro` | `et5` | use a Tobii Pro tracker, see section 14 |

`python labvanced_tobii_bridge.py --help` lists them as well.

## 8. Output files

Each run creates a folder `recordings/<date>_<time>_<label>/` with five CSV files:

| File | Content | Written |
|---|---|---|
| `merged.csv` | **everything in one table**, sorted by time | when you click Stop |
| `gaze.csv` | Tobii gaze samples (~33 per second) | live, during the session |
| `webcam.csv` | Labvanced webcam gaze samples | live |
| `events.csv` | all other messages from the study (your events) | live |
| `clock_sync.csv` | once per second, the measured offset between the Tobii clock and the computer clock | live |

The live files are complete even if the computer crashes; `merged.csv` is built from them.

### merged.csv

One row per Tobii sample, webcam sample or event. The column `row_type` says which:

| Column | `tobii` rows | `webcam` rows | `event` rows |
|---|---|---|---|
| `unix_time_ms` | time of the Tobii sample | `T` = camera capture time | Labvanced event time (receive time if no timestamp was sent) |
| `tobii_timestamp_us` | the same moment on the Tobii clock (microseconds) | same | same |
| `row_type` | `tobii` | `webcam` | `event` |
| `tobii_x_norm`, `tobii_y_norm` | Tobii gaze, 0..1 across the screen | **nearest Tobii sample** | |
| `tobii_x_px`, `tobii_y_px` | Tobii gaze in screen pixels | nearest Tobii sample | |
| `tobii_valid` | 1 = eyes found, 0 = not (e.g. blink) | nearest Tobii sample | |
| `pupil_left_mm`, `pupil_right_mm` | empty for the Eye Tracker 5 (Tobii Pro only) | | |
| `webcam_x_frame`, `webcam_y_frame` | | webcam gaze as Labvanced records it (frame units) | |
| `webcam_x_norm`, `webcam_y_norm` | | webcam gaze converted to 0..1 across the screen, comparable to `tobii_x_norm`/`tobii_y_norm` | |
| `webcam_x_px`, `webcam_y_px` | | webcam gaze in screen pixels, comparable to `tobii_x_px`/`tobii_y_px` | |
| `webcam_confidence` | | `C` from Labvanced (0..1) | |
| `tobii_dt_ms` | | webcam `T` minus the time of the paired Tobii sample (within ±15 ms at 33 Hz) | |
| `labvanced_msg` | | | the message, e.g. `frame_start_image` |
| `labvanced_value` | | | the variable value sent |
| `labvanced_unix_ms` | | | Labvanced's own timestamp of the event, if the value was one |

So **every `webcam` row is a direct comparison of the two trackers** at the same moment, in the same
units. To know which stimulus was shown, take the last `event` row before it.

### The single files

* `gaze.csv`: `unix_time_ms`, `tobii_timestamp_us`, `tobii_x_norm`, `tobii_y_norm`, `tobii_x_px`,
  `tobii_y_px`, `tobii_valid`, `pupil_left_mm`, `pupil_right_mm`.
* `webcam.csv`: `unix_time_ms` (= `T`), `tobii_timestamp_us`, `webcam_x_frame`, `webcam_y_frame`,
  `webcam_x_norm`, `webcam_y_norm`, `webcam_x_px`, `webcam_y_px`, `webcam_confidence`, plus
  `received_unix_ms` (when it arrived) and `processing_lag_ms` (arrival minus `T`: the time
  Labvanced needed to compute the gaze from the camera image).
* `events.csv`: `unix_time_ms` (when it arrived), `tobii_timestamp_us`, `labvanced_msg`,
  `labvanced_value`, `labvanced_unix_ms`, `transfer_delay_ms` (arrival minus Labvanced's timestamp).
* `clock_sync.csv`: the raw clock measurements, only needed to check the alignment.

Webcam samples where Labvanced found no gaze have empty x/y cells; they are kept, not dropped.

## 9. Coordinates: how the two trackers are made comparable

* **Tobii** reports gaze **normalized from 0 to 1 across the screen** it was set up on in Tobii
  Experience: (0, 0) is the top left corner of the screen, (1, 1) the bottom right. Values
  outside 0..1 mean the gaze was off the screen. The script keeps these values exactly as Tobii
  delivers them, and adds pixels (`x * screen width`, `y * screen height`).
* **Labvanced** records webcam gaze in **frame units**: positions on the study's frame, e.g.
  0..800 by 0..450.
* In the `Zoom / Adaptive` display mode, Labvanced scales the frame to fit the screen and centers
  it. The script reverses exactly that calculation and converts each webcam sample into Tobii's
  0..1 screen coordinates (and pixels). If the frame has the same shape as the screen (an
  800 x 450 frame on a 1920 x 1080 screen, both 16:9), this simply means
  `x_norm = x / 800`, `y_norm = y / 450`. On a screen with a different shape (e.g. 16:10), the
  frame has empty bars at the top and bottom, and the conversion accounts for them.

The study must run in fullscreen, on the screen with the tracker, with the frame size given to
the script (default 800 x 450).

## 10. Timing: how the clocks are aligned

All times in the files are on one time axis, the computer's clock (`unix_time_ms`, milliseconds
since 1970):

1. **Tobii samples**: the tracker timestamps each sample when it records it. Once per second the
   script measures the offset between the Tobii clock and the computer clock (round trip of a few
   microseconds), and converts each sample's time with it.
2. **Labvanced** runs in the browser on the same computer and uses the same computer clock for its
   timestamps (`T` of the webcam samples, `Trigger Timestamp (Unixtime)` of events). These times
   are used directly, so transfer delays do not matter.

Things to keep in mind:

* Labvanced timestamps have 1 ms resolution.
* An event's timestamp is the moment the event fired in the browser. The moment the frame
  physically appears on the screen is typically one screen refresh later (about 8 to 17 ms). This
  shifts events relative to both trackers in the same way.
* Each tracker's timestamp is only as accurate as that tracker's own capture time.
* The Eye Tracker 5 delivers about 33 samples per second, so a webcam sample is paired with a
  Tobii sample at most about 15 ms away (`tobii_dt_ms`).

## 11. Analysis example (Python)

```python
import numpy as np
import pandas as pd

m = pd.read_csv("recordings/2026-11-03_10-15-00_P01/merged.csv")

# which event (e.g. stimulus) each row belongs to: the last event before it
m["current_event"] = m["labvanced_msg"].where(m["row_type"] == "event").ffill()

# webcam rows = both trackers side by side
w = m[(m["row_type"] == "webcam") & (m["tobii_valid"] == 1)].dropna(subset=["webcam_x_px"])
w["distance_px"] = np.hypot(w["webcam_x_px"] - w["tobii_x_px"], w["webcam_y_px"] - w["tobii_y_px"])

print(w.groupby("current_event")["distance_px"].median())
```

## 12. Recommended pilot check

Before the first real participant, run one pilot session with a simple task: a dot that jumps to
several positions across the screen, each shown for 2 seconds, with a `Send To Websocket` event on
each frame start. In `merged.csv` you should then see:

* both trackers jump to each new position shortly after its event (the eye movement), at nearly
  the same time (within a sample interval, ~30 ms),
* both close to the dot position.

This confirms the setup (timing, screen, frame size, calibration) before data collection.

## 13. Troubleshooting

| Problem | Solution |
|---|---|
| `tobii_stream_engine.dll not found` | see 3.3, add the path with `--dll` |
| `No Tobii eye tracker found` | check that Tobii Experience shows the tracker as ready; replug the USB cable |
| `Stream Engine ... is too old` | update Tobii Experience |
| The console says `Python was not found` | install Python as in 3.2, with "Add python.exe to PATH" ticked; if Python is installed but was added without that option, reinstall it with the option |
| The console says `Installing "websockets" failed` | usually no internet connection or a blocking network proxy; connect to the internet and start again, or ask your IT to install the Python package `websockets` |
| The window does not open, the console shows `No module named 'tkinter'` | reinstall Python with the default options (3.2) |
| `Tobii eye tracker` stays orange: no eyes detected | participant not in front of the tracker, or the tracker set up for a different screen in Tobii Experience |
| Tobii gaze is always the same point or way off | calibrate in Tobii Experience (3.1) |
| `Labvanced study` stays grey (`Waiting for the study`) after opening the study | check 4.1; check that Chrome's "access other apps and services" prompt was allowed (if you clicked Block: click the icon left of the address bar → Site settings → allow), then reload the study |
| `Labvanced study` is red: `WebSocket server stopped ... address already in use` | the recorder is already running in another window: close all of them and start once; or another program uses port 8081: use `--port 8090` and the same port in the study settings |
| `Webcam gaze` stays grey although the study runs with eye tracking | check the `Send To Websocket` action of 4.3: message exactly `webcam_gaze`, the array variable selected |
| Webcam samples appear in `events.csv` instead of `webcam.csv` | the variable sent with `webcam_gaze` is not the `[X,Y,T,C]` array |
| Webcam and Tobii positions are systematically shifted or scaled | check 4.2: `Zoom / Adaptive`, fullscreen, correct `--frame-size`, study on the tracker's screen |
| `Could not detect the screen resolution` | add `--screen-size 1920x1080` (your resolution) |
| Fewer webcam samples in `webcam.csv` than in the Labvanced export | the recorder was closed, or the study tab reloaded, during the session (see section 6); use the Labvanced export for the missing part |

## 14. Using a Tobii Pro tracker instead

The same script works with Tobii Pro screen-based trackers (Spark, Fusion, Nano, Spectrum),
which are licensed for research and also deliver pupil size:

1. Install **Tobii Pro Eye Tracker Manager**, set up the display and calibrate there.
2. Use **Python 3.10, 64-bit** (the Tobii Pro SDK only exists for Python 3.10), and install the
   Tobii Pro SDK once: open a command prompt (Windows key, type `cmd`, Enter) and run
   ```
   pip install tobii-research
   ```
3. Open `start_recording.bat` with Notepad and add `--backend pro` to the line `python labvanced_tobii_bridge.py %*` near the end:
   ```
   python labvanced_tobii_bridge.py --backend pro %*
   ```

Everything else (study setup, output files) is the same; `pupil_left_mm` / `pupil_right_mm` are
then filled, and Tobii's x/y is the average of both eyes.
