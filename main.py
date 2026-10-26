from ast import Assert
from PIL import Image
import dearpygui.dearpygui as dpg
import threading
import subprocess

import time
import random
import jack
from numpy.__config__ import show
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
import pathlib
import shutil

from utils import SingletonMeta, db_to_lin, generate_tilted_noise, connect_program_nodes_to_patchbay, remove_forbidden_path_chars

print(os.getpid())

PRESETS_COMBO_SPECIAL_ITEMS = ("[No Preset]", "+ New", "+ From File")

DEVICES_COMBO_SPECIAL_ITEMS = ("[No Device]", "+ New")

app_path = pathlib.Path("~/.local/share/eq-juggler").expanduser()
if not app_path.exists():
    app_path.mkdir()

@dataclass
class Device:
    name: str
    presets: dict[str, PEQConfig] = field(default_factory=dict)
    create_folder: bool = True

    def __post_init__(self):
        assert self.name != ""

        self.name = remove_forbidden_path_chars(self.name)
        self.path = app_path / "devices" / self.name

        if self.create_folder:
            self.path.mkdir()

    def add_preset(self, preset: PEQConfig):
        preset.name = remove_forbidden_path_chars(preset.name)

        assert preset.name != ""
        assert preset.name not in self.presets

        self.presets[preset.name] = preset

        with open(self.path / f"{preset.name}.txt", "w") as f:
            f.write(preset.to_eq_apo())

    def delete_preset(self, preset: PEQConfig):
        del self.presets[preset.name]

        (self.path / f"{preset.name}.txt").unlink()

    def delete_from_storage(self):
        shutil.rmtree(self.path)

    def update_preset(self, preset):
        assert preset.name in self.presets
        self.presets[preset.name] = preset

        with open(self.path / f"{preset.name}.txt", "w") as f:
            f.write(preset.to_eq_apo())

    def update_preset_name(self, old_name, new_name):
        assert old_name in self.presets

        new_name = remove_forbidden_path_chars(new_name)
        self.presets[new_name] = self.presets.pop(old_name)
        self.presets[new_name].name = new_name

        (self.path / f"{old_name}.txt").move(self.path / f"{new_name}.txt")

    def update_device_name(self, new_name):
        new_name = remove_forbidden_path_chars(new_name)

        new_path = app_path / "devices" / new_name
        self.path.move(new_path)

        self.name = new_name
        self.path = new_path



@dataclass
class GUIState(metaclass=SingletonMeta):
    audio_bypass: bool = False
    preset_btns: list[int | str] = field(default_factory=list)
    active_preset_button: str | int | None = None
    tabs: list[str] = field(default_factory=lambda:["presets", "control"])
    kill_dpg_event: threading.Event = threading.Event()
    presets: list[PEQConfig] = field(default_factory=list)
    next_free_preset_id: int = 0    # TODO
    devices: dict[str, Device] = field(default_factory=dict)
    current_device: Device | None = None
    _current_preset: PEQConfig | None = None

    @property
    def current_preset(self):
        return self._current_preset

    @current_preset.setter
    def current_preset(self, new_preset: PEQConfig | None):
        if new_preset is not None:
            new_preset.reset_zi()
        self._current_preset = new_preset
        with jack_client.settings.lock:
            jack_client.settings.current_eq_preset = copy.deepcopy(new_preset)


gui_state = GUIState()

devices_path = app_path / "devices"
if not devices_path.exists():
    devices_path.mkdir()

for device_entry in devices_path.iterdir():
    if device_entry.is_dir():
        device = Device(device_entry.name, create_folder=False)
        gui_state.devices[device.name] = device
        for preset_entry in device_entry.iterdir():
            if preset_entry.is_file():
                preset = eq_apo_parser.parse_eq_apo_config(preset_entry, 48000)
                device.presets[preset.name] = preset


# Start the jack thread
jack_client.settings.bypass = True
t = threading.Thread(target=jack_client.start_jack)
t.start()

# Change sample rate of presets to jack client's sample rate.
jack_client.client_started_event.wait()
sr = jack_client.client.samplerate
for d in gui_state.devices:
    for p in gui_state.presets:
        p.change_sample_rate(sr)

