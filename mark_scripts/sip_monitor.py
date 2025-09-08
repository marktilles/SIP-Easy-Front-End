#!/usr/bin/env python3

import smtplib
import subprocess
import datetime
import socket
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ==========================
# CONFIGURATION
# ==========================
FROM_EMAIL = "markdtilles@gmail.com"
TO_EMAIL = "mark.tilles@icloud.com"
APP_PASSWORD = "moek iezj dqeo nimp"   # Gmail App Password

SERVICE_NAME = "sip"                 # systemd service name
STATE_FILE = "/tmp/sip_last_active.txt"

HOURS_THRESHOLD = 1                  # inactivity threshold
# ==========================

# Get server hostname
SERVER_NAME = socket.gethostname()

def get_ip_address():
    """Get the server's primary IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))   # connect to external server
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "Unknown"

SERVER_IP = get_ip_address()


def is_service_active(service_name):
    """Check if a systemd service is active."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", service_name],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout.strip() == "active"
    except Exception as e:
        print(f"Error checking service: {e}")
        return False


def send_email():
    """Send an email alert."""
    subject = f"SIP Service Inactive on ({SERVER_IP})"
    body = (
        f"The SIP service on server '{SERVER_NAME}' "
        f"({SERVER_IP}) has been inactive for at least {HOURS_THRESHOLD} hours. Remember to open the app and restart the Automatic Sprinkler Scheduler if the weather demands it."
    )

    msg = MIMEMultipart()
    msg["From"] = FROM_EMAIL
    msg["To"] = TO_EMAIL
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(FROM_EMAIL, APP_PASSWORD)
            server.sendmail(FROM_EMAIL, TO_EMAIL, msg.as_string())
        print("✅ Email sent successfully")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")


def check_sip_service():
    active = is_service_active(SERVICE_NAME)
    now = datetime.datetime.now()

    try:
        with open(STATE_FILE, "r") as f:
            last_active = datetime.datetime.fromisoformat(f.read().strip())
    except FileNotFoundError:
        last_active = now

    if active:
        # Update last active time
        with open(STATE_FILE, "w") as f:
            f.write(now.isoformat())
        print(f"SIP service is active on {SERVER_NAME} ({SERVER_IP}).")
    else:
        # Check how long it has been inactive
        inactive_time = now - last_active
        hours_inactive = inactive_time.total_seconds() / 3600
        print(f"SIP inactive for {hours_inactive:.2f} hours on {SERVER_NAME} ({SERVER_IP})")
        if hours_inactive >= HOURS_THRESHOLD:
            send_email()


if __name__ == "__main__":
    check_sip_service()

