from PIL import Image
import dearpygui.dearpygui as dpg
import threading
import subprocess

import time
import random
import jack
from scipy._external.array_api_extra import default_dtype

import eq_apo_parser
import jack_client
import numpy as np
import pyloudnorm as pyln
from peq_config import PEQConfig
import pipewire_utils
import copy
import os
import pystray
from dataclasses import dataclass, field
import crossfiledialog

from utils import SingletonMeta, db_to_lin, generate_tilted_noise, connect_program_nodes_to_patchbay

print(os.getpid())

@dataclass
class GUIState(metaclass=SingletonMeta):
    audio_bypass: bool = False
    preset_btns: list[int | str] = field(default_factory=list)
    active_preset_button: str | int | None = None
    tabs: list[str] = field(default_factory=lambda:["presets", "control"])
    kill_dpg_event: threading.Event = threading.Event()
    presets: list[PEQConfig] = field(default_factory=list)
    next_free_preset_id: int = 0    # TODO

    def add_preset(self, preset: PEQConfig):
        # TODO
        idx = self.next_free_preset_id
        with dpg.table_row(tag=f"presets_table_row_{idx}", parent="presets_table"):
            btn = dpg.add_button(
                label=preset.name, user_data=preset.name,
                callback=preset_btn_callback,
                width=-1, height=100,
                tag=f"preset_btn_{idx}",
            )

            dpg.add_button(label="", width=100, height=100, user_data=idx)
            dpg.add_button(label="󰆴", width=100, height=100, user_data=idx, callback=delete_preset_btn_callback)

        self.presets.append(preset)
        self.preset_btns.append(btn)
        self.next_free_preset_id += 1

        with jack_client.settings.lock:
            jack_client.settings.eq_presets.append(preset)

    def delete_preset_by_name(self, preset_id: int):
        dpg.delete_item(f"presets_table_row_{preset_id}")
        for idx, preset_btn in enumerate(self.preset_btns):
            if preset_btn == f"preset_btn_{preset_id}":
                return (
                    idx,
                    self.presets.pop(idx),
                    self.preset_btns.pop(idx),
                )


gui_state = GUIState()


#
# First of all define eq presets as many as you want. The parameters are: path
# or text of config; sample rate is unimportand because it will be changed
# after jack client thread is started; and preset name that can be
# automatically generated from path's name without extension. Then add them
# manually to `ps`. First preset in `ps` will be set as default preset when
# starting the app.
#

p1 = eq_apo_parser.parse_eq_apo_config("/home/paro/Downloads/JT1/PEQdB Diamond Beta for KB501X.txt", 48000, "Diamond")
p2 = eq_apo_parser.parse_eq_apo_config("/home/paro/Downloads/JT1/PEQdB Pref norm 02.10.2026.txt", 48000, "Pref norm")
p3 = eq_apo_parser.parse_eq_apo_config("/home/paro/Downloads/JT1/PEQdB pref 10.10.2026.txt", 48000, "pref today")
p4 = eq_apo_parser.parse_eq_apo_config("/home/paro/Downloads/JT1/PEQdB pref 2 10.10.2026.txt", 48000, "pref today 2")
p5 = eq_apo_parser.parse_eq_apo_config("/home/paro/Downloads/JT1/avg peq pref 10.10.2026.txt", 48000, "avg pref")
p6 = eq_apo_parser.parse_eq_apo_config("", 48000, "original")

gui_state.presets = [p1, p2, p3, p4, p5, p6]

