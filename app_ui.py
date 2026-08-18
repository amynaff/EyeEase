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

import atexit
import json
import os
from datetime import datetime

import customtkinter as ctk

from gamma import (
    GammaController,
    KELVIN_MAX,
    KELVIN_MIN,
    kelvin_to_hex,
)
from auto_schedule import Schedule, parse_hhmm
import brand
import cities
import ring
import startup
import tray

SETTINGS_PATH = os.path.expanduser("~/.eyeease_settings.json")

# Palette comes from brand.py so the panel, tray icon and app icon can't
# drift apart. ACCENT/ACCENT_DIM are kept as local names because they read
# better at the call sites than LENS/LENS_DIM do.
ACCENT = brand.LENS
ACCENT_HOVER = brand.LENS_BRIGHT
ACCENT_DIM = brand.LENS_DIM
INK = brand.INK

# The off state has its own colour rather than a grey. See brand.py for
# where the blue comes from and why a blue is safe here specifically.
OFF = brand.BLUE
OFF_HOVER = brand.BLUE_BRIGHT
OFF_INK = brand.BLUE_INK
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

# The backlight lock re-asserts on its own timer rather than riding the tick
# above. 30 seconds is the right cadence for a 45-minute fade and far too
# loose for this: pressing a brightness key hands you back PWM flicker, and
# measured on a build, the backlight sat at 30% for 14 seconds before the
# tick took it back. For someone who turned this mode on *because* flicker
# hurts, 14 seconds of it is the failure the feature exists to prevent.
# Costs one backlight read per interval, and nothing at all while the mode
# is off — _hold_pwm_safe() returns before touching the display.
HOLD_MS = 2_000

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
        "zero_blue": False,
        # What zero-blue mode displaced, kept across restarts so switching
        # the mode off a week later still gives back the right warmth.
        "before_zero_blue": None,
        "pwm_safe": False,
        # The backlight level the lock displaced, written to disk the moment
        # the lock engages. A SIGKILL runs no cleanup code of any kind, so
        # this is the only way the level survives one — see
        # _repair_backlight_after_crash().
        "backlight_before_lock": None,
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
        self._hold_job = None

        # Window position is tracked by hand because a borderless window has
        # to be re-positioned after overrideredirect(), and dragging it is
        # our job rather than the window manager's.
        self._window_x, self._window_y = 120, 90
        self._drag_offset = None
        self._chrome_stripped = False
        self._gamma_failed = False
        self._ring_job = None
        # Set once the menu-bar icon exists; until then the mark can't
        # follow the state because there's nothing to re-draw.
        self._tray_icon = None
        # Parked by tray.py; see _restore_display_on_terminate() for why it
        # has to be held rather than discarded.
        self.terminate_observer = None

        self.title("EyeEase")
        self.geometry(f"{PANEL_WIDTH}x600+{self._window_x}+{self._window_y}")
        self.resizable(False, False)
        self.configure(fg_color=BG)
        self.attributes("-topmost", True)  # small utility window stays on top

        # The screen is a system-wide setting this process borrowed. If the
        # process dies without on_close() running, restore_display() is the
        # last line of defence — see its docstring for why the backlight
        # needs one and the colour doesn't.
        atexit.register(self.restore_display)

        # Before the UI, because building it probes the backlight — and the
        # probe would read a level this may be about to correct.
        self._repair_backlight_after_crash()

        self._build_ui()
        self._fit_to_content()
        if self.settings["pwm_safe"] and self.pwm_switch is not None:
            # Restore the saved mode, but only if the hardware still allows
            # it — otherwise correct the switch rather than lie about it.
            if self.gamma.enable_pwm_safe():
                self._remember_backlight()
            else:
                self.settings["pwm_safe"] = False
                self.pwm_switch.deselect()
                self.pwm_note.configure(text="can't hold this backlight")
        if self.settings["zero_blue"]:
            # Restored rather than re-toggled: enter_zero_blue() would park
            # the mode's own values as if they were the user's.
            self.zero_blue_switch.select()
            holding = self._enable_pwm_for_zero_blue()
            self.zero_blue_note.configure(text=self._zero_blue_note(holding))
            self._sync_zero_blue_controls()
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

        # Fitting the height to the content only helps if the result is
        # somewhere you can see it. Each option row adds ~60px, and the
        # panel opens 90px down by default — enough rows and the EASE
        # button ends up below the bottom of a laptop screen, on a window
        # with no title bar to drag it back by.
        lowest = self.winfo_screenheight() - height - 12
        if self._window_y > lowest:
            self._window_y = max(12, lowest)

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

    RING_SIZE = 156

    def _build_sliders(self):
        """The day ring, then the two controls that feed it.

        The ring replaced a pair of tall vertical sliders. Those worked, but
        they were also the single most recognisable thing about a competitor's
        panel, and they gave the schedule — the part of this app nothing else
        does — no presence at all.
        """
        card = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=14)
        card.pack(fill="x", padx=22, pady=(0, 10))

        holder = ctk.CTkFrame(card, fg_color="transparent",
                              width=self.RING_SIZE, height=self.RING_SIZE)
        holder.pack(pady=(14, 14))
        holder.pack_propagate(False)

        self.ring_label = ctk.CTkLabel(holder, text="")
        self.ring_label.place(relx=0.5, rely=0.5, anchor="center")

        # Native labels sit over the rendered ring rather than being drawn
        # into it: text stays crisp, and updating a reading doesn't mean
        # re-rendering 360 wedges.
        self.warmth_readout = ctk.CTkLabel(
            holder, text="", font=ctk.CTkFont(size=24, weight="bold"),
            text_color=TEXT,
        )
        self.warmth_readout.place(relx=0.5, rely=0.43, anchor="center")

        self.ring_status = ctk.CTkLabel(
            holder, text="", font=ctk.CTkFont(size=10), text_color=TEXT_MUTED,
        )
        self.ring_status.place(relx=0.5, rely=0.60, anchor="center")

        self.warmth_slider = self._add_slider_row(
            "WARMTH", self.settings["intensity"], 0.0
        )
        self.brightness_slider, self.brightness_readout = self._add_slider_row(
            "BRIGHTNESS", self.settings["brightness"], 0.15, with_readout=True
        )

    def _add_slider_row(self, label, initial, min_val, with_readout=False):
        """A horizontal slider with its label and, optionally, its value."""
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=22, pady=(0, 10))

        head = ctk.CTkFrame(row, fg_color="transparent")
        head.pack(fill="x")
        ctk.CTkLabel(
            head, text=label, font=ctk.CTkFont(size=9, weight="bold"),
            text_color=TEXT_MUTED,
        ).pack(side="left")

        readout = None
        if with_readout:
            readout = ctk.CTkLabel(
                head, text="", font=ctk.CTkFont(size=11), text_color=TEXT_MUTED
            )
            readout.pack(side="right")

        slider = ctk.CTkSlider(
            row,
            from_=min_val,
            to=1.0,
            height=16,
            button_length=8,
            corner_radius=8,
            fg_color=SURFACE_HI,
            progress_color=ACCENT,
            button_color=TEXT,
            button_hover_color=ACCENT,
            command=lambda v: self._on_slider_change(),
        )
        slider.set(initial)
        slider.pack(fill="x", pady=(4, 0))

        return (slider, readout) if with_readout else slider

    def _redraw_ring(self):
        """Re-render the ring. Debounced by its caller, not cheap enough to
        run on every pixel of a slider drag."""
        image = ring.render(
            self.RING_SIZE,
            self.schedule,
            self.settings["intensity"],
            datetime.now().astimezone(),
            self.settings["auto"],
            self.settings["is_on"],
        )
        self._ring_image = ctk.CTkImage(
            light_image=image, dark_image=image,
            size=(self.RING_SIZE, self.RING_SIZE),
        )
        self.ring_label.configure(image=self._ring_image)

    def _queue_ring_redraw(self):
        if self._ring_job is not None:
            self.after_cancel(self._ring_job)
        self._ring_job = self.after(120, self._flush_ring)

    def _flush_ring(self):
        self._ring_job = None
        self._redraw_ring()

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
        # accent-coloured selection is unreadable on the dark unselected one. This is
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

        # One field taking a city name or a raw "lat, lon" pair. Two labelled
        # coordinate boxes assumed the user knows their own latitude, which
        # almost nobody does — it quietly made sunset mode unreachable for
        # anyone who wasn't going to go and look it up.
        self.coords_row = ctk.CTkFrame(box, fg_color="transparent")

        top = ctk.CTkFrame(self.coords_row, fg_color="transparent")
        top.pack(fill="x")
        ctk.CTkLabel(
            top, text="Where", font=ctk.CTkFont(size=11), text_color=TEXT_MUTED
        ).pack(side="left")

        self.place_entry = ctk.CTkEntry(
            top,
            height=28,
            corner_radius=8,
            font=ctk.CTkFont(size=12),
            fg_color=SURFACE_HI,
            border_width=0,
            text_color=TEXT,
            placeholder_text="your city",
        )
        self.place_entry.bind("<Return>", lambda _e: self._commit_place())
        self.place_entry.bind("<FocusOut>", lambda _e: self._commit_place())
        self.place_entry.bind("<KeyRelease>", lambda _e: self._suggest_places())
        self.place_entry.pack(side="left", fill="x", expand=True, padx=(8, 0))

        # Doubles as the suggestion line while typing and the confirmation
        # line once something is set, so the row never grows or jumps.
        self.place_note = ctk.CTkLabel(
            self.coords_row,
            text="",
            font=ctk.CTkFont(size=10),
            text_color=TEXT_MUTED,
            anchor="w",
        )
        self.place_note.pack(fill="x", pady=(4, 0))

        self._restore_place_field()
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

    def _restore_place_field(self):
        """Show whatever location is already saved, as a place not a number."""
        lat, lon = self.schedule.latitude, self.schedule.longitude
        self.place_entry.delete(0, "end")
        if lat is None or lon is None:
            self.place_note.configure(text="a city name, or \u201clat, lon\u201d")
            return
        label = cities.nearest_label(lat, lon)
        self.place_entry.insert(0, label)
        self.place_note.configure(text=f"{lat:.4f}, {lon:.4f}")

    def _suggest_places(self):
        """Offer matches as the user types, without committing anything."""
        typed = self.place_entry.get().strip()
        if not typed:
            self.place_note.configure(text="a city name, or \u201clat, lon\u201d")
            return
        matches = cities.search(typed, limit=3)
        if matches:
            self.place_note.configure(
                text="  \u00b7  ".join(f"{n}, {r}" for n, r, _, _ in matches)
            )
        elif "," in typed:
            self.place_note.configure(text="press return to use these coordinates")
        else:
            self.place_note.configure(text="no match \u2014 try a nearby larger city")

    def _commit_place(self):
        """Resolve the field to coordinates, or put back what was there.

        Empty means "not set": the schedule then reports itself unusable
        rather than guessing where anyone is.
        """
        typed = self.place_entry.get().strip()

        if not typed:
            self.schedule.latitude = None
            self.schedule.longitude = None
            self.place_note.configure(text="a city name, or \u201clat, lon\u201d")
        else:
            found = cities.resolve(typed)
            if found is None:
                # Restore rather than leave text sitting there looking accepted.
                self._restore_place_field()
                self.place_note.configure(text="no match \u2014 try a nearby larger city")
                return
            label, lat, lon = found
            self.schedule.latitude = lat
            self.schedule.longitude = lon
            self.place_entry.delete(0, "end")
            self.place_entry.insert(0, label)
            self.place_note.configure(text=f"{lat:.4f}, {lon:.4f}")

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
        """The on/off options that aren't about colour, in one card."""
        card = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=12)
        card.pack(fill="x", padx=22, pady=(0, 16))

        # Asked once at startup. A switch that can only ever refuse is worse
        # than no switch — it invites the user to keep trying something that
        # cannot work on their hardware. Where the backlight can't be driven,
        # the option simply isn't offered.
        self._backlight_controllable = self.gamma.can_control_backlight()

        # Sits above the individual switches because it drives them: it is
        # the whole promise in one flip, and the two rows under it are the
        # same thing taken apart for anyone who wants only half of it.
        self.zero_blue_switch, self.zero_blue_note = self._add_option_row(
            card,
            "Zero blue, zero flicker",
            self._toggle_zero_blue,
            first=True,
            description="Blue channel off entirely, backlight held steady",
        )

        if self._backlight_controllable:
            self.pwm_switch, self.pwm_note = self._add_option_row(
                card,
                "No-flicker dimming",
                self._toggle_pwm_safe,
                first=False,
                description="Holds the backlight steady and dims in software",
            )
            if self.settings["pwm_safe"]:
                self.pwm_switch.select()
        else:
            self.pwm_switch = None
            self.pwm_note = None
            # Can't be active if it can't be controlled — don't let a stale
            # saved value have the app believe otherwise.
            self.settings["pwm_safe"] = False

        if startup.is_supported():
            self.login_switch, self.login_note = self._add_option_row(
                card,
                "Launch at login",
                self._toggle_login,
                first=False,
            )
            # Read from the OS, never from saved settings — someone may have
            # removed the login item by hand since last run, and the switch
            # should show what's actually true.
            if startup.is_enabled():
                self.login_switch.select()
        else:
            self.login_switch = None
            self.login_note = None

    def _add_option_row(self, parent, label, command, first, description=None):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(12, 12) if first else (0, 12))

        top = ctk.CTkFrame(row, fg_color="transparent")
        top.pack(fill="x")

        switch = ctk.CTkSwitch(
            top,
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
            top, text="", font=ctk.CTkFont(size=10), text_color=TEXT_MUTED
        )
        note.pack(side="right")

        if description:
            # "PWM" is jargon. The switch says what it does; this says what
            # that means.
            ctk.CTkLabel(
                row,
                text=description,
                font=ctk.CTkFont(size=10),
                text_color=TEXT_MUTED,
                anchor="w",
            ).pack(fill="x", padx=(46, 0), pady=(2, 0))

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
            light_image=brand.eye_image(22, OFF_INK, OFF),
            dark_image=brand.eye_image(22, OFF_INK, OFF),
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

        # Not packed until something actually fails, so it costs no space in
        # the normal case — _fit_to_content() resizes the panel around it.
        self.gamma_warning = ctk.CTkLabel(
            self,
            text="Your system refused the colour change — see README",
            font=ctk.CTkFont(size=10),
            text_color=TEXT_MUTED,
            wraplength=PANEL_WIDTH - 60,
        )

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
            # Deliberately terse: the ring's centre already carries the full
            # sentence, and two copies of it a few centimetres apart read as
            # a bug rather than emphasis.
            text=("on" if self.schedule.is_usable() else "needs a place") if on else "off",
            text_color=ACCENT if on and self.schedule.fading() else TEXT_MUTED,
        )
        for entry in (
            self.start_entry,
            self.end_entry,
            self.place_entry,
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

        self._tick_job = self.after(TICK_MS, tick)

        def hold():
            self._hold_job = self.after(HOLD_MS, hold)
            self._hold_pwm_safe()

        self._hold_job = self.after(HOLD_MS, hold)

    def _stop_ticking(self):
        for attribute in ("_tick_job", "_hold_job"):
            job = getattr(self, attribute)
            if job is not None:
                self.after_cancel(job)
                setattr(self, attribute, None)

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
        if not self.settings["pwm_safe"] or self.pwm_switch is None:
            return
        if self.gamma.hold_pwm_safe():
            return

        self.settings["pwm_safe"] = False
        self.pwm_switch.deselect()
        self.pwm_note.configure(text="lost control of backlight")
        if self.settings["zero_blue"]:
            self.zero_blue_note.configure(text=self._zero_blue_note(False))
        self._queue_save()

    # -- zero blue -------------------------------------------------------
    # One switch for the two halves of "nothing on this screen is hurting
    # my eyes": no blue in the ramp, and a backlight that isn't strobing
    # while it dims. They're separate mechanisms with separate failure
    # modes, so the note under the switch says which half is actually in
    # force rather than implying both always are.

    def _enable_pwm_for_zero_blue(self) -> bool:
        """Turn the backlight lock on as part of the mode. Returns whether
        the lock is in force, which is not the same as whether we asked."""
        if self.pwm_switch is None:
            return False
        if self.settings["pwm_safe"]:
            return True
        self.pwm_switch.select()
        self._toggle_pwm_safe()  # deselects itself again if it can't hold
        return self.settings["pwm_safe"]

    def _zero_blue_note(self, holding: bool) -> str:
        """Say which half of the promise is real on this machine.

        A laptop whose backlight we can't drive still gets the colour half,
        and that's worth having — but claiming "no flicker" there would be
        the exact lie the probe in gamma.py exists to prevent.
        """
        if holding:
            return "no blue, backlight steady"
        if self.pwm_switch is None:
            return "no blue — backlight isn't ours to hold"
        return "no blue — can't hold this backlight"

    def _toggle_zero_blue(self):
        turning_on = self.zero_blue_switch.get() == 1

        if turning_on:
            self.settings["before_zero_blue"] = {
                "intensity": self.settings["intensity"],
                "pwm_safe": self.settings["pwm_safe"],
            }
            self.settings["zero_blue"] = True
            holding = self._enable_pwm_for_zero_blue()
            self.zero_blue_note.configure(text=self._zero_blue_note(holding))
            # The ramp ignores the slider in this mode; move it so the panel
            # doesn't sit there showing a warmth the screen isn't at.
            self.warmth_slider.set(1.0)
            self.settings["intensity"] = 1.0
        else:
            self.settings["zero_blue"] = False
            self.zero_blue_note.configure(text="")
            before = self.settings["before_zero_blue"] or {}
            # Only undo the lock if the mode is what turned it on — someone
            # who had no-flicker dimming on beforehand keeps it.
            if (
                self.pwm_switch is not None
                and self.settings["pwm_safe"]
                and not before.get("pwm_safe")
            ):
                self.pwm_switch.deselect()
                self._toggle_pwm_safe()
            if before.get("intensity") is not None:
                self.settings["intensity"] = before["intensity"]
                self.warmth_slider.set(before["intensity"])
            self.settings["before_zero_blue"] = None

        self._sync_zero_blue_controls()
        self._cancel_animation()
        self._apply_current()
        self._queue_save()

    def _sync_zero_blue_controls(self):
        """Grey out the controls the mode has taken over.

        Leaving them live would let a preset quietly set a temperature that
        the ramp then overrides — the click would look like it worked and
        change nothing on screen.
        """
        state = "disabled" if self.settings["zero_blue"] else "normal"
        self.warmth_slider.configure(state=state)
        for button in self.preset_buttons.values():
            button.configure(state=state)

    def _remember_backlight(self):
        """Write the displaced level straight to disk, not via _queue_save().

        The debounce is 400ms, which is 400ms in which a kill loses the one
        value needed to undo the lock. This is the single write in the app
        worth doing synchronously.
        """
        self.settings["backlight_before_lock"] = self.gamma._saved_hw_brightness
        save_settings(self.settings)

    def _repair_backlight_after_crash(self):
        """Undo a lock left behind by a previous run that was killed.

        SIGKILL is uncatchable, so no exit hook can help: Force Quit, or
        `osascript -e 'quit app "EyeEase"'` on this app (it isn't scriptable,
        so the quit escalates to a kill), and the backlight simply stays
        pinned at 100% forever. The next launch is the only place left to
        fix it.

        Only acts if the backlight is still sitting where the lock left it.
        Someone who has already turned their brightness back down since then
        has said what they want more recently than this file has, and yanking
        them to a stale level would be its own bug.
        """
        saved = self.settings.get("backlight_before_lock")
        if saved is None:
            return

        current = self.gamma._get_hw_brightness()
        if current is not None and current >= 0.98:
            self.gamma._set_hw_brightness(saved)

        self.settings["backlight_before_lock"] = None
        save_settings(self.settings)

    def _toggle_pwm_safe(self):
        turning_on = self.pwm_switch.get() == 1
        if turning_on:
            if not self.gamma.enable_pwm_safe():
                # Couldn't reach the backlight (unsupported hardware, no
                # permission, etc.) — leave the switch off instead of
                # claiming a mode that isn't actually active.
                self.pwm_switch.deselect()
                self.pwm_note.configure(text="can't hold this backlight")
                turning_on = False
            else:
                self.pwm_note.configure(text="backlight held steady")
                self._remember_backlight()
        else:
            self.gamma.disable_pwm_safe()
            self._remember_backlight()
            self.pwm_note.configure(text="")
        self.settings["pwm_safe"] = turning_on
        if self.settings["zero_blue"]:
            # Turning the backlight row off by hand halves the mode above
            # it. Say so there too, or that switch keeps promising no
            # flicker while the backlight has gone back to dimming itself.
            self.zero_blue_note.configure(text=self._zero_blue_note(turning_on))
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

            self.gamma.apply(
                intensity_to_kelvin(cur_i), cur_b, self.settings["zero_blue"]
            )

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
        if self.settings["zero_blue"]:
            # A Kelvin number would undersell it: 1200K is a temperature the
            # slider can reach on its own, and the point of the mode is the
            # channel that is gone rather than the one it sits nearest.
            self.warmth_readout.configure(
                text="NO BLUE", text_color=kelvin_to_hex(KELVIN_MIN, zero_blue=True)
            )
            self.brightness_readout.configure(
                text=f"{int(round(brightness * 100))}%"
            )
            self._update_ring_status()
            self._queue_ring_redraw()
            self._update_preset_highlight(kelvin, brightness)
            return

        self.warmth_readout.configure(
            text=f"{int(round(kelvin / 50) * 50)}K",
            # The number is drawn in the tint it describes, which is the whole
            # preview: no separate swatch, no label, nothing extra on screen.
            # Tint only, never the dimming — a readout that fades toward black
            # at low brightness would be unreadable rather than informative.
            text_color=kelvin_to_hex(kelvin),
        )
        self.brightness_readout.configure(text=f"{int(round(brightness * 100))}%")

        self._update_ring_status()
        self._queue_ring_redraw()
        self._update_preset_highlight(kelvin, brightness)

    def _update_ring_status(self):
        """The line under the ring's reading.

        With auto on this is the schedule talking; with it off the ring is a
        flat band and saying anything about sunset would be describing a
        curve that isn't being followed.
        """
        if not self.settings["is_on"]:
            self.ring_status.configure(text="off")
        elif self.settings["auto"] and self.schedule.is_usable():
            self.ring_status.configure(text=self.schedule.status_line())
        else:
            self.ring_status.configure(text="manual")

    def _update_preset_highlight(self, kelvin, brightness):
        """Light up whichever preset the current values correspond to, so the
        row reads as state and not just as three buttons."""
        for name, button in self.preset_buttons.items():
            preset = PRESETS[name]
            active = (
                not self.settings["zero_blue"]
                and abs(kelvin - preset["kelvin"]) < 60
                and abs(brightness - preset["brightness"]) < 0.02
                and self.settings["is_on"]
            )
            button.configure(
                fg_color=ACCENT_DIM if active else SURFACE,
                text_color=TEXT if active else TEXT_MUTED,
            )

    def attach_tray(self, icon):
        """Called by tray.py once the menu-bar item exists."""
        self._tray_icon = icon
        self._update_tray_icon()

    def _update_tray_icon(self):
        if self._tray_icon is None:
            return
        try:
            self._tray_icon.icon = tray.make_icon_image(self.settings["is_on"])
            tray.force_redraw(self._tray_icon)
        except Exception:
            # A menu-bar icon that won't re-draw is not a reason to take the
            # app down with it — the panel is still the real control.
            pass

    def _update_power_state(self):
        on = self.settings["is_on"]
        self.power_button.configure(
            text="EASE ON" if on else "EASE OFF",
            image=self.eye_mark_on if on else self.eye_mark_off,
            fg_color=ACCENT if on else OFF,
            text_color=INK if on else OFF_INK,
            hover_color=ACCENT_HOVER if on else OFF_HOVER,
        )
        self.status_dot.configure(text_color=ACCENT if on else ACCENT_DIM)
        self._update_tray_icon()

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
            applied = self.gamma.apply(
                intensity_to_kelvin(intensity), brightness, self.settings["zero_blue"]
            )
        else:
            applied = self.gamma.reset()
        self._show_gamma_warning(not applied)
        self._refresh_readouts()
        self._queue_save()

    def _show_gamma_warning(self, failed):
        """Say so when the OS refuses the colour change.

        Windows sanity-checks gamma ramps and rejects ones too far from
        linear, which is precisely the shape the warmest settings produce.
        Without this the sliders would move, the readout would update, and
        the screen would stay stubbornly unchanged with nothing explaining
        why.
        """
        if failed == self._gamma_failed:
            return
        self._gamma_failed = failed

        if failed:
            self.gamma_warning.pack(fill="x", padx=22, pady=(0, 16))
        else:
            self.gamma_warning.pack_forget()
        self._fit_to_content()

    def restore_display(self):
        """Give the screen back. Touches no Tk, and is safe to call twice.

        The colour half looks after itself: macOS resets the gamma table when
        the process that set it dies, so a crash or a kill -9 leaves the
        screen untinted on its own.

        The backlight does not. It's a persistent system setting, and nothing
        puts it back — measured on a build, quitting by Apple Event (which is
        also what a logout or a Force Quit does) left the panel pinned at
        100% with the saved 45% never restored. Someone who turned this mode
        on because bright, flickering screens hurt should not log back in to
        a display at full blast.

        Deliberately Tk-free: this runs from atexit and from a signal
        handler, both of which can fire after the window is destroyed.
        """
        try:
            self.gamma.disable_pwm_safe()  # no-ops when the lock isn't held
            self.gamma.reset()
        except Exception:
            # Nothing useful to do while the process is on its way out, and
            # raising here would replace a clean exit with a traceback.
            pass

    def on_close(self):
        """Call this before quitting so the screen doesn't stay tinted."""
        self._cancel_animation()
        self._stop_ticking()
        if self._ring_job is not None:
            self.after_cancel(self._ring_job)
            self._ring_job = None
        if self._save_job is not None:
            self.after_cancel(self._save_job)
            self._save_job = None
        self.restore_display()
        self.settings["backlight_before_lock"] = None
        save_settings(self.settings)
        self.destroy()
