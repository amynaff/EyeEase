"""
app_ui.py — the floating panel: two vertical sliders, three presets, one
EASE button.

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
from auto_schedule import (
    Schedule,
    parse_hhmm,
    parse_latitude,
    parse_longitude,
)
import brand
import startup

SETTINGS_PATH = os.path.expanduser("~/.eyeease_settings.json")

# Palette comes from brand.py so the panel, tray icon and app icon can't
# drift apart. ACCENT/ACCENT_DIM are kept as local names because they read
# better at the call sites than AMBER/AMBER_DIM do.
ACCENT = brand.AMBER
ACCENT_HOVER = brand.AMBER_BRIGHT
ACCENT_DIM = brand.AMBER_DIM
INK = brand.INK
BG = brand.BG
SURFACE = brand.SURFACE
SURFACE_HI = brand.SURFACE_HI
TEXT = brand.TEXT
TEXT_MUTED = brand.TEXT_MUTED

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

# How often the auto schedule re-checks the clock. The fade lasts tens of
# minutes, so a 30s tick is far finer than the eye can follow — the point is
# just to never be visibly behind.
TICK_MS = 30_000

# Fixed width; height is measured from the content in _fit_to_content().
PANEL_WIDTH = 360

# Labels on the schedule mode selector, mapped to Schedule.mode.
MODE_FIXED = "Fixed times"
MODE_SOLAR = "Sunset/sunrise"


def intensity_to_kelvin(intensity: float) -> float:
    """Slider position (0.0-1.0, up = warmer) -> colour temperature."""
    intensity = max(0.0, min(1.0, intensity))
    return KELVIN_MAX - intensity * (KELVIN_MAX - KELVIN_MIN)


def kelvin_to_intensity(kelvin: float) -> float:
    """Inverse of intensity_to_kelvin(), for loading presets into the slider."""
    kelvin = max(KELVIN_MIN, min(KELVIN_MAX, kelvin))
    return (KELVIN_MAX - kelvin) / (KELVIN_MAX - KELVIN_MIN)


def load_settings():
    defaults = {
        "intensity": 0.6,
        "brightness": 0.8,
        "is_on": True,
        "pwm_safe": False,
        "auto": False,
        "schedule": Schedule().to_dict(),
    }
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
        self.schedule = Schedule.from_dict(self.settings["schedule"])

        # Handles for pending after() callbacks so they can be cancelled on
        # close — otherwise a transition mid-flight fires against a destroyed
        # window and throws.
        self._anim_job = None
        self._save_job = None
        self._tick_job = None

        # Window position is tracked by hand because a borderless window has
        # to be re-positioned after overrideredirect(), and dragging it is
        # our job rather than the window manager's.
        self._window_x, self._window_y = 120, 90
        self._drag_offset = None
        self._chrome_stripped = False

        self.title("EyeEase")
        self.geometry(f"{PANEL_WIDTH}x600+{self._window_x}+{self._window_y}")
        self.resizable(False, False)
        self.configure(fg_color=BG)
        self.attributes("-topmost", True)  # small utility window stays on top

        self._build_ui()
        self._fit_to_content()
        if self.settings["pwm_safe"]:
            # Restore the saved mode, but only if the hardware still allows
            # it — otherwise correct the switch rather than lie about it.
            if not self.gamma.enable_pwm_safe():
                self.settings["pwm_safe"] = False
                self.pwm_switch.deselect()
                self.pwm_note.configure(text="can't control this backlight")
        self._apply_current()
        self._start_ticking()
        # Deferred so the window is mapped first — see _strip_chrome().
        self.after(80, self._strip_chrome)

    def _fit_to_content(self):
        """Size the window to whatever the rows actually need.

        The panel doesn't scroll, so a hardcoded height that's a few pixels
        short doesn't overflow visibly — pack() just squeezes the last
        widgets and the EASE button disappears off the bottom. Asking Tk for
        the required height means adding a row can't reintroduce that.
        """
        self.update_idletasks()
        height = self.winfo_reqheight()
        self.geometry(f"{PANEL_WIDTH}x{height}+{self._window_x}+{self._window_y}")

    # -- window chrome ---------------------------------------------------
    def _strip_chrome(self):
        """Drop the OS title bar, leaving a bare floating panel.

        Has to run *after* the window has been mapped: calling
        overrideredirect() before the first draw leaves macOS with a window
        it never puts on screen — it reports a sensible geometry and simply
        isn't visible. Re-asserting geometry and re-mapping afterwards is
        what makes it appear.

        macOS draws rounded corners and a drop shadow on the result by
        itself, so nothing here has to fake them.
        """
        try:
            self.overrideredirect(True)
        except Exception:
            # Not worth failing the whole app over cosmetics — a title bar is
            # a perfectly usable fallback.
            self._chrome_stripped = False
            return

        self.geometry(f"+{self._window_x}+{self._window_y}")
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self._chrome_stripped = True

    def _make_draggable(self, widget):
        widget.bind("<Button-1>", self._drag_start)
        widget.bind("<B1-Motion>", self._drag_move)

    def _drag_start(self, event):
        self._drag_offset = (
            event.x_root - self.winfo_x(),
            event.y_root - self.winfo_y(),
        )

    def _drag_move(self, event):
        if self._drag_offset is None:
            return
        self._window_x = event.x_root - self._drag_offset[0]
        self._window_y = event.y_root - self._drag_offset[1]
        self.geometry(f"+{self._window_x}+{self._window_y}")

    def show_panel(self):
        """Bring the panel back from the tray.

        deiconify() alone can restore a borderless window without raising it,
        which looks identical to the app ignoring the tray click, so lift and
        re-assert topmost too.
        """
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)

    # -- construction ----------------------------------------------------
    def _build_ui(self):
        self._build_header()
        self._build_sliders()
        self._build_presets()
        self._build_schedule_row()
        self._build_options_card()
        self._build_power_button()
        self._refresh_readouts()
        self._update_power_state()
        self._update_schedule_row()

    def _build_header(self):
        """The header doubles as the title bar: it's the drag handle, and it
        carries the only close affordance now that the OS one is gone."""
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=22, pady=(18, 16))

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

        # Hides to the tray rather than quitting, matching what the OS close
        # button did before — Quit lives in the tray menu, and only Quit puts
        # the screen back to normal.
        self.close_button = ctk.CTkButton(
            header,
            text="✕",
            width=26,
            height=26,
            corner_radius=13,
            font=ctk.CTkFont(size=13),
            fg_color="transparent",
            hover_color=SURFACE_HI,
            text_color=TEXT_MUTED,
            command=self.withdraw,
        )
        self.close_button.pack(side="right")

        self.status_dot = ctk.CTkLabel(
            header, text="●", font=ctk.CTkFont(size=13), text_color=ACCENT
        )
        self.status_dot.pack(side="right", padx=(0, 10))

        # Everything in the header drags the window except the close button.
        self._make_draggable(header)
        self._make_draggable(wordmark)
        self._make_draggable(self.status_dot)

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
            height=158,
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

    def _build_schedule_row(self):
        """Auto switch, a live status line, and the two clock times.

        The sliders keep meaning 'what I want at night' while this is on —
        during the day the screen sits neutral and eases toward those values
        as the fade runs, which is what the status line spells out.
        """
        box = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=12)
        box.pack(fill="x", padx=22, pady=(0, 14))

        top = ctk.CTkFrame(box, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(12, 0))

        self.auto_switch = ctk.CTkSwitch(
            top,
            text="Auto schedule",
            font=ctk.CTkFont(size=12),
            text_color=TEXT,
            progress_color=ACCENT,
            button_color=TEXT,
            command=self._toggle_auto,
        )
        if self.settings["auto"]:
            self.auto_switch.select()
        self.auto_switch.pack(side="left")

        self.schedule_status = ctk.CTkLabel(
            top, text="", font=ctk.CTkFont(size=11), text_color=TEXT_MUTED
        )
        self.schedule_status.pack(side="right")

        # Two plain buttons rather than CTkSegmentedButton: that widget uses
        # one text colour for every segment, so whatever reads well on the
        # amber selection is unreadable on the dark unselected one. This is
        # the same active/inactive treatment the presets row uses.
        mode_row = ctk.CTkFrame(box, fg_color="transparent")
        mode_row.pack(fill="x", padx=14, pady=(10, 0))
        mode_row.grid_columnconfigure((0, 1), weight=1, uniform="modes")

        self.mode_buttons = {}
        for i, (label, mode) in enumerate(
            ((MODE_FIXED, "fixed"), (MODE_SOLAR, "solar"))
        ):
            button = ctk.CTkButton(
                mode_row,
                text=label,
                height=28,
                corner_radius=8,
                font=ctk.CTkFont(size=11, weight="bold"),
                command=lambda m=mode: self._change_schedule_mode(m),
            )
            button.grid(row=0, column=i, sticky="ew", padx=(0, 4) if i == 0 else (4, 0))
            self.mode_buttons[mode] = button
        self._update_mode_buttons()

        # Both input rows are built once and swapped by packing, so switching
        # mode never loses what was typed in the other one.
        self.times_row = ctk.CTkFrame(box, fg_color="transparent")
        ctk.CTkLabel(
            self.times_row, text="Warm from", font=ctk.CTkFont(size=11),
            text_color=TEXT_MUTED,
        ).pack(side="left")
        self.start_entry = self._add_time_entry(self.times_row, self.schedule.start)
        ctk.CTkLabel(
            self.times_row, text="to", font=ctk.CTkFont(size=11),
            text_color=TEXT_MUTED,
        ).pack(side="left", padx=(8, 0))
        self.end_entry = self._add_time_entry(self.times_row, self.schedule.end)

        self.coords_row = ctk.CTkFrame(box, fg_color="transparent")
        ctk.CTkLabel(
            self.coords_row, text="Lat", font=ctk.CTkFont(size=11),
            text_color=TEXT_MUTED,
        ).pack(side="left")
        self.lat_entry = self._add_coord_entry(
            self.coords_row, self.schedule.latitude
        )
        ctk.CTkLabel(
            self.coords_row, text="Lon", font=ctk.CTkFont(size=11),
            text_color=TEXT_MUTED,
        ).pack(side="left", padx=(10, 0))
        self.lon_entry = self._add_coord_entry(
            self.coords_row, self.schedule.longitude
        )

        self._show_schedule_inputs()

    def _show_schedule_inputs(self):
        """Pack whichever input row matches the current mode."""
        self.times_row.pack_forget()
        self.coords_row.pack_forget()
        row = self.coords_row if self.schedule.mode == "solar" else self.times_row
        row.pack(fill="x", padx=14, pady=(8, 12))

    def _update_mode_buttons(self):
        for mode, button in self.mode_buttons.items():
            active = self.schedule.mode == mode
            button.configure(
                fg_color=ACCENT_DIM if active else SURFACE_HI,
                hover_color=ACCENT_DIM if active else SURFACE_HI,
                text_color=TEXT if active else TEXT_MUTED,
            )

    def _change_schedule_mode(self, mode):
        self.schedule.mode = mode
        self.settings["schedule"] = self.schedule.to_dict()
        self._update_mode_buttons()
        self._show_schedule_inputs()
        self._fit_to_content()
        self._update_schedule_row()
        self._apply_current()
        self._queue_save()

    def _add_coord_entry(self, parent, value):
        entry = ctk.CTkEntry(
            parent,
            width=78,
            height=28,
            corner_radius=8,
            justify="center",
            font=ctk.CTkFont(size=12),
            fg_color=SURFACE_HI,
            border_width=0,
            text_color=TEXT,
            placeholder_text="—",
        )
        if value is not None:
            entry.insert(0, f"{value:g}")
        entry.bind("<Return>", lambda _e: self._commit_coords())
        entry.bind("<FocusOut>", lambda _e: self._commit_coords())
        entry.pack(side="left", padx=(8, 0))
        return entry

    def _commit_coords(self):
        """Validate both coordinates, keeping each only if it parses.

        Empty is allowed and means "not set" — that's how you clear a
        coordinate, and the schedule reports itself unusable rather than
        guessing a location.
        """
        for entry, parser, attribute in (
            (self.lat_entry, parse_latitude, "latitude"),
            (self.lon_entry, parse_longitude, "longitude"),
        ):
            raw = entry.get().strip()
            if not raw:
                setattr(self.schedule, attribute, None)
                entry.delete(0, "end")
                continue

            parsed = parser(raw)
            if parsed is None:
                # Put back the last good value rather than leaving something
                # that looks accepted but isn't.
                previous = getattr(self.schedule, attribute)
                entry.delete(0, "end")
                if previous is not None:
                    entry.insert(0, f"{previous:g}")
            else:
                setattr(self.schedule, attribute, parsed)
                entry.delete(0, "end")
                entry.insert(0, f"{parsed:g}")

        self.settings["schedule"] = self.schedule.to_dict()
        self._update_schedule_row()
        self._apply_current()
        self._queue_save()

    def _add_time_entry(self, parent, value):
        entry = ctk.CTkEntry(
            parent,
            width=62,
            height=28,
            corner_radius=8,
            justify="center",
            font=ctk.CTkFont(size=12),
            fg_color=SURFACE_HI,
            border_width=0,
            text_color=TEXT,
        )
        entry.insert(0, value)
        # Commit on Enter or when focus leaves, rather than per keystroke —
        # "2" on the way to "20:00" isn't a time, and rejecting it mid-typing
        # would fight the user.
        entry.bind("<Return>", lambda _e: self._commit_times())
        entry.bind("<FocusOut>", lambda _e: self._commit_times())
        entry.pack(side="left", padx=(8, 0))
        return entry

    def _build_options_card(self):
        """The two on/off options that aren't about colour, in one card."""
        card = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=12)
        card.pack(fill="x", padx=22, pady=(0, 16))

        self.pwm_switch, self.pwm_note = self._add_option_row(
            card, "PWM-safe mode", self._toggle_pwm_safe, first=True
        )
        if self.settings["pwm_safe"]:
            self.pwm_switch.select()

        if startup.is_supported():
            self.login_switch, self.login_note = self._add_option_row(
                card, "Launch at login", self._toggle_login, first=False
            )
            # Read from the OS, never from saved settings — someone may have
            # removed the login item by hand since last run, and the switch
            # should show what's actually true.
            if startup.is_enabled():
                self.login_switch.select()
        else:
            self.login_switch = None
            self.login_note = None

    def _add_option_row(self, parent, label, command, first):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(12, 12) if first else (0, 12))

        switch = ctk.CTkSwitch(
            row,
            text=label,
            font=ctk.CTkFont(size=12),
            text_color=TEXT,
            progress_color=ACCENT,
            button_color=TEXT,
            command=command,
        )
        switch.pack(side="left")

        # Populated only when something needs explaining — a switch that
        # refuses to engage says why instead of silently flipping back.
        note = ctk.CTkLabel(
            row, text="", font=ctk.CTkFont(size=10), text_color=TEXT_MUTED
        )
        note.pack(side="right")
        return switch, note

    def _toggle_login(self):
        turning_on = self.login_switch.get() == 1
        succeeded = startup.enable() if turning_on else startup.disable()

        if not succeeded:
            # Put the switch back where it was rather than leaving it
            # claiming a login item that isn't there.
            if turning_on:
                self.login_switch.deselect()
            else:
                self.login_switch.select()
            self.login_note.configure(text="couldn't update login items")
            return

        self.login_note.configure(text="takes effect next login" if turning_on else "")

    def _build_power_button(self):
        # Two pre-rendered marks rather than one recoloured on the fly: the
        # iris is punched in the button's own colour, so the "off" mark has
        # to be drawn against the off background to stay an eye and not a
        # blob. Both are held on self because CTkImage doesn't keep the
        # underlying PIL image alive on its own.
        self.eye_mark_on = ctk.CTkImage(
            light_image=brand.eye_image(22, brand.INK, ACCENT),
            dark_image=brand.eye_image(22, brand.INK, ACCENT),
            size=(22, 22),
        )
        self.eye_mark_off = ctk.CTkImage(
            light_image=brand.eye_image(22, TEXT_MUTED, SURFACE_HI),
            dark_image=brand.eye_image(22, TEXT_MUTED, SURFACE_HI),
            size=(22, 22),
        )

        self.power_button = ctk.CTkButton(
            self,
            text="EASE ON",
            image=self.eye_mark_on,
            compound="left",
            height=54,
            corner_radius=14,
            font=ctk.CTkFont(size=17, weight="bold"),
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color=INK,
            command=self._toggle_on_off,
        )
        self.power_button.pack(fill="x", padx=22, pady=(0, 22))

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

    def _auto_active(self):
        return self.settings["auto"] and self.schedule.is_usable()

    def _apply_preset(self, name):
        preset = PRESETS[name]
        target_intensity = kelvin_to_intensity(preset["kelvin"])
        if not self.settings["is_on"]:
            self.settings["is_on"] = True
            self._update_power_state()

        if self._auto_active():
            # The schedule owns what reaches the screen, so a preset only
            # moves the night target. Easing here would fight the fade and
            # briefly show a warmth the schedule hasn't reached yet.
            self._cancel_animation()
            self.warmth_slider.set(target_intensity)
            self.brightness_slider.set(preset["brightness"])
            self.settings["intensity"] = target_intensity
            self.settings["brightness"] = preset["brightness"]
            self._apply_current()
            return

        self._animate_to(target_intensity, preset["brightness"])

    def _toggle_on_off(self):
        self.settings["is_on"] = not self.settings["is_on"]
        self._update_power_state()
        if self.settings["is_on"]:
            if self._auto_active():
                self._apply_current()
            else:
                # Ease back to wherever the sliders are sitting.
                self._animate_to(
                    self.warmth_slider.get(),
                    self.brightness_slider.get(),
                    from_neutral=True,
                )
        else:
            self._animate_to(0.0, 1.0, keep_sliders=True)

    # -- auto schedule ---------------------------------------------------
    def _toggle_auto(self):
        self.settings["auto"] = self.auto_switch.get() == 1
        self._cancel_animation()
        self._update_schedule_row()
        self._apply_current()
        self._queue_save()

    def _commit_times(self):
        """Validate both entries and keep the schedule only if they parse."""
        start = self.start_entry.get()
        end = self.end_entry.get()

        for entry, value, attribute in (
            (self.start_entry, start, "start"),
            (self.end_entry, end, "end"),
        ):
            parsed = parse_hhmm(value)
            # Rewrite the field either way: back to the last good value if it
            # didn't parse, or zero-padded if it did, so "7:05" doesn't sit
            # there looking different from "20:00".
            text = (
                getattr(self.schedule, attribute)
                if parsed is None
                else "{:02d}:{:02d}".format(*parsed)
            )
            if parsed is not None:
                setattr(self.schedule, attribute, text)
            entry.delete(0, "end")
            entry.insert(0, text)

        self.settings["schedule"] = self.schedule.to_dict()
        self._update_schedule_row()
        self._apply_current()
        self._queue_save()

    def _update_schedule_row(self):
        on = self.settings["auto"]
        self.schedule_status.configure(
            text=self.schedule.status_line() if on else "off",
            text_color=ACCENT if on and self.schedule.fading() else TEXT_MUTED,
        )
        for entry in (
            self.start_entry,
            self.end_entry,
            self.lat_entry,
            self.lon_entry,
        ):
            entry.configure(
                state="normal" if on else "disabled",
                text_color=TEXT if on else TEXT_MUTED,
            )
        for button in self.mode_buttons.values():
            button.configure(state="normal" if on else "disabled")

    def _start_ticking(self):
        self._stop_ticking()

        def tick():
            # Re-arm first so a failure in the body can't silently kill the
            # loop and leave the schedule frozen at whatever it last applied.
            self._tick_job = self.after(TICK_MS, tick)
            if self.settings["auto"]:
                self._update_schedule_row()
                if self._anim_job is None:
                    self._apply_current()
            self._hold_pwm_safe()

        self._tick_job = self.after(TICK_MS, tick)

    def _stop_ticking(self):
        if self._tick_job is not None:
            self.after_cancel(self._tick_job)
            self._tick_job = None

    def _effective_values(self):
        """The values to actually send to the screen right now.

        With auto off that's just the sliders. With auto on the sliders are
        the *night* target, and the schedule says how much of it applies —
        0% at midday, 100% deep in the evening, sliding between the two
        across the fade.
        """
        intensity = self.settings["intensity"]
        brightness = self.settings["brightness"]

        if not self.settings["auto"] or not self.schedule.is_usable():
            return (intensity, brightness)

        fraction = self.schedule.night_fraction()
        # Neutral is intensity 0 / brightness 1, so both blends run from
        # there toward whatever the sliders say.
        return (intensity * fraction, 1.0 - (1.0 - brightness) * fraction)

    def _hold_pwm_safe(self):
        """Keep the backlight pinned while the mode is on, and stop claiming
        the mode if the backlight slips out of our control."""
        if not self.settings["pwm_safe"]:
            return
        if self.gamma.hold_pwm_safe():
            return

        self.settings["pwm_safe"] = False
        self.pwm_switch.deselect()
        self.pwm_note.configure(text="lost control of backlight")
        self._queue_save()

    def _toggle_pwm_safe(self):
        turning_on = self.pwm_switch.get() == 1
        if turning_on:
            if not self.gamma.enable_pwm_safe():
                # Couldn't reach the backlight (unsupported hardware, no
                # permission, etc.) — leave the switch off instead of
                # claiming a mode that isn't actually active.
                self.pwm_switch.deselect()
                self.pwm_note.configure(text="can't control this backlight")
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
        self.warmth_readout.configure(
            text=f"{int(round(kelvin / 50) * 50)}K",
            # The number is drawn in the tint it describes, which is the whole
            # preview: no separate swatch, no label, nothing extra on screen.
            # Tint only, never the dimming — a readout that fades toward black
            # at low brightness would be unreadable rather than informative.
            text_color=kelvin_to_hex(kelvin),
        )
        self.brightness_readout.configure(text=f"{int(round(brightness * 100))}%")

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
        self.power_button.configure(
            text="EASE ON" if on else "EASE OFF",
            image=self.eye_mark_on if on else self.eye_mark_off,
            fg_color=ACCENT if on else SURFACE_HI,
            text_color=INK if on else TEXT_MUTED,
            hover_color=ACCENT_HOVER if on else SURFACE_HI,
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
            intensity, brightness = self._effective_values()
            self.gamma.apply(intensity_to_kelvin(intensity), brightness)
        else:
            self.gamma.reset()
        self._refresh_readouts()
        self._queue_save()

    def on_close(self):
        """Call this before quitting so the screen doesn't stay tinted."""
        self._cancel_animation()
        self._stop_ticking()
        if self._save_job is not None:
            self.after_cancel(self._save_job)
            self._save_job = None
        self.gamma.reset()
        if self.settings["pwm_safe"]:
            self.gamma.disable_pwm_safe()
        save_settings(self.settings)
        self.destroy()
