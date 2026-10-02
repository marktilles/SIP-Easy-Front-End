#!/usr/bin/env python3
"""
Live, read-only view of the Raspberry Pi 40-pin GPIO header.

Reads each pin's mode and level by running `pinctrl get` (Raspberry Pi OS
Bookworm) or `raspi-gpio get` (older images). It never configures or drives a
pin, so it is safe to run while sprinklers.py, SIP and lamptimer are running.

Run it on the Pi's desktop:   python3 gpio_viewer.py
Needs Tk once:                sudo apt install python3-tk
"""

import shutil
import subprocess
import time
import tkinter as tk
from tkinter import font as tkfont

REFRESH_MS = 500

# Physical pin number -> BCM GPIO number (int) or power/ground label (str)
HEADER = {
    1: "3V3", 2: "5V", 3: 2, 4: "5V", 5: 3, 6: "GND", 7: 4, 8: 14,
    9: "GND", 10: 15, 11: 17, 12: 18, 13: 27, 14: "GND", 15: 22, 16: 23,
    17: "3V3", 18: 24, 19: 10, 20: "GND", 21: 9, 22: 25, 23: 11, 24: 8,
    25: "GND", 26: 7, 27: 0, 28: 1, 29: 5, 30: "GND", 31: 6, 32: 12,
    33: 13, 34: "GND", 35: 19, 36: 16, 37: 26, 38: 20, 39: "GND", 40: 21,
}

BG = "#1e1e24"
FG = "#e8e8ee"
COLORS = {
    "out_hi": "#2ecc40",   # output driven high
    "out_lo": "#1b6b2a",   # output driven low
    "in_hi": "#339af0",    # input reading high
    "in_lo": "#6b7280",    # input reading low
    "alt": "#ff922b",      # alternate function (I2C, SPI, UART, PWM...)
    "unknown": "#868e96",
    "3V3": "#ffa94d",
    "5V": "#e03131",
    "GND": "#000000",
}
LEGEND = [
    ("Output HIGH", "out_hi"), ("Output LOW", "out_lo"),
    ("Input HIGH", "in_hi"), ("Input LOW", "in_lo"),
    ("Alt function", "alt"), ("3V3", "3V3"), ("5V", "5V"), ("GND", "GND"),
]


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=2).stdout


def parse_pinctrl(text):
    """' 27: op dh pd | hi // GPIO27 = output'  ->  {27: ('op', 'hi')}"""
    states = {}
    for line in text.splitlines():
        if "|" not in line or ":" not in line:
            continue
        left, right = line.split("|", 1)
        tokens = left.replace(":", " ", 1).split()
        if len(tokens) < 2 or not tokens[0].isdigit():
            continue
        rest = right.split()
        states[int(tokens[0])] = (tokens[1], rest[0] if rest else "?")
    return states


def parse_raspi_gpio(text):
    """'GPIO 27: level=1 fsel=1 func=OUTPUT pull=DOWN'  ->  {27: ('op', 'hi')}"""
    states = {}
    for line in text.splitlines():
        if not line.startswith("GPIO ") or "level=" not in line:
            continue
        head, _, rest = line.partition(":")
        fields = dict(f.split("=", 1) for f in rest.split() if "=" in f)
        func = fields.get("func", "").upper()
        if func == "INPUT":
            mode = "ip"
        elif func == "OUTPUT":
            mode = "op"
        else:
            mode = func.lower().replace("alt", "a")
        level = "hi" if fields.get("level") == "1" else "lo"
        states[int(head.split()[1])] = (mode, level)
    return states


def read_gpio():
    if shutil.which("pinctrl"):
        return parse_pinctrl(run(["pinctrl", "get"])), "pinctrl"
    if shutil.which("raspi-gpio"):
        return parse_raspi_gpio(run(["raspi-gpio", "get"])), "raspi-gpio"
    raise RuntimeError("Neither pinctrl nor raspi-gpio is installed")


