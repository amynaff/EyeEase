"""
app_ui.py — the floating panel. Two sliders, three presets, one ZAP button.

Uses customtkinter so it looks modern (rounded corners, dark theme) without
pulling in something heavy like Electron.
"""

import json
import os
import customtkinter as ctk

from gamma import GammaController

SETTINGS_PATH = os.path.expanduser("~/.eyeease_settings.json")

PRESETS = {
    "Reading": {"warmth": 0.55, "brightness": 0.9},
    "Evening": {"warmth": 0.8, "brightness": 0.6},
    "Sleep": {"warmth": 1.0, "brightness": 0.3},
}


def load_settings():
    defaults = {"warmth": 0.6, "brightness": 0.8, "is_on": True, "pwm_safe": False}
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH) as f:
                defaults.update(json.load(f))
        except (json.JSONDecodeError, OSError):
            pass
    return defaults


def save_settings(data):
    try:
        with open(SETTINGS_PATH, "w") as f:
            json.dump(data, f)
    except OSError:
        pass


class EyeEaseApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self.gamma = GammaController()
        self.settings = load_settings()

        self.title("")
        self.geometry("300x340")
        self.resizable(False, False)
        self.attributes("-topmost", True)  # small utility window stays on top

        self._build_ui()
        if self.settings["pwm_safe"]:
            self.gamma.enable_pwm_safe()
        self._apply_current()

    def _build_ui(self):
        pad = {"padx": 20, "pady": (0, 14)}

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(20, 10))

        ctk.CTkLabel(
            header, text="TAP ZAP LITE", font=ctk.CTkFont(size=14, weight="bold")
        ).pack(side="left")

        self.zap_button = ctk.CTkButton(
            header,
            text="⚡",
            width=36,
            height=36,
            corner_radius=18,
            command=self._toggle_on_off,
        )
        self.zap_button.pack(side="right")

        self.warmth_slider = self._add_slider("Warmth", pad, self.settings["warmth"])
        self.brightness_slider = self._add_slider(
            "Brightness", pad, self.settings["brightness"], min_val=0.15
        )

        preset_row = ctk.CTkFrame(self, fg_color="transparent")
        preset_row.pack(fill="x", padx=20, pady=(4, 20))
        for name in PRESETS:
            ctk.CTkButton(
                preset_row,
                text=name,
                width=76,
                height=28,
                fg_color="#2a2a2a",
                hover_color="#3a3a3a",
                command=lambda n=name: self._apply_preset(n),
            ).pack(side="left", expand=True, padx=4)

        self.pwm_switch = ctk.CTkSwitch(
            self,
            text="PWM-safe mode",
            font=ctk.CTkFont(size=12),
            command=self._toggle_pwm_safe,
        )
        if self.settings["pwm_safe"]:
            self.pwm_switch.select()
        self.pwm_switch.pack(anchor="w", padx=20, pady=(0, 16))

        self._update_zap_button()

    def _add_slider(self, label, pad, initial, min_val=0.0):
        ctk.CTkLabel(self, text=label, font=ctk.CTkFont(size=12)).pack(
            anchor="w", padx=20
        )
        slider = ctk.CTkSlider(
            self, from_=min_val, to=1.0, command=lambda v: self._on_slider_change()
        )
        slider.set(initial)
        slider.pack(fill="x", **pad)
        return slider

    def _on_slider_change(self):
        self.settings["warmth"] = self.warmth_slider.get()
        self.settings["brightness"] = self.brightness_slider.get()
        self._apply_current()

    def _apply_preset(self, name):
        preset = PRESETS[name]
        self.warmth_slider.set(preset["warmth"])
        self.brightness_slider.set(preset["brightness"])
        self.settings.update(preset)
        self._apply_current()

    def _toggle_on_off(self):
        self.settings["is_on"] = not self.settings["is_on"]
        self._update_zap_button()
        self._apply_current()

    def _toggle_pwm_safe(self):
        turning_on = self.pwm_switch.get() == 1
        if turning_on:
            if not self.gamma.enable_pwm_safe():
                # Couldn't reach the backlight (unsupported hardware, no
                # permission, etc.) — leave the switch off instead of
                # claiming a mode that isn't actually active.
                self.pwm_switch.deselect()
                turning_on = False
        else:
            self.gamma.disable_pwm_safe()
        self.settings["pwm_safe"] = turning_on
        save_settings(self.settings)

    def _update_zap_button(self):
        on = self.settings["is_on"]
        self.zap_button.configure(fg_color="#ff5a36" if on else "#2a2a2a")

    def _apply_current(self):
        if self.settings["is_on"]:
            self.gamma.apply(self.settings["warmth"], self.settings["brightness"])
        else:
            self.gamma.reset()
        save_settings(self.settings)

    def on_close(self):
        """Call this before quitting so the screen doesn't stay tinted."""
        self.gamma.reset()
        if self.settings["pwm_safe"]:
            self.gamma.disable_pwm_safe()
        save_settings(self.settings)
        self.destroy()