# p1 = eq_apo_parser.parse_eq_apo_config("/home/paro/Downloads/Space Travel 2/peqdb diamond.txt", 48000, "Diamond")
# p2 = eq_apo_parser.parse_eq_apo_config("/home/paro/Downloads/Space Travel 2/delta harman moa 2025.txt", 48000, "moa 2025")
# p3 = eq_apo_parser.parse_eq_apo_config("/home/paro/Downloads/Space Travel 2/harman ie 2019.txt", 48000, "harman ie 2019")
# p4 = eq_apo_parser.parse_eq_apo_config("/home/paro/Downloads/Space Travel 2/ief preference 2025.txt", 48000, "ief")
# p5 = eq_apo_parser.parse_eq_apo_config("/home/paro/Downloads/Space Travel 2/JM-1 -10dB tilt.txt", 48000, "JM-1 tilt")
# p6 = eq_apo_parser.parse_eq_apo_config("/home/paro/Downloads/Space Travel 2/JM-1 + Bass.txt", 48000, "JM-1 + Bass")
# p7 = eq_apo_parser.parse_eq_apo_config("", 48000, "original")
#
# ps = [p1, p2, p3, p4, p5, p6, p7]

# p1 = eq_apo_parser.parse_eq_apo_config("/home/paro/Downloads/final-audio-e500/h-ie-2019-precise.txt", 48000, "H IE 2019 precise")
# p2 = eq_apo_parser.parse_eq_apo_config("/home/paro/Downloads/final-audio-e500/peqdb-diamond-kinda-precise.txt", 48000, "diamond kinda precise")
# p3 = eq_apo_parser.parse_eq_apo_config("/home/paro/Downloads/final-audio-e500/JM-1.txt", 48000, "JM-1")
# p4 = eq_apo_parser.parse_eq_apo_config("/home/paro/Downloads/final-audio-e500/JM-1 -10db tilt.txt", 48000, "JM-1 -10db tilt")
# p5 = eq_apo_parser.parse_eq_apo_config("/home/paro/Downloads/final-audio-e500/JM-1 with bass.txt", 48000, "JM-1 with bass")
# p6 = eq_apo_parser.parse_eq_apo_config("", 48000, "original")
#
# ps = [p1, p2, p3, p4, p5]

# Start the jack thread
jack_client.settings.bypass = True
t = threading.Thread(target=jack_client.start_jack)
t.start()

# Change sample rate of presets to jack client's sample rate.
jack_client.client_started_event.wait()
sr = jack_client.client.samplerate
for p in gui_state.presets:
    p.change_sample_rate(sr)

with jack_client.settings.lock:
    jack_client.settings.current_eq_preset = copy.deepcopy(gui_state.presets[0])
    jack_client.settings.eq_presets = copy.deepcopy(gui_state.presets)
    jack_client.settings.bypass = False


NODE_AUTO_CONNECT = True
if NODE_AUTO_CONNECT:
    old_default_sink, new_default_sink = \
        connect_program_nodes_to_patchbay(jack_client)


def preset_btn_callback(sender, app_data, user_data):
    global gui_state

    if gui_state.active_preset_button is not None:
        dpg.bind_item_theme(gui_state.active_preset_button, 0)

    dpg.bind_item_theme(sender, "preset_btn_theme")
    gui_state.active_preset_button = sender

    with jack_client.settings.lock:
        jack_client.settings.current_eq_preset = copy.deepcopy(
            next(filter(lambda p: p.name == user_data, gui_state.presets))
        )

def bypass_btn_callback(sender, app_data, user_data):
    global gui_state
    gui_state.audio_bypass ^= True

    with jack_client.settings.lock:
        jack_client.settings.bypass = gui_state.audio_bypass

    if gui_state.audio_bypass:
        dpg.configure_item("bypass_btn", label="Bypass: ON")
    else:
        dpg.configure_item("bypass_btn", label="Bypass: OFF")

def ch_swap_btn_callback(sender, app_data, user_data):
    new_state = not user_data
    dpg.set_item_user_data(sender, new_state)
    if new_state:
        dpg.configure_item(sender, label="Channel Swap: ON")
    else:
        dpg.configure_item(sender, label="Channel Swap: OFF")

    with jack_client.settings.lock:
        jack_client.settings.swap_channels = new_state

