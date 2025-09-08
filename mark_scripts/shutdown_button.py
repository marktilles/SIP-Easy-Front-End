#!/usr/bin/env python3

import RPi.GPIO as GPIO
import time
import os

# Configuration
PIN = 21
DEBOUNCE_TIME = 0.05
REBOOT_MIN = 1
REBOOT_MAX = 5
SHUTDOWN_MIN = 6
BLINK_DURATION = 0.2  # seconds
LED_PATH = "/sys/class/leds/ACT/"

def led_on():
    with open(LED_PATH + "brightness", "w") as f:
        f.write("1")

def led_off():
    with open(LED_PATH + "brightness", "w") as f:
        f.write("0")

def blink_led(times):
    for _ in range(times):
        led_on()
        time.sleep(BLINK_DURATION)
        led_off()
        time.sleep(BLINK_DURATION)

def monitor_pin():
    # Setup GPIO
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    # Set LED trigger to 'none' so we can manually control it
    with open(LED_PATH + "trigger", "w") as f:
        f.write("none")

    print("Monitoring GPIO 21...")

    try:
        while True:
            if GPIO.input(PIN) == GPIO.LOW:
                start_time = time.time()
                print("Pin pulled LOW, timing...")

                while GPIO.input(PIN) == GPIO.LOW:
                    time.sleep(DEBOUNCE_TIME)

                duration = time.time() - start_time
                print(f"Held LOW for {duration:.2f} seconds")

                if REBOOT_MIN <= duration <= REBOOT_MAX:
                    print("Blinking 5 times before reboot...")
                    blink_led(5)
                    os.system("sudo reboot")

                elif duration >= SHUTDOWN_MIN:
                    print("Blinking 10 times before shutdown...")
                    blink_led(10)
                    os.system("sudo shutdown -h now")

                else:
                   print("Duration outside valid ranges. Ignored.")
                   print("Blinking 2 times before ignore..")
                   blink_led(2)

            time.sleep(0.1)

    except KeyboardInterrupt:
        print("Exiting...")

    finally:
        GPIO.cleanup()
        # Optional: Reset LED trigger to default
        with open(LED_PATH + "trigger", "w") as f:
            f.write("mmc0")  # default trigger for SD activity

if __name__ == "__main__":
    monitor_pin()