with jack_client.settings.lock:
    jack_client.settings.current_eq_preset = None
    jack_client.settings.bypass = False


NODE_AUTO_CONNECT = True
if NODE_AUTO_CONNECT:
    old_default_sink, new_default_sink = \
        connect_program_nodes_to_patchbay(jack_client)


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


def devices_combo_callback(sender, app_data, user_data):
    global gui_state

    if app_data == "+ New":
        i = 1
        while True:
            try:
                device = Device(f"Device #{i}")
                gui_state.devices[device.name] = device
                gui_state.current_device = device
                break
            except FileExistsError:
                i += 1

        device_items: list = dpg.get_item_configuration("devices_combo")["items"]
        device_items.insert(len(DEVICES_COMBO_SPECIAL_ITEMS), device.name)
        dpg.configure_item(
            "devices_combo", items=device_items,
            default_value=device.name,
        )
        dpg.set_value("device_name_input", device.name)
        dpg.set_value("preset_name_input", "")

        dpg.configure_item("control_panels_group", show=False)
        dpg.configure_item("device_preset_name_inputs_group", show=True)
        dpg.configure_item("preset_name_table_row", show=False)
        dpg.configure_item("no_device_seleted_group", show=False)
        dpg.configure_item("presets_combo_group", show=True)

        presets_combo_callback(
            "presets_combo", "[No Preset]",
            dpg.get_item_user_data("presets_combo")
        )

        return

    if app_data == "[No Device]":
        gui_state.current_device = None
        dpg.configure_item(
            "presets_combo",
            items=PRESETS_COMBO_SPECIAL_ITEMS,
            default_value=PRESETS_COMBO_SPECIAL_ITEMS[0],
        )
        dpg.set_value("device_name_input", "")
        dpg.set_value("preset_name_input", "")

        dpg.configure_item("control_panels_group", show=False)
        dpg.configure_item("device_preset_name_inputs_group", show=False)
        dpg.configure_item("no_device_seleted_group", show=True)
        dpg.configure_item("presets_combo_group", show=False)
        return

    gui_state.current_device = gui_state.devices[app_data]

    preset_items = [name for name in gui_state.current_device.presets]
    preset_items.extend(PRESETS_COMBO_SPECIAL_ITEMS)

    default_value = preset_items[0]
    dpg.configure_item("presets_combo", items=preset_items, default_value=default_value)
    dpg.set_value("device_name_input", gui_state.current_device.name)

    presets_combo_callback(
        "presets_combo", default_value,
        dpg.get_item_user_data("presets_combo")
    )


def presets_combo_callback(sender, app_data, user_data):
    global gui_state

    dpg.set_item_user_data(sender, app_data)
    assert gui_state.current_device is not None

    if app_data == "[No Preset]":
        gui_state.current_preset = None
        dpg.configure_item("no_device_seleted_group", show=False)
        dpg.configure_item("device_preset_name_inputs_group", show=True)
        dpg.configure_item("presets_combo_group", show=True)
        dpg.configure_item("control_panels_group", show=False)
        dpg.configure_item("preset_name_table_row", show=False)
        return

    default_value = app_data
    if app_data == "+ From File":
        path = crossfiledialog.open_file(title="Choose file with APO preset")
        if path == "":
            dpg.configure_item(sender, default_value=user_data)
            return

        try:
            config = eq_apo_parser.parse_eq_apo_config(path, 48000)    # TODO fs
        except SyntaxError:
            dpg.configure_item(sender, default_value=user_data)
            dpg.configure_item("eq_apo_parse_error_popup", show=True)
            return

        try:
            gui_state.current_device.add_preset(config)
        except AssertionError:
            pass
    elif app_data == "+ New":
        i = 1
        while True:
            config = PEQConfig(f"Preset #{i}", 0, [], 48000)    # TODO fs
            try:
                gui_state.current_device.add_preset(config)
                break
            except AssertionError:
                i += 1

    if app_data in {"+ From File", "+ New"}:
        preset_items = [name for name in gui_state.current_device.presets]
        preset_items.extend(PRESETS_COMBO_SPECIAL_ITEMS)
        default_value = config.name
        dpg.configure_item("presets_combo", items=preset_items, default_value=default_value)

    dpg.set_value("preset_name_input", default_value)
    gui_state.current_preset = gui_state.current_device.presets[default_value]
    dpg.set_value("eq_config_input", gui_state.current_preset.to_eq_apo())

    dpg.configure_item("no_device_seleted_group", show=False)
    dpg.configure_item("device_preset_name_inputs_group", show=True)
    dpg.configure_item("presets_combo_group", show=True)
    dpg.configure_item("control_panels_group", show=True)
    dpg.configure_item("preset_name_table_row", show=True)


