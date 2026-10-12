"""Event suggestions from a workbook note (M2F). Suggestions only: nothing is applied unless the engineer
accepts it in the preview, and the note itself is always imported as written.

* An event category for the row's entry, from conservative keywords:
  Start/restart ("Start RPM", "restart"), Stop ("stop RPM", "shut down",
  "trip"), Adjustment ("changed", "reduce", "valve", "cooler"…), Abnormal
  observation ("noise", "vibration"…).
* Starting or stopping a recording ("Start recording", "Stop recording")
  is not a shaft start or stop: Start/Stop feed the shaft-running timeline
  (results/runtime.py). It is suggested as Other.
* A time in the note ("9:36 Changed 1 coil…" on a 10:35 reading) proposes a
  separate event entry at that time, with the text from that time on.
* "After … stop" proposes a separate Stop (or Start) event after the
  reading, at a time the engineer enters: putting Stop on the reading
  itself would place the stop before the speed it recorded.
"""

import re

from ..models import ManualLogEntry

Category = ManualLogEntry.Category

_RECORDING = re.compile(r"\b(start|stop|end)\w*\s+(?:of\s+)?(?:the\s+)?(record\w*|logging|labview|dcs)\b", re.I)
_AFTER = re.compile(r"\bafter\b.*?\b(stop|start)", re.I)
_START = re.compile(r"\b(re-?start\w*|start(?:ed|ing)?\s*(?:up|rpm|rotation|shaft|motor|speed|running)|start-?up)\b",
                    re.I)  # fmt: skip
_STOP = re.compile(r"\b(stop(?:ped|ping)?\s*(?:rpm|rotation|shaft|motor|speed|running)|shut\s*-?down|trip(?:ped)?)\b",
                   re.I)  # fmt: skip
_ADJUST = re.compile(r"\b(chang\w*|reduc\w*|redus\w*|increas\w*|decreas\w*|adjust\w*|valves?|coolers?|set\s*point\w*|"
                     r"opened|closed)\b", re.I)  # fmt: skip
_ABNORMAL = re.compile(r"\b(noise|noisy|vibration\w*|abnormal|smoke|squeal\w*|alarm\w*)\b", re.I)
# A time of day in the note: 9:36, 09:36, 9h36; with a dot (9.50) only at the start of the note.
_TIME = re.compile(r"(?<![\d.:,])([01]?\d|2[0-3])[:h]([0-5]\d)(?![\d])|^\s*([01]?\d|2[0-3])\.([0-5]\d)(?![\d])")


def _category(text):
    """(category, reason) suggested by the words of a note, or (None, "")."""
    if _RECORDING.search(text):
        return Category.OTHER, "Recording start/stop, not a shaft start/stop."
    if _START.search(text):
        return Category.START, "The note mentions a start."
    if _STOP.search(text):
        return Category.STOP, "The note mentions a stop."
    if _ABNORMAL.search(text):
        return Category.ABNORMAL, "The note mentions an abnormal observation."
    if _ADJUST.search(text):
        return Category.ADJUSTMENT, "The note mentions an adjustment or a configuration change."
    return None, ""


def suggest(note, at, next_at=None):
    """{"category": {"value", "reason"} | None, "events": [{"time", "category", "note", "reason", "flag",
    "needs_time"}]} for a row's note; at/next_at: local datetimes of this and the next row."""
    found = {"category": None, "events": []}
    if not note:
        return found
    times = []
    for match in _TIME.finditer(note):
        hour, minute_ = (match.group(1), match.group(2)) if match.group(1) else (match.group(3), match.group(4))
        times.append((match.start(), int(hour), int(minute_)))
    for index, (start, hour, minute_) in enumerate(times):
        if (hour, minute_) == (at.hour, at.minute):
            continue
        end = times[index + 1][0] if index + 1 < len(times) else len(note)
        text = note[start:end].strip(" ;,&-")
        category, _ = _category(text)
        event = {"time": f"{hour:02d}:{minute_:02d}", "category": category or Category.OTHER, "note": text,
                 "reason": f"The note names the time {hour:02d}:{minute_:02d}; the reading is at {at:%H:%M}.",
                 "flag": "", "needs_time": False}  # fmt: skip
        if (hour, minute_) > (at.hour, at.minute):
            event["flag"] = "Later than the reading: check the date and time."
        found["events"].append(event)
    after = _AFTER.search(note)
    if after and not _RECORDING.search(note):
        category = Category.STOP if after.group(1).lower() == "stop" else Category.START
        window = f" (between {at:%H:%M} and {next_at:%H:%M}, the next row)" if next_at else ""
        found["events"].append({
            "time": "", "category": category, "note": note,
            "reason": f"The note says “{after.group(0)}” after this reading: enter when{window}.",
            "flag": "", "needs_time": True,
        })  # fmt: skip
    if not found["events"]:
        category, reason = _category(note)
        if category:
            found["category"] = {"value": category, "reason": reason}
    return found
