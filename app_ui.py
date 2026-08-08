"""
app_ui.py — the floating panel: two vertical sliders, three presets, one ZAP
button.

Uses customtkinter so it looks modern (rounded corners, dark theme) without
pulling in something heavy like Electron.

The warmth slider holds an "intensity" from 0.0 to 1.0 rather than a raw
Kelvin value, so that dragging *up* always means *more effect* — Kelvin runs
backwards (6500 neutral down to 1200 deep amber), which feels wrong under a
finger. intensity_to_kelvin() below is the only place that mapping lives.
"""

import json
import os
import customtkinter as ctk

from gamma import (
    GammaController,
    KELVIN_MAX,
    KELVIN_MIN,
    kelvin_to_hex,
)

SETTINGS_PATH = os.path.expanduser("~/.eyeease_settings.json")

# -- palette ------------------------------------------------------------
BG = "#0d0d0f"
SURFACE = "#17171b"
SURFACE_HI = "#232329"
ACCENT = "#ff5a36"
ACCENT_DIM = "#7a2b1a"
TEXT = "#f2f2f4"
TEXT_MUTED = "#8a8a94"

# Presets are written in Kelvin because that's the unit people actually
# reason about ("2700K is a warm bulb"), then converted to slider intensity.
PRESETS = {
    "Reading": {"kelvin": 4000, "brightness": 0.90},
    "Evening": {"kelvin": 2700, "brightness": 0.70},
    "Sleep": {"kelvin": 1900, "brightness": 0.45},
}

# How long a preset / on-off change takes to ease in, in milliseconds.
# Slider drags are applied instantly instead — animating those would feel
# like input lag.
TRANSITION_MS = 380
TRANSITION_STEPS = 16


def intensity_to_kelvin(intensity: float) -> float:
    """Slider position (0.0-1.0, up = warmer) -> colour temperature."""
    intensity = max(0.0, min(1.0, intensity))
    return KELVIN_MAX - intensity * (KELVIN_MAX - KELVIN_MIN)


def kelvin_to_intensity(kelvin: float) -> float:
    """Inverse of intensity_to_kelvin(), for loading presets into the slider."""
    kelvin = max(KELVIN_MIN, min(KELVIN_MAX, kelvin))
    return (KELVIN_MAX - kelvin) / (KELVIN_MAX - KELVIN_MIN)


