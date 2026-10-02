#!/home/pi/kiln-controller/venv/bin/python

import RPi.GPIO as GPIO
import time
from datetime import datetime, timedelta
import json
from astral import LocationInfo
from astral.sun import sun
from zoneinfo import ZoneInfo
import os
import logging
from logging.handlers import RotatingFileHandler

# --- Logging setup: capped, auto-rotating log file (never grows unbounded) ---
LOG_FILE = "/home/pi/lamptimer.log"
logger = logging.getLogger("lamptimer")
logger.setLevel(logging.INFO)
_handler = RotatingFileHandler(LOG_FILE, maxBytes=500_000, backupCount=3)
_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
logger.addHandler(_handler)

# --- GPIO setup ---
GPIO.setmode(GPIO.BCM)
GPIO_PIN = 25
GPIO.setup(GPIO_PIN, GPIO.OUT)
GPIO.output(GPIO_PIN, GPIO.LOW)

# --- Config ---
TIMEZONE = ZoneInfo("America/Los_Angeles")
SCHEDULE_FILE = "/home/pi/schedule.json"
SHUTDOWN_FILE = "/home/pi/shutdown_flag.json"

DEFAULT_SCHEDULE = {
    "mode": "sunset",
    "offset_minutes": 60,
    "fixed_on_time": "19:00",
    "off_time": "23:59"
}

# --- Location for sunset calculations ---
city = LocationInfo("Los Angeles", "USA", "America/Los_Angeles", 34.0522, -118.2437)

# --- Sunset cache (avoid recomputing every 0.5s loop tick) ---
_cached_sunset_date = None
_cached_sunset = None


def load_schedule():
    try:
        with open(SCHEDULE_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError, OSError) as e:
        logger.warning(f"Could not read schedule.json ({e}). Using default schedule.")
        return dict(DEFAULT_SCHEDULE)


def parse_time(timestr, fallback="19:00"):
    """Parse HH:MM into today's datetime; fall back to a safe default on bad input."""
    try:
        h, m = map(int, timestr.split(":"))
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError("out of range")
    except (ValueError, AttributeError):
        logger.warning(f"Invalid time string '{timestr}', falling back to {fallback}")
        h, m = map(int, fallback.split(":"))
    return datetime.now(TIMEZONE).replace(hour=h, minute=m, second=0, microsecond=0)


def get_today_sunset():
    """Cache sunset time per calendar day instead of recomputing every loop tick."""
    global _cached_sunset_date, _cached_sunset
    today = datetime.now(TIMEZONE).date()
    if _cached_sunset_date != today or _cached_sunset is None:
        s = sun(city.observer, date=today, tzinfo=TIMEZONE)
        _cached_sunset = s["sunset"]
        _cached_sunset_date = today
    return _cached_sunset


def check_shutdown_flag():
    if os.path.exists(SHUTDOWN_FILE):
        try:
            with open(SHUTDOWN_FILE, "r") as f:
                flag = json.load(f)
                if flag.get("turn_off_now", False):
                    # Reset flag atomically
                    tmp_file = SHUTDOWN_FILE + ".tmp"
                    with open(tmp_file, "w") as f2:
                        json.dump({"turn_off_now": False}, f2)
                        f2.flush()
                        os.fsync(f2.fileno())
                    os.replace(tmp_file, SHUTDOWN_FILE)
                    return True
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Could not read shutdown_flag.json ({e})")
    return False


# --- Lamp control loop ---
logger.info("Starting Lamp Timer...")
last_state = None  # tracks last applied GPIO state so we only log/act on change
try:
    while True:
        try:
            schedule = load_schedule()
            now = datetime.now(TIMEZONE)

            # Determine turn-on time
            if schedule.get("mode") == "sunset":
                sunset = get_today_sunset()
                turn_on = sunset + timedelta(minutes=schedule.get("offset_minutes", 60))
            else:
                turn_on = parse_time(
                    schedule.get("fixed_on_time", DEFAULT_SCHEDULE["fixed_on_time"]),
                    DEFAULT_SCHEDULE["fixed_on_time"],
                )

            turn_off = parse_time(
                schedule.get("off_time", DEFAULT_SCHEDULE["off_time"]),
                DEFAULT_SCHEDULE["off_time"],
            )

            # Immediate shutdown check
            if check_shutdown_flag():
                GPIO.output(GPIO_PIN, GPIO.LOW)
                if last_state is not False:
                    logger.info("Lamp OFF due to schedule update")
                    last_state = False
                time.sleep(0.5)
                continue  # skip normal schedule for this loop

            # --- Handle overnight schedules (off time earlier than on time) ---
            if turn_off <= turn_on:
                # Off time occurs the next day
                if now >= turn_on or now < turn_off:
                    lamp_should_be_on = True
                else:
                    lamp_should_be_on = False
            else:
                # Normal same-day schedule
                lamp_should_be_on = turn_on <= now < turn_off

#            # --- Apply output state (only act/log on an actual change) ---
#            if lamp_should_be_on != last_state:
#                GPIO.output(GPIO_PIN, GPIO.HIGH if lamp_should_be_on else GPIO.LOW)
#                logger.info(f"Lamp {'ON' if lamp_should_be_on else 'OFF'}")
#                last_state = lamp_should_be_on

#           --- Apply output state: re-assert EVERY tick so SIP / sprinklers.py
            # can't leave the lamp wrong. Log only on an actual change. ---
            GPIO.setup(GPIO_PIN, GPIO.OUT)   # re-claim pin in case another process released it
            GPIO.output(GPIO_PIN, GPIO.HIGH if lamp_should_be_on else GPIO.LOW)
            if lamp_should_be_on != last_state:
                logger.info(f"Lamp {'ON' if lamp_should_be_on else 'OFF'}")
                last_state = lamp_should_be_on


            time.sleep(0.5)  # short sleep for fast reaction

        except KeyboardInterrupt:
            raise
        except Exception as e:
            # Don't let one bad tick (malformed file, transient IO error, etc.)
            # kill the whole daemon and leave the lamp stuck in its last state.
            logger.error(f"Loop error: {e}")
            time.sleep(1)

except KeyboardInterrupt:
    GPIO.output(GPIO_PIN, GPIO.LOW)
finally:
    GPIO.cleanup()