def normalize_presets_btn_callback(sender, app_data, user_data):
    #
    # Now is the presets loudness matching. It is simplified/generalized version.
    # It just compares loudness of the same noise but with different presets
    # applied. After it preamp gains are lessened to match the quitest one. It's
    # chosen because as by now program only works as equalizer that captures
    # samples from the inports of the node, applies dsp to them and outputs them to
    # the outports of the node. Noise is specified by it's tilt in dB/octave. -3 is
    # pink noise, -4.5 is chosen as default because many popular music has tilt
    # spectal tilt of -4.5 dB/octave. One can also experiment with filter class of
    # `meter`: "K-weighting", "Fenton/Lee 1", etc.
    #
    noise_tilt = -4.5
    fs = gui_state.presets[0].fs
    reference_signal = generate_tilted_noise(fs * 60, noise_tilt, fs)
    meter = pyln.Meter(48000, "Fenton/Lee 2")
    ps_loudnesses = []
    for idx, p in enumerate(gui_state.presets):
        dpg.configure_item(
            "normalize_presets_prog_bar", default_value=idx/len(gui_state.presets),
            overlay=f"{idx}/{len(gui_state.presets)}"
        )
        loudness = meter.integrated_loudness(p.apply_temp(reference_signal))
        print(f"{p.name}: {loudness:.1f} LUFS")
        ps_loudnesses.append(loudness)

    dpg.configure_item(
        "normalize_presets_prog_bar", default_value=1.0,
        overlay="Presets Normalized!"
    )

    min_loudness = min(ps_loudnesses)
    for p, l in zip(gui_state.presets, ps_loudnesses):
        p.preamp_gain += min_loudness - l

    with jack_client.settings.lock:
        jack_client.settings.eq_presets = copy.deepcopy(gui_state.presets)
        jack_client.settings.current_eq_preset = copy.deepcopy(
            next(filter(lambda p: p.name == jack_client.settings.current_eq_preset.name, gui_state.presets))
        )

def global_gain_slider_callback(sender, app_data, user_data):
    with jack_client.settings.lock:
        k1, k2, k3 = user_data
        x = app_data
        q = x*k1
        v = q*(1/(k2*(x + k3)) + 1)

        if app_data == -1:
            v = -float("inf")
            dpg.configure_item(sender, format=f"-inf dBFS")
        else:
            dpg.configure_item(sender, format=f"{v:.1f} dBFS")

        jack_client.settings.post_gain_lin = db_to_lin(v)



def change_tab_callback(sender, app_data, user_data):
    global gui_state

    for tab in gui_state.tabs:
        tab_btn_dpg_name = f"{tab}_tab_btn"
        tab_dpg_name = f"{tab}_tab"
        show = True if sender == tab_btn_dpg_name else False
        dpg.configure_item(tab_dpg_name, show=show)


def add_preset_btn_callback(sender, app_data, user_data):
    global gui_state
    filename = crossfiledialog.open_file(title="Choose file with APO preset")
    preset = eq_apo_parser.parse_eq_apo_config(filename, jack_client.client.samplerate)
    gui_state.add_preset(preset)


def delete_preset_btn_callback(sender, app_data, user_data):
    global gui_state

    #TODO
    if len(gui_state.preset_btns) == 1:
        return

    id = user_data
    idx, _, popped_btn = gui_state.delete_preset_by_name(id)
    if gui_state.active_preset_button == popped_btn:
        gui_state.active_preset_button = None
        new_idx = idx if idx < len(gui_state.preset_btns) else idx - 1
        preset_btn_callback(
            gui_state.preset_btns[new_idx], None,
            gui_state.presets[new_idx].name
        )

    with jack_client.settings.lock:
        jack_client.settings.eq_presets.pop(idx)


