#!/usr/bin/env python3

from flask import Flask, render_template, request, jsonify, render_template_string, Response
from bs4 import BeautifulSoup
import threading
import time
import RPi.GPIO as GPIO
import subprocess
import time  # Ensure this is at the top
import requests
import re

import json
import os

# Add upload button optiomn for replcing background image
from werkzeug.utils import secure_filename



# Load config from file
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
with open(CONFIG_PATH) as f:
    CONFIG = json.load(f)
    TITLE = CONFIG.get("title", "Untitled")
    VERSION = CONFIG.get("version", "unknown")
    DEFAULT_DURATION = CONFIG.get("default_duration_min", "9")
    SERVER_IP = CONFIG["server_ip"]
    ZONE_CONFIG = {int(k): v for k, v in CONFIG["zones"].items()}

    print("Loaror reading log file: name 'render_template_string' is not definedded config for server titled:", TITLE)
    print("Default Duration:", DEFAULT_DURATION)
    print("Server IP:", SERVER_IP)
    print("Version:", VERSION)
    print("Zones defined:", {k: v["nickname"] for k, v in ZONE_CONFIG.items()})


GPIO.setmode(GPIO.BCM)
for zone in ZONE_CONFIG.values():
    GPIO.setup(zone["gpio"], GPIO.OUT)
    GPIO.output(zone["gpio"], GPIO.LOW)

# Globals
app = Flask(__name__)
zone_timers = {}               # zone_id -> remaining seconds
lock = threading.Lock()
has_user_activated_zone = False
gpio_initialized = True

# Upload config (this goes here!)
# Add upload button optiomn for replcing background image
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'static')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def stop_sip_service():
    GPIO.setmode(GPIO.BCM)
    for zone in ZONE_CONFIG.values():
        GPIO.setup(zone["gpio"], GPIO.OUT)
    try:
        result = subprocess.run(['sudo', 'pkill', '-f', 'sip'], check=True, text=True, capture_output=True)
        print("SIP process stopped successfully.")
    except subprocess.CalledProcessError as e:
        print("Error stopping SIP process:", e.stderr)


def start_sip_service():
    try:
        result = subprocess.run(['sudo', 'systemctl', 'start', 'sip'], check=True, text=True, capture_output=True)
        print("SIP process started successfully:", result.stdout)
    except subprocess.CalledProcessError as e:
        print("Error starting SIP process:", e.stderr)
        raise

def gpio_on(zone_id):
    GPIO.output(ZONE_CONFIG[zone_id]["gpio"], GPIO.HIGH)

def gpio_off(zone_id):
    GPIO.output(ZONE_CONFIG[zone_id]["gpio"], GPIO.LOW)

def initialize_gpio():
    global gpio_initialized
    GPIO.setmode(GPIO.BCM)
    for zone in ZONE_CONFIG.values():
        GPIO.setup(zone["gpio"], GPIO.OUT)
        GPIO.output(zone["gpio"], GPIO.LOW)
    gpio_initialized = True
    print("GPIO system re-initialized.")





@app.route("/")
def index():
    return render_template(
        "index.html",
        zones=ZONE_CONFIG,
        version=VERSION,
        default_duration=DEFAULT_DURATION,
        server_ip=SERVER_IP,
        title=TITLE
    )


@app.route("/active_zones")
def active_zones():
    try:
        response = requests.get(f"http://{SERVER_IP}/sn", timeout=2)
        html = response.text
        print(f"[active_zones] Full HTML response:\n{html}")

        # Find the first 8-digit binary sequence in the HTML
        match = re.search(r'\b[01]{8}\b', html)
        if not match:
            return jsonify(active=False, zones=[], error="8-bit binary value not found", raw=html)

        binary_str = match.group(0)
        print(f"[active_zones] Extracted binary: '{binary_str}'")

        active_zone_ids = [str(i + 1) for i, c in enumerate(binary_str) if c == '1']

        # Add nicknames
        nicknames = {
            zid: ZONE_CONFIG[int(zid)]["nickname"]
            for zid in active_zone_ids
            if int(zid) in ZONE_CONFIG and ZONE_CONFIG[int(zid)]["nickname"] != "MASTER"
        }

        return jsonify(active=bool(active_zone_ids), zones=active_zone_ids, nicknames=nicknames, raw=binary_str)

    except Exception as e:
        print("Error fetching active zones:", e)
        return jsonify(active=False, zones=[], error=str(e))