def describe(info):
    """Return (status text, colour) for one GPIO's (mode, level)."""
    if info is None:
        return "?", COLORS["unknown"]
    mode, level = info
    lvl = "HI" if level == "hi" else "LO" if level == "lo" else "?"
    if mode == "op":
        return f"OUT {lvl}", COLORS["out_hi" if lvl == "HI" else "out_lo"]
    if mode == "ip":
        return f"IN  {lvl}", COLORS["in_hi" if lvl == "HI" else "in_lo"]
    if mode.startswith("a") and mode[1:].isdigit():
        return f"{mode.upper()}  {lvl}", COLORS["alt"]
    return f"--  {lvl}", COLORS["unknown"]


class App:
    def __init__(self, root):
        self.root = root
        root.title("Raspberry Pi GPIO status")
        root.configure(bg=BG)
        root.resizable(False, False)

        mono = tkfont.Font(family="DejaVu Sans Mono", size=12)
        bold = tkfont.Font(family="DejaVu Sans Mono", size=12, weight="bold")

        grid = tk.Frame(root, bg=BG, padx=14, pady=10)
        grid.pack()

        self.widgets = {}  # physical pin -> (canvas, oval id, text label)
        for row in range(20):
            left_pin, right_pin = row * 2 + 1, row * 2 + 2
            for pin, side in ((left_pin, "left"), (right_pin, "right")):
                label = tk.Label(grid, text="", font=mono, bg=BG, fg=FG, width=19,
                                 anchor="e" if side == "left" else "w")
                canvas = tk.Canvas(grid, width=22, height=22, bg=BG, highlightthickness=0)
                oval = canvas.create_oval(2, 2, 20, 20, fill=COLORS["unknown"], outline="#888")
                number = tk.Label(grid, text=str(pin), font=bold, bg=BG, fg="#9aa0aa", width=3)
                if side == "left":
                    label.grid(row=row, column=0, pady=1)
                    canvas.grid(row=row, column=1, padx=3)
                    number.grid(row=row, column=2)
                else:
                    number.grid(row=row, column=3)
                    canvas.grid(row=row, column=4, padx=3)
                    label.grid(row=row, column=5, pady=1)
                self.widgets[pin] = (canvas, oval, label, side)

        legend = tk.Frame(root, bg=BG, pady=4)
        legend.pack()
        for text, key in LEGEND:
            c = tk.Canvas(legend, width=16, height=16, bg=BG, highlightthickness=0)
            c.create_oval(1, 1, 15, 15, fill=COLORS[key], outline="#888")
            c.pack(side="left", padx=(8, 2))
            tk.Label(legend, text=text, font=("DejaVu Sans", 9), bg=BG, fg=FG).pack(side="left")

        self.status = tk.Label(root, text="", font=("DejaVu Sans", 9), bg=BG, fg="#9aa0aa", pady=6)
        self.status.pack()

        self.refresh()

    def paint(self, pin, text, color):
        canvas, oval, label, side = self.widgets[pin]
        canvas.itemconfig(oval, fill=color)
        label.config(text=text)

    def refresh(self):
        try:
            states, source = read_gpio()
            err = None
        except Exception as e:  # keep the window alive and show the problem
            states, source, err = {}, "", str(e)

        for pin, what in HEADER.items():
            if isinstance(what, str):  # power / ground
                name, status, color = what, "", COLORS[what]
            else:
                name = f"GPIO{what}"
                status, color = describe(states.get(what))
            text = f"{status}  {name}" if self.widgets[pin][3] == "left" else f"{name}  {status}"
            self.paint(pin, text.strip() if not status else text, color)

        if err:
            self.status.config(text=f"Error: {err}", fg="#ff6b6b")
        else:
            self.status.config(
                text=f"Read with {source}, every {REFRESH_MS} ms. Last update {time.strftime('%H:%M:%S')}",
                fg="#9aa0aa")
        self.root.after(REFRESH_MS, self.refresh)


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