def print_info_callback(sender, app_data, user_data):
    print(f"sender: {sender}\napp_data: {repr(app_data)}\nuser_data: {user_data}")


def preset_name_input_callback(sender, app_data, user_data):
    global gui_state

    assert gui_state.current_device is not None
    assert gui_state.current_preset is not None

    gui_state.current_device.update_preset_name(
        gui_state.current_preset.name, app_data
    )

    preset_items = [name for name in gui_state.current_device.presets]
    preset_items.extend(PRESETS_COMBO_SPECIAL_ITEMS)
    dpg.configure_item(
        "presets_combo", items=preset_items,
        default_value=gui_state.current_preset.name
    )


def preset_name_save_btn_callback(sender, app_data, user_data):
    tag = "preset_name_input"
    preset_name_input_callback(
        tag,
        dpg.get_value(tag),
        dpg.get_item_user_data(tag),
    )


def device_name_input_callback(sender, app_data, user_data):
    global gui_state

    assert gui_state.current_device is not None

    old_name = gui_state.current_device.name
    gui_state.current_device.update_device_name(app_data)
    new_name = gui_state.current_device.name
    gui_state.devices[new_name] = gui_state.devices.pop(old_name)

    device_items = [name for name in gui_state.devices]
    device_items.extend(DEVICES_COMBO_SPECIAL_ITEMS)
    dpg.configure_item(
        "devices_combo", items=device_items,
        default_value=gui_state.current_device.name
    )


def device_name_save_btn_callback(sender, app_data, user_data):
    tag = "device_name_input"
    device_name_input_callback(
        tag,
        dpg.get_value(tag),
        dpg.get_item_user_data(tag),
    )


def delete_device_btn_callback(sender, app_data, user_data):
    global gui_state

    assert gui_state.current_device is not None

    gui_state.current_device.delete_from_storage()
    gui_state.devices.pop(gui_state.current_device.name)

    gui_state.current_preset = None
    gui_state.current_device = None

    tag = "devices_combo"
    devices_combo_callback(
        tag, "[No Device]",
        dpg.get_item_user_data(tag)
    )

    device_items = [name for name in gui_state.devices]
    device_items.extend(DEVICES_COMBO_SPECIAL_ITEMS)
    dpg.configure_item(
        "devices_combo", default_value="[No Device]",
        items=device_items
    )
    dpg.configure_item("delete_device_popup", show=False)


def delete_preset_btn_callback(sender, app_data, user_data):
    global gui_state

    assert gui_state.current_device is not None
    assert gui_state.current_preset is not None

    gui_state.current_device.delete_preset(gui_state.current_preset)
    gui_state.current_preset = None

    tag = "presets_combo"
    presets_combo_callback(
        tag, "[No Preset]",
        dpg.get_item_user_data(tag)
    )

    preset_items = [name for name in gui_state.current_device.presets]
    preset_items.extend(PRESETS_COMBO_SPECIAL_ITEMS)
    dpg.configure_item(
        "presets_combo", default_value="[No Preset]",
        items=preset_items
    )
    dpg.configure_item("delete_preset_popup", show=False)


def save_preset_config_btn_callback(sender, app_data, user_data):
    global gui_state

    assert gui_state.current_preset is not None
    assert gui_state.current_device is not None

    config_text = dpg.get_value("eq_config_input")
    try:
        new_config = eq_apo_parser.parse_eq_apo_config(
            config_text,
            48000,    # TODO fs
            gui_state.current_preset.name
        )
    except SyntaxError:
        dpg.configure_item("eq_apo_parse_error_popup", show=True)
        return

    gui_state.current_preset = new_config
    gui_state.current_device.update_preset(new_config)