@app.route("/toggle_sip", methods=["POST"])
def toggle_sip():
    try:
        result = subprocess.run(['systemctl', 'is-active', 'sip'], text=True, capture_output=True)
        is_running = result.stdout.strip() == "active"

        if is_running:
            stop_sip_service()
            # Turn off all GPIOs except MASTER (zone 8)
            for zid in ZONE_CONFIG:
                gpio_off(zid)
            return jsonify(success=True, running=False)
        else:
            start_sip_service()
            return jsonify(success=True, running=True)
    except Exception as e:
        print("Error toggling SIP service:", str(e))
        return jsonify(success=False, error=str(e))


@app.route("/start_zone", methods=["POST"])
def start_zone():
    global has_user_activated_zone, gpio_initialized

    try:
        data = request.get_json(force=True)
        print("Received start_zone request:", data)

        zone_id = int(data.get("zone", -1))
        duration = int(data.get("duration", 0))

        if zone_id not in ZONE_CONFIG or zone_id == 8 or duration <= 0:
            return jsonify(success=False, error="Invalid zone or duration")

        with lock:
            if not gpio_initialized:
                initialize_gpio()

            # Only stop SIP service if this is NOT the Misters zone
            if ZONE_CONFIG[zone_id]["nickname"].lower() != "misters":
                stop_sip_service()

            if not has_user_activated_zone:
                has_user_activated_zone = True

            zone_timers[zone_id] = duration
            gpio_on(zone_id)
            gpio_on(8)

        return jsonify(success=True)

    except Exception as e:
        print("Error in /start_zone:", e)
        return jsonify(success=False, error=str(e))


@app.route("/stop_all", methods=["POST"])
def stop_all():
    global gpio_initialized, has_user_activated_zone
    try:
        with lock:
            for zid in ZONE_CONFIG:
                gpio_off(zid)
            zone_timers.clear()
            GPIO.cleanup()
            gpio_initialized = False
            has_user_activated_zone = False

        time.sleep(1.0)  # Let GPIOs fully release

        # Restart SIP scheduler
        #start_sip_service()
        #print("SIP scheduler restarted after manual stop.")

        return jsonify(success=True)
    except Exception as e:
        print("Failed to restart SIP after stop_all:", e)
        return jsonify(success=False, error=str(e))

# This shows all schedules on SIP service but removes buttons
@app.route("/view-vp")
def view_schedules():
    try:
        remote_url = f"http://{SERVER_IP}/vp"
        resp = requests.get(remote_url, timeout=5)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove unwanted UI components
        for tag in soup.find_all(['script', 'header', 'nav', 'footer', 'aside']):
            tag.decompose()
        for tag in soup.find_all(['button', 'input', 'form']):
            tag.decompose()

        # Locate all schedule blocks
        program_cards = soup.find_all("div", class_="controlblock")
        if not program_cards:
            return "Could not find any schedule cards.", 404

        content_html = ""

        for card in program_cards:
            # Skip disabled schedules
            if "disabled" in card.get("class", []):
                continue

            # Break the card HTML into lines
            lines = str(card).splitlines()
            processed_lines = []

            for line in lines:
                processed_lines.append(line)
                if "until" in line.lower():
                    # Separator only inside the card after 'until'
                    processed_lines.append(
                        '<hr style="border: 0; border-top: 1px solid black; margin: 6px 0;">'
                    )

            # Add card content
            content_html += "\n".join(processed_lines)

        return render_template_string(f"""
            <html>
            <head>
                <title>Beautified Schedules</title>
                <style>
                    body {{
                        font-family: sans-serif;
                        font-size: 36px;
                        background-color: #f0f8ff;
                        padding: 20px;
                    }}
                    hr {{
                        border: none;
                        border-top: 2px solid #ccc;
                        margin: 40px 0;
                    }}
                    .panel {{
                        padding: 20px;
                        border-radius: 12px;
                        background-color: white;
                        box-shadow: 0 2px 6px rgba(0,0,0,0.05);
                    }}
                </style>
            </head>
            <body>
                <h2>Sprinkler Program Schedules</h2>
                {content_html}
            </body>
            </html>
        """)

    except Exception as e:
        return f"<h3>Error loading schedule page: {str(e)}</h3>", 500