def start_dpg():
    global gui_state

    gui_state.preset_btns.clear()
    gui_state.kill_dpg_event.clear()

    dpg.create_context()

    with dpg.theme(tag="preset_btn_theme"):
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_color(dpg.mvThemeCol_Button, (0, 128, 128, 255))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (0, 160, 160, 255))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (0, 100, 100, 255))

    with dpg.font_registry():
        with dpg.font("/usr/share/fonts/TTF/BlexMonoNerdFont-Regular.ttf", 20) as nerd_font:
            dpg.bind_font(nerd_font)

    with dpg.theme() as global_theme:
        # This targets the background container size of the menu bar
        with dpg.theme_component(dpg.mvChildWindow):
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 0, 0)

    dpg.bind_theme(global_theme)
    with dpg.window(tag="Primary Window"):
        with dpg.child_window(no_scrollbar=True, no_scroll_with_mouse=True, height=25, border=False):
            with dpg.tab_bar():
                dpg.add_tab_button(label="Presets", callback=change_tab_callback, tag="presets_tab_btn")
                dpg.add_tab_button(label="Control", callback=change_tab_callback, tag="control_tab_btn")

        with dpg.child_window(border=False, no_scrollbar=True):
            with dpg.group(tag="presets_tab"):
                with dpg.table(
                    header_row=False, resizable=False, hideable=False,
                    reorderable=False, borders_innerH=False,
                    borders_innerV=False, borders_outerH=False,
                    borders_outerV=False, row_background=False,
                    policy=dpg.mvTable_SizingStretchProp,
                    tag="presets_table"
                ):
                    dpg.add_table_column(label="preset_name")
                    dpg.add_table_column(label="edit_btn", width_fixed=True, init_width_or_weight=100)
                    dpg.add_table_column(label="delete_btn", width_fixed=True, init_width_or_weight=100)

                    for idx, p in enumerate(gui_state.presets):
                        with dpg.table_row(tag=f"presets_table_row_{idx}"):
                            btn = dpg.add_button(
                                label=p.name, user_data=p.name,
                                callback=preset_btn_callback,
                                width=-1, height=100,
                                tag=f"preset_btn_{idx}",
                            )

                            dpg.add_button(label="", width=100, height=100, user_data=idx)
                            dpg.add_button(label="󰆴", width=100, height=100, user_data=idx, callback=delete_preset_btn_callback)

                        gui_state.preset_btns.append(f"preset_btn_{idx}")
                        gui_state.next_free_preset_id += 1

                dpg.add_button(
                    label="+", tag="add_preset_btn",
                    callback=add_preset_btn_callback,
                    width=-1, height=100
                )

                if gui_state.active_preset_button is None:
                    gui_state.active_preset_button = gui_state.preset_btns[0]
                dpg.bind_item_theme(gui_state.active_preset_button, "preset_btn_theme")

                with dpg.group(horizontal=True):
                    dpg.add_button(
                        label="Normalize presets",
                        callback=normalize_presets_btn_callback
                    )
                    dpg.add_progress_bar(
                        default_value=0.0, width=-1,
                        tag="normalize_presets_prog_bar"
                    )

            with dpg.group(tag="control_tab"):
                with dpg.group(horizontal=True):
                    dpg.add_button(
                        label="Bypass: OFF", user_data=False,
                        tag="bypass_btn", callback=bypass_btn_callback
                    )
                    dpg.add_button(
                        label="Channel Swap: OFF", user_data=False,
                        tag="ch_swap_btn", callback=ch_swap_btn_callback
                    )
                dpg.add_slider_float(
                    label="Global Gain",
                    min_value=-1, max_value=0,
                    tag="global_gain_slider", format="0.0 dBFS",
                    callback=global_gain_slider_callback,
                    user_data=(60, 50, 1.01)
                )


    def mouse_wheel_callback(sender, app_data):
        if dpg.is_item_hovered("global_gain_slider"):
            current_val = dpg.get_value("global_gain_slider")
            # app_data is positive for scrolling up, negative for scrolling down
            if (
                dpg.is_key_down(dpg.mvKey_LControl)
                or dpg.is_key_down(dpg.mvKey_RControl)
            ):
                step = 0.1
            elif (
                dpg.is_key_down(dpg.mvKey_LShift)
                or dpg.is_key_down(dpg.mvKey_RShift)
            ):
                step = 5
            else:
                step = 1

            k1, k2, k3 = dpg.get_item_user_data("global_gain_slider")
            x = current_val
            q = x*k1
            v = q*(1/(k2*(x + k3)) + 1)

            y = v + (app_data * step)

            a = k2*k1
            b = k1*k2*k3 + k1 - k2*y
            c = -k2*k3*y

            new_val = (-b + (b**2 - 4*a*c)**0.5) / (2*a)

            # Clamp values within bounds (optional, e.g., 0 to 100)
            new_val = max(-1, min(0, new_val))

            dpg.set_value("global_gain_slider", new_val)
            global_gain_slider_callback("global_gain_slider", new_val, (k1, k2, k3))

    change_tab_callback("presets_tab_btn", None, None)


    # with dpg.item_handler_registry() as handler_registry:
    #     dpg.add_item_hover_handler(callback=power_button_on_hover)
    #
    with dpg.handler_registry():
        dpg.add_mouse_wheel_handler(callback=mouse_wheel_callback)

    # dpg.bind_item_handler_registry(power_btn, handler_registry)

    dpg.create_viewport(title='EQ Juggler', width=800, height=600,)
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.set_primary_window("Primary Window", True)

    while dpg.is_dearpygui_running():
        if gui_state.kill_dpg_event.is_set():
            break

        # If the button is no longer hovered, reset the color to white.
        # This acts as the "on_leave" fallback because Dear PyGui lacks a native leave handler.
        # if not dpg.is_item_hovered(power_btn):
        #     if is_bypass:
        #         dpg.configure_item("power_btn_text_color_prop", value=(255, 0, 0, 255))
        #     else:
        #         dpg.configure_item("power_btn_text_color_prop", value=(0, 255, 0, 255))

        dpg.render_dearpygui_frame()

    dpg.destroy_context()