def load_preset_config_btn_callback(sender, app_data, user_data):
    global gui_state

    assert gui_state.current_preset is not None
    assert gui_state.current_device is not None

    path = crossfiledialog.open_file(title="Choose file with APO preset")
    if path == "":
        return

    try:
        new_config = eq_apo_parser.parse_eq_apo_config(
            path,
            48000,    # TODO fs
            gui_state.current_preset.name
        )
    except SyntaxError:
        dpg.configure_item("eq_apo_parse_error_popup", show=True)
        return

    with open(path) as f:
        dpg.set_value("eq_config_input", f.read())

    gui_state.current_preset = new_config
    gui_state.current_device.update_preset(new_config)


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
                    header_row=False, policy=dpg.mvTable_SizingStretchProp,
                ):
                    dpg.add_table_column(label="device", init_width_or_weight=0.5)
                    dpg.add_table_column(label="preset", init_width_or_weight=0.5)

                    with dpg.table_row():
                        with dpg.group(horizontal=True):
                            device_items = [name for name in gui_state.devices]
                            device_items.extend(DEVICES_COMBO_SPECIAL_ITEMS)
                            dpg.add_text("Device:")
                            dpg.add_combo(
                                items=device_items, width=-1,
                                callback=devices_combo_callback, tag="devices_combo",
                                default_value=DEVICES_COMBO_SPECIAL_ITEMS[0],
                            )

                        with dpg.group(horizontal=True, tag="presets_combo_group", show=False):
                            if gui_state.current_device is not None:
                                preset_items = [name for name in gui_state.current_device.presets]
                            else:
                                preset_items = []

                            preset_items.extend(PRESETS_COMBO_SPECIAL_ITEMS)
                            dpg.add_text("Preset:")
                            dpg.add_combo(
                                items=preset_items, width=-1, tag="presets_combo",
                                default_value=PRESETS_COMBO_SPECIAL_ITEMS[0],
                                callback=presets_combo_callback,
                                user_data=PRESETS_COMBO_SPECIAL_ITEMS[0]
                            )

                with dpg.group(tag="no_device_seleted_group"):
                    dpg.add_spacer(height=2)
                    dpg.add_separator()
                    dpg.add_spacer(height=2)
                    dpg.add_text("No Device Selected")

                with dpg.group(tag="device_preset_name_inputs_group", show=False):
                    dpg.add_spacer(height=2)
                    dpg.add_separator()
                    dpg.add_spacer(height=2)

                    with dpg.table(
                        header_row=False, policy=dpg.mvTable_SizingStretchProp
                    ):
                        dpg.add_table_column()
                        dpg.add_table_column()
                        dpg.add_table_column(width_fixed=True, init_width_or_weight=100)
                        dpg.add_table_column(width_fixed=True, init_width_or_weight=100)

                        with dpg.table_row():
                            dpg.add_text("Device Name:")
                            dpg.add_input_text(
                                width=-1, hint="Empty...", on_enter=True,
                                tag="device_name_input",
                                callback=device_name_input_callback
                            )
                            dpg.add_button(
                                label="Save", width=-1, tag="save_device_name_btn",
                                callback=device_name_save_btn_callback,
                            )
                            dpg.add_button(
                                label="Delete", width=-1, tag="delete_device_btn",
                                callback=lambda: dpg.configure_item("delete_device_popup", show=True)
                            )

                        with dpg.table_row(tag="preset_name_table_row"):
                            dpg.add_text("Preset Name:")
                            dpg.add_input_text(
                                width=-1, hint="Empty...",
                                callback=preset_name_input_callback, on_enter=True,
                                tag="preset_name_input",
                            )
                            dpg.add_button(
                                label="Save", width=-1, tag="save_preset_name_btn",
                                callback=preset_name_save_btn_callback
                            )
                            dpg.add_button(
                                label="Delete", width=-1, tag="delete_preset_btn",
                                callback=lambda: dpg.configure_item("delete_preset_popup", show=True)
                            )

                with dpg.group(tag="control_panels_group", show=False):
                    dpg.add_spacer(height=2)
                    dpg.add_separator()
                    dpg.add_spacer(height=2)

                    with dpg.collapsing_header(label="EQ Config"):
                        dpg.add_input_text(
                            multiline=True,
                            width=-1, height=200,
                            hint="Empty...",
                            tag="eq_config_input"
                        )
                        with dpg.table(
                            header_row=False, policy=dpg.mvTable_SizingStretchProp
                        ):
                            dpg.add_table_column(init_width_or_weight=0.5)
                            dpg.add_table_column(init_width_or_weight=0.5)
                            with dpg.table_row():
                                dpg.add_button(
                                    label="Save", width=-1,
                                    callback=save_preset_config_btn_callback
                                )
                                dpg.add_button(
                                    label="Load", width=-1,
                                    callback=load_preset_config_btn_callback
                                )

                    dpg.add_spacer(height=2)
                    dpg.add_separator()
                    dpg.add_spacer(height=2)

                    with dpg.collapsing_header(label="Channel Match (stub)"):
                        with dpg.table(
                            header_row=False,
                            policy=dpg.mvTable_SizingStretchProp,
                        ):
                            dpg.add_table_column(label="Left", init_width_or_weight=0.5)
                            dpg.add_table_column(label="Right", init_width_or_weight=0.5)

                            with dpg.table_row():
                                dpg.add_button(label="Left", width=-1)
                                dpg.add_button(label="Right", width=-1)

                            with dpg.table_row():
                                dpg.add_input_text(
                                    multiline=True,
                                    height=200, hint="Empty...",
                                    width=-1
                                )
                                dpg.add_input_text(
                                    multiline=True,
                                    height=200, hint="Empty...",
                                    width=-1
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

    with dpg.window(
        tag="delete_device_popup",
        modal=True,
        show=False,
        no_title_bar=True,
        no_resize=True,
        width=300,
        height=300,
    ):
        dpg.add_text(
            "Are you sure you want to delete this device "
            "and all its presets?\nBe careful: after removal, "
            "[No Device] mode will be set, and sound "
            "may become louder!", wrap=0)
        dpg.add_separator()

        with dpg.group(horizontal=True):
            dpg.add_button(label="Delete", callback=delete_device_btn_callback)
            dpg.add_button(
                label="Cancel",
                callback=lambda: dpg.configure_item("delete_device_popup", show=False)
            )

    with dpg.window(
        tag="delete_preset_popup",
        modal=True,
        show=False,
        no_title_bar=True,
        no_resize=True,
        width=300,
        height=300,
    ):
        dpg.add_text(
            "Are you sure you want to delete this preset?\n"
            "Be careful: after removal, "
            "[No Preset] mode will be set, and sound "
            "may become louder!", wrap=0
        )
        dpg.add_separator()

        with dpg.group(horizontal=True):
            dpg.add_button(label="Delete", callback=delete_preset_btn_callback)
            dpg.add_button(
                label="Cancel",
                callback=lambda: dpg.configure_item("delete_preset_popup", show=False)
            )

    with dpg.window(
        tag="eq_apo_parse_error_popup",
        modal=True,
        show=False,
        no_title_bar=True,
        no_resize=True,
        width=300,
        height=300,
    ):
        dpg.add_text(
            "An error was occured when parsing EQ APO config", wrap=0
        )
        dpg.add_separator()

        with dpg.group(horizontal=True):
            dpg.add_button(
                label="Close",
                callback=lambda: dpg.configure_item("eq_apo_parse_error_popup", show=False)
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


tray_icon = Image.open("./tray-icon.png") \
    .resize((64, 64), Image.Resampling.LANCZOS)

menu = pystray.Menu(
    pystray.MenuItem("Show EQ Juggler", show_app_action),
    pystray.MenuItem("Quit EQ Juggler", quit_app_action)
)
icon = pystray.Icon("EQ Juggler", tray_icon, "EQ Juggler", menu)
icon.run()

jack_client.kill_jack_event.set()
t.join()

if NODE_AUTO_CONNECT:
    pipewire_utils.destroy_node(new_default_sink.id)
    pipewire_utils.wireplumber_set_default(old_default_sink.id)