@app.route('/view-log')
def view_log():
    try:
        response = requests.get(f"http://{SERVER_IP}/vl", timeout=5)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')
        tables = soup.find_all('table')

        if not tables:
            return "No table data found on the page.", 404

        table_html = ''.join(str(table) for table in tables)

        return render_template_string(f"""
            <html>
            <head>
                <title>Sprinkler Log Table</title>
                <style>
                    body {{
                        font-family: sans-serif;
                        background-color: #f0f8ff;
                        font-size: 36px;
                        padding: 20px;
                    }}
                    table {{
                        border-collapse: collapse;
                        width: 100%;
                    }}
                    th, td {{
                        border: 1px solid #ccc;
                        padding: 8px;
                        text-align: left;
                    }}
                </style>
            </head>
            <body>
                <h2>Sprinkler Log Table Data</h2>
                {table_html}
            </body>
            </html>
        """)

    except requests.exceptions.RequestException as e:
        return f"Failed to fetch table data: {e}", 500


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/upload_background', methods=['POST'])
def upload_background():
    if 'photo' not in request.files:
        return jsonify(success=False, error="No file part")

    file = request.files['photo']
    if file.filename == '':
        return jsonify(success=False, error="No selected file")

    if file and allowed_file(file.filename):
        filename = secure_filename("IMG_5040.jpg")  # overwrite the current background image
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        # Restart the SIP service
        try:
            stop_sip_service()
            start_sip_service()
            return jsonify(success=True)
        except Exception as e:
            return jsonify(success=False, error=str(e))

    return jsonify(success=False, error="Invalid file type")


@app.route("/status")
def status():
    with lock:
        return jsonify({
            zid: {
                "nickname": ZONE_CONFIG[zid]["nickname"],
                "remaining": zone_timers.get(zid, 0)
            } for zid in ZONE_CONFIG if zid != 8
        })


@app.route("/sip_status", methods=["GET"])
def sip_status():
    try:
        result = subprocess.run(['systemctl', 'is-active', 'sip'], text=True, capture_output=True)
        is_running = result.stdout.strip() == "active"
        return jsonify(running=is_running)
    except Exception as e:

        return jsonify(running=False, error=str(e))

def countdown_loop():
    global has_user_activated_zone, gpio_initialized

    while True:
        time.sleep(1)

        try:
            with lock:
                expired = []
                for zone_id in list(zone_timers):
                    zone_timers[zone_id] -= 1
                    if zone_timers[zone_id] <= 0:
                        gpio_off(zone_id)
                        expired.append(zone_id)
                for zid in expired:
                    del zone_timers[zid]

                if has_user_activated_zone:
                    # MASTER logic
                    if any(z != 8 for z in zone_timers):
                        gpio_on(8)
                    else:
                        gpio_off(8)

                    # Auto-release & restart logic
                    if len(zone_timers) == 0 and GPIO.input(ZONE_CONFIG[8]["gpio"]) == GPIO.LOW:
                        print("All zones complete. Releasing GPIO and restarting scheduler.")

                        GPIO.cleanup()
                        gpio_initialized = False
                        has_user_activated_zone = False

                        # Delay to ensure GPIO is truly released
                        time.sleep(1.0)

                        # Restart SIP service
                        #try:
                            #start_sip_service()
                        #except Exception as e:
                            #print("Auto-restart SIP failed:", e)

        except Exception as loop_error:
            print("Error in countdown loop:", loop_error)

threading.Thread(target=countdown_loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

