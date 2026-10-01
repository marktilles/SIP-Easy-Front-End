"""
Lamp scheduler blueprint for the sprinklers front-end.

lamptimer.py keeps running as its own service and owns GPIO 27. This blueprint
never touches GPIO: it only reads/writes the same schedule.json and
shutdown_flag.json files that lampapp.py used, so lamptimer behaves exactly
as before.

Routes
  GET  /lamp/status    -> {lamp_on, sunset, turn_on, schedule{...}}
  POST /lamp/schedule  -> JSON body {mode, offset_minutes, fixed_on_time, off_time}
"""

import json
import os
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from astral import LocationInfo
from astral.sun import sun
from flask import Blueprint, current_app, jsonify, request

lamp_bp = Blueprint("lamp", __name__, url_prefix="/lamp")

SCHEDULE_FILE = "/home/pi/schedule.json"
SHUTDOWN_FILE = "/home/pi/shutdown_flag.json"

CITY = LocationInfo("Los Angeles", "USA", "America/Los_Angeles", 34.0522, -118.2437)
TIMEZONE = ZoneInfo("America/Los_Angeles")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

DEFAULT_SCHEDULE = {
    "mode": "sunset",
    "offset_minutes": 60,
    "fixed_on_time": "19:00",
    "off_time": "23:59",
}


# --- File helpers (atomic writes, same as lampapp.py) ---
def _write_json_atomic(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def load_schedule():
    try:
        with open(SCHEDULE_FILE, "r") as f:
            return {**DEFAULT_SCHEDULE, **json.load(f)}
    except (json.JSONDecodeError, OSError) as e:
        current_app.logger.warning(f"lamp: schedule.json unreadable ({e}); using defaults")
        return dict(DEFAULT_SCHEDULE)


def save_schedule(schedule):
    _write_json_atomic(SCHEDULE_FILE, schedule)
    # Tell lamptimer to re-evaluate immediately
    _write_json_atomic(SHUTDOWN_FILE, {"turn_off_now": True})


def valid_time(value, fallback):
    return value if isinstance(value, str) and TIME_RE.match(value) else fallback


# --- Schedule logic (same rules as lamptimer.py) ---
def today_sunset():
    return sun(CITY.observer, date=datetime.now(TIMEZONE).date(), tzinfo=TIMEZONE)["sunset"]


def compute_lamp_state(schedule, now):
    """Returns (lamp_on_now, turn_on_str)."""
    if schedule.get("mode") == "sunset":
        on_dt = today_sunset() + timedelta(minutes=schedule.get("offset_minutes", 60))
    else:
        t = valid_time(schedule.get("fixed_on_time"), DEFAULT_SCHEDULE["fixed_on_time"])
        h, m = map(int, t.split(":"))
        on_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)

    t_off = valid_time(schedule.get("off_time"), DEFAULT_SCHEDULE["off_time"])
    h, m = map(int, t_off.split(":"))
    off_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)

    if off_dt <= on_dt:  # overnight schedule
        lamp_on = now >= on_dt or now < off_dt
    else:
        lamp_on = on_dt <= now < off_dt
    return lamp_on, on_dt.strftime("%H:%M")


def status_payload():
    schedule = load_schedule()
    now = datetime.now(TIMEZONE)
    lamp_on, turn_on = compute_lamp_state(schedule, now)
    return {
        "lamp_on": lamp_on,
        "sunset": today_sunset().strftime("%H:%M"),
        "turn_on": turn_on,
        "schedule": schedule,
    }


# --- Routes ---
@lamp_bp.route("/status")
def lamp_status():
    try:
        return jsonify(status_payload())
    except Exception as e:
        current_app.logger.error(f"lamp status error: {e}")
        return jsonify(error=str(e)), 500


@lamp_bp.route("/schedule", methods=["POST"])
def lamp_schedule():
    data = request.get_json(force=True, silent=True) or {}
    try:
        offset = max(0, min(int(data.get("offset_minutes", 60)), 720))
    except (TypeError, ValueError):
        offset = 60

    schedule = {
        "mode": data.get("mode") if data.get("mode") in ("sunset", "fixed") else "sunset",
        "offset_minutes": offset,
        "fixed_on_time": valid_time(data.get("fixed_on_time"), DEFAULT_SCHEDULE["fixed_on_time"]),
        "off_time": valid_time(data.get("off_time"), DEFAULT_SCHEDULE["off_time"]),
    }
    try:
        save_schedule(schedule)
        return jsonify({**status_payload(), "success": True})
    except Exception as e:
        current_app.logger.error(f"lamp: could not save schedule: {e}")
        return jsonify(success=False, error=str(e)), 500