def load_settings():
    defaults = {"intensity": 0.6, "brightness": 0.8, "is_on": True, "pwm_safe": False}
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH) as f:
                saved = json.load(f)
        except (json.JSONDecodeError, OSError):
            return defaults
        # Settings written before the Kelvin rewrite used "warmth" on the
        # same 0.0-1.0 scale, so it carries over as-is under the new name.
        if "warmth" in saved and "intensity" not in saved:
            saved["intensity"] = saved.pop("warmth")
        defaults.update({k: v for k, v in saved.items() if k in defaults})
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

        self.gamma = GammaController()
        self.settings = load_settings()

        # Handles for pending after() callbacks so they can be cancelled on
        # close — otherwise a transition mid-flight fires against a destroyed
        # window and throws.
        self._anim_job = None
        self._save_job = None

        self.title("EyeEase")
        # Tall enough for every row to fit without pack() squeezing the last
        # widgets — the panel has no scroll, so an overflow silently clips the
        # ZAP button right off the bottom.
        self.geometry("360x624")
        self.resizable(False, False)
        self.configure(fg_color=BG)
        self.attributes("-topmost", True)  # small utility window stays on top

        self._build_ui()
        if self.settings["pwm_safe"]:
            # Restore the saved mode, but only if the hardware still allows
            # it — otherwise correct the switch rather than lie about it.
            if not self.gamma.enable_pwm_safe():
                self.settings["pwm_safe"] = False
                self.pwm_switch.deselect()
        self._apply_current()

    # -- construction ----------------------------------------------------
    def _build_ui(self):
        self._build_header()
        self._build_sliders()
        self._build_swatch()
        self._build_presets()
        self._build_pwm_row()
        self._build_zap_button()
        self._refresh_readouts()
        self._update_power_state()

    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=22, pady=(20, 16))

        wordmark = ctk.CTkFrame(header, fg_color="transparent")
        wordmark.pack(side="left")
        ctk.CTkLabel(
            wordmark,
            text="EYE",
            font=ctk.CTkFont(size=19, weight="bold"),
            text_color=TEXT,
        ).pack(side="left")
        ctk.CTkLabel(
            wordmark,
            text="EASE",
            font=ctk.CTkFont(size=19, weight="bold"),
            text_color=ACCENT,
        ).pack(side="left")

        self.status_dot = ctk.CTkLabel(
            header, text="●", font=ctk.CTkFont(size=13), text_color=ACCENT
        )
        self.status_dot.pack(side="right")

    def _build_sliders(self):
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=22, pady=(0, 14))
        row.grid_columnconfigure((0, 1), weight=1, uniform="sliders")

        self.warmth_slider, self.warmth_readout = self._add_slider_column(
            row, 0, "WARMTH", self.settings["intensity"], min_val=0.0
        )
        self.brightness_slider, self.brightness_readout = self._add_slider_column(
            row, 1, "BRIGHTNESS", self.settings["brightness"], min_val=0.15
        )

    def _add_slider_column(self, parent, column, label, initial, min_val):
        """One labelled vertical slider with a big value readout underneath."""
        col = ctk.CTkFrame(parent, fg_color=SURFACE, corner_radius=14)
        col.grid(row=0, column=column, sticky="nsew", padx=(0, 10) if column == 0 else (10, 0))

        ctk.CTkLabel(
            col,
            text=label,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=TEXT_MUTED,
        ).pack(pady=(16, 10))

        slider = ctk.CTkSlider(
            col,
            from_=min_val,
            to=1.0,
            orientation="vertical",
            height=178,
            width=18,
            button_length=22,
            corner_radius=9,
            fg_color=SURFACE_HI,
            progress_color=ACCENT,
            button_color=TEXT,
            button_hover_color=ACCENT,
            command=lambda v: self._on_slider_change(),
        )
        slider.set(initial)
        slider.pack()

        readout = ctk.CTkLabel(
            col, text="", font=ctk.CTkFont(size=17, weight="bold"), text_color=TEXT
        )
        readout.pack(pady=(12, 16))

        return slider, readout

    def _build_swatch(self):
        """A thin strip showing the colour a white pixel will actually become,
        so the sliders preview themselves without the user hunting for a
        white window to look at."""
        wrap = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=12)
        wrap.pack(fill="x", padx=22, pady=(0, 14))

        ctk.CTkLabel(
            wrap,
            text="PREVIEW",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=TEXT_MUTED,
        ).pack(pady=(12, 8))

        self.swatch = ctk.CTkFrame(wrap, height=26, corner_radius=8, fg_color="#ffffff")
        self.swatch.pack(fill="x", padx=14, pady=(0, 14))

    def _build_presets(self):
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=22, pady=(0, 14))
        # grid with a uniform group rather than pack(expand=True) — pack
        # divides only the *leftover* space, so the widest label wins and the
        # last button gets squeezed to a sliver.
        row.grid_columnconfigure((0, 1, 2), weight=1, uniform="presets")

        self.preset_buttons = {}
        for i, name in enumerate(PRESETS):
            button = ctk.CTkButton(
                row,
                text=name.upper(),
                height=34,
                corner_radius=10,
                font=ctk.CTkFont(size=11, weight="bold"),
                fg_color=SURFACE,
                hover_color=SURFACE_HI,
                text_color=TEXT_MUTED,
                command=lambda n=name: self._apply_preset(n),
            )
            button.grid(
                row=0,
                column=i,
                sticky="ew",
                padx=(0 if i == 0 else 4, 0 if i == 2 else 4),
            )
            self.preset_buttons[name] = button

    def _build_pwm_row(self):
        row = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=12)
        row.pack(fill="x", padx=22, pady=(0, 16))

        self.pwm_switch = ctk.CTkSwitch(
            row,
            text="PWM-safe mode",
            font=ctk.CTkFont(size=12),
            text_color=TEXT,
            progress_color=ACCENT,
            button_color=TEXT,
            command=self._toggle_pwm_safe,
        )
        if self.settings["pwm_safe"]:
            self.pwm_switch.select()
        self.pwm_switch.pack(side="left", padx=14, pady=13)

        # Populated only when the switch refuses to engage, so the user learns
        # why instead of watching it silently flip back.
        self.pwm_note = ctk.CTkLabel(
            row, text="", font=ctk.CTkFont(size=10), text_color=TEXT_MUTED
        )
        self.pwm_note.pack(side="right", padx=14)

    def _build_zap_button(self):
        self.zap_button = ctk.CTkButton(
            self,
            text="⚡  ZAP",
            height=54,
            corner_radius=14,
            font=ctk.CTkFont(size=17, weight="bold"),
            fg_color=ACCENT,
            hover_color="#ff734f",
            text_color="#120704",
            command=self._toggle_on_off,
        )
        self.zap_button.pack(fill="x", padx=22, pady=(0, 22))

    # -- interaction -----------------------------------------------------
    def _on_slider_change(self):
        self.settings["intensity"] = self.warmth_slider.get()
        self.settings["brightness"] = self.brightness_slider.get()
        # A drag means the user is deliberately setting a value, so treat it
        # as turning the effect on rather than fighting an "off" state.
        if not self.settings["is_on"]:
            self.settings["is_on"] = True
            self._update_power_state()
        self._cancel_animation()
        self._apply_current()

    def _apply_preset(self, name):
        preset = PRESETS[name]
        target_intensity = kelvin_to_intensity(preset["kelvin"])
        if not self.settings["is_on"]:
            self.settings["is_on"] = True
            self._update_power_state()
        self._animate_to(target_intensity, preset["brightness"])

    def _toggle_on_off(self):
        self.settings["is_on"] = not self.settings["is_on"]
        self._update_power_state()
        if self.settings["is_on"]:
            # Ease back to wherever the sliders are sitting.
            self._animate_to(
                self.warmth_slider.get(), self.brightness_slider.get(), from_neutral=True
            )
        else:
            self._animate_to(0.0, 1.0, keep_sliders=True)

    def _toggle_pwm_safe(self):
        turning_on = self.pwm_switch.get() == 1
        if turning_on:
            if not self.gamma.enable_pwm_safe():
                # Couldn't reach the backlight (unsupported hardware, no
                # permission, etc.) — leave the switch off instead of
                # claiming a mode that isn't actually active.
                self.pwm_switch.deselect()
                self.pwm_note.configure(text="unavailable on this display")
                turning_on = False
            else:
                self.pwm_note.configure(text="backlight locked 100%")
        else:
            self.gamma.disable_pwm_safe()
            self.pwm_note.configure(text="")
        self.settings["pwm_safe"] = turning_on
        self._queue_save()

    # -- transitions -----------------------------------------------------
    def _cancel_animation(self):
        if self._anim_job is not None:
            self.after_cancel(self._anim_job)
            self._anim_job = None

    def _animate_to(self, intensity, brightness, keep_sliders=False, from_neutral=False):
        """Ease the screen from where it is now to the given values.

        keep_sliders leaves the slider positions alone (used when switching
        off, so the user's chosen values are still there when they switch
        back on). from_neutral starts the ease at an untinted screen, which
        is where the display actually is after being switched off.
        """
        self._cancel_animation()

        start_i = 0.0 if from_neutral else self.warmth_slider.get()
        start_b = 1.0 if from_neutral else self.brightness_slider.get()

        def step(n):
            t = n / TRANSITION_STEPS
            eased = t * t * (3 - 2 * t)  # smoothstep — no abrupt start or stop
            cur_i = start_i + (intensity - start_i) * eased
            cur_b = start_b + (brightness - start_b) * eased

            if not keep_sliders:
                self.warmth_slider.set(cur_i)
                self.brightness_slider.set(cur_b)
                self.settings["intensity"] = cur_i
                self.settings["brightness"] = cur_b
                self._refresh_readouts(cur_i, cur_b)

            self.gamma.apply(intensity_to_kelvin(cur_i), cur_b)

            if n < TRANSITION_STEPS:
                self._anim_job = self.after(
                    TRANSITION_MS // TRANSITION_STEPS, step, n + 1
                )
            else:
                self._anim_job = None
                if keep_sliders:
                    # Switching off eases the *screen* back to neutral but
                    # leaves the controls showing the user's settings, so the
                    # readouts have to follow the sliders rather than the
                    # animation — otherwise the panel claims 6500K/100% while
                    # the sliders plainly sit somewhere else.
                    self._refresh_readouts()
                self._queue_save()

        step(0)

    # -- rendering -------------------------------------------------------
    def _refresh_readouts(self, intensity=None, brightness=None):
        if intensity is None:
            intensity = self.warmth_slider.get()
        if brightness is None:
            brightness = self.brightness_slider.get()

        kelvin = intensity_to_kelvin(intensity)
        self.warmth_readout.configure(text=f"{int(round(kelvin / 50) * 50)}K")
        self.brightness_readout.configure(text=f"{int(round(brightness * 100))}%")

        # The swatch shows the tint only — not the dimming — because a strip
        # that goes near-black at low brightness stops communicating colour.
        self.swatch.configure(fg_color=kelvin_to_hex(kelvin))

        self._update_preset_highlight(kelvin, brightness)

    def _update_preset_highlight(self, kelvin, brightness):
        """Light up whichever preset the current values correspond to, so the
        row reads as state and not just as three buttons."""
        for name, button in self.preset_buttons.items():
            preset = PRESETS[name]
            active = (
                abs(kelvin - preset["kelvin"]) < 60
                and abs(brightness - preset["brightness"]) < 0.02
                and self.settings["is_on"]
            )
            button.configure(
                fg_color=ACCENT_DIM if active else SURFACE,
                text_color=TEXT if active else TEXT_MUTED,
            )

    def _update_power_state(self):
        on = self.settings["is_on"]
        self.zap_button.configure(
            text="⚡  ZAP" if on else "⚡  ZAPPED OFF",
            fg_color=ACCENT if on else SURFACE_HI,
            text_color="#120704" if on else TEXT_MUTED,
            hover_color="#ff734f" if on else SURFACE_HI,
        )
        self.status_dot.configure(text_color=ACCENT if on else ACCENT_DIM)

    # -- persistence -----------------------------------------------------
    def _queue_save(self):
        """Debounced — a slider drag fires this dozens of times a second and
        each one would otherwise be a separate disk write."""
        if self._save_job is not None:
            self.after_cancel(self._save_job)
        self._save_job = self.after(400, self._flush_save)

    def _flush_save(self):
        self._save_job = None
        save_settings(self.settings)

    # -- lifecycle -------------------------------------------------------
    def _apply_current(self):
        if self.settings["is_on"]:
            self.gamma.apply(
                intensity_to_kelvin(self.settings["intensity"]),
                self.settings["brightness"],
            )
        else:
            self.gamma.reset()
        self._refresh_readouts()
        self._queue_save()

    def on_close(self):
        """Call this before quitting so the screen doesn't stay tinted."""
        self._cancel_animation()
        if self._save_job is not None:
            self.after_cancel(self._save_job)
            self._save_job = None
        self.gamma.reset()
        if self.settings["pwm_safe"]:
            self.gamma.disable_pwm_safe()
        save_settings(self.settings)
        self.destroy()