dpg_thread = threading.Thread(target=start_dpg)
dpg_thread.start()


def show_app_action(icon, item):
    global dpg_thread
    if not dpg_thread.is_alive():
        dpg_thread = threading.Thread(target=start_dpg)
        dpg_thread.start()


def quit_app_action(icon, item):
    global gui_state
    gui_state.kill_dpg_event.set()
    icon.stop()

def presets_tray_action(icon, item):
    global gui_state, dpg_thread
    if dpg_thread.is_alive():
        preset_btn_callback(
            next(filter(lambda b: dpg.get_item_user_data(b) == item.text, gui_state.preset_btns)),
            None, item.text
        )
    else:
        print(NotImplementedError(
            "Preset is changed on Jack client level, but selected radio "
            "button didn't changed in DearPyGui"
        ))
        with jack_client.settings.lock:
            jack_client.settings.current_eq_preset = copy.deepcopy(
                next(filter(lambda p: p.name == item.text, gui_state.presets))
            )


tray_icon = Image.open("./tray-icon.png") \
    .resize((64, 64), Image.Resampling.LANCZOS)

presets_submenu = pystray.Menu(
    *(pystray.MenuItem(p.name, presets_tray_action) for p in gui_state.presets)
)

menu = pystray.Menu(
    pystray.MenuItem("Show EQ Juggler", show_app_action),
    pystray.MenuItem("▸ Presets", presets_submenu),
    pystray.MenuItem("Quit EQ Juggler", quit_app_action)
)
icon = pystray.Icon("EQ Juggler", tray_icon, "EQ Juggler", menu)
icon.run()

jack_client.kill_jack_event.set()
t.join()

if NODE_AUTO_CONNECT:
    pipewire_utils.destroy_node(new_default_sink.id)
    pipewire_utils.wireplumber_set_default(old_default_sink.id)
