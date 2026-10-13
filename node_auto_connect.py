# TODO . I think there is some way to do this all in machine readable format


import re
import subprocess
from dataclasses import dataclass
import json

SINK_RE = re.compile(r"^[^*]+(?P<is_default>\*)?\s+(?P<id>\d+)\.\s+(?P<unstripped_name>.*)\[.+\]")
PW_LINK_RE = re.compile(r"^\s+(?P<id>\d+)\s+(?P<node_name>[^:]+):(?P<port_name>.+)")


@dataclass
class Sink:
    id: int
    node_description: str
    is_default: bool

    def __post_init__(self):
        pw_dump = json.loads(
            subprocess.run("pw-dump", capture_output=True).stdout
        )

        self_node = next(filter(lambda e: e["id"] == self.id, pw_dump))
        self.node_name = self_node["info"]["props"]["node.name"]


@dataclass
class PwLinkPort:
    id: int
    node_name: str
    port_name: str


def split_list_by(item, l):
    new_list = []
    prev_item_idx = -1
    while prev_item_idx < len(l):
        try:
            idx = l.index(item, prev_item_idx + 1)
        except ValueError:
            new_list.append(l[prev_item_idx + 1:])
            break
        new_list.append(l[prev_item_idx + 1:idx])
        prev_item_idx = idx
    return new_list


def split_list_by_item_iter(item, l):
    prev_item_idx = -1
    while prev_item_idx < len(l):
        try:
            idx = l.index(item, prev_item_idx + 1)
        except ValueError:
            yield l[prev_item_idx + 1:]
            return
        yield l[prev_item_idx + 1:idx]
        prev_item_idx = idx


def get_sinks() -> list[Sink]:
    wp_status = subprocess.run(["wpctl", "status"], capture_output=True) \
        .stdout \
        .decode() \
        .split("\n")

    audio_tree = next(filter(
        lambda tree: tree[0] == "Audio",
        split_list_by_item_iter("", wp_status)
    ))

    sinks_branch = next(filter(
        lambda branch: branch[0] == " ├─ Sinks:",
        split_list_by_item_iter(" │  ", audio_tree)
    ))

    sinks = []
    for sink in sinks_branch[1:]:
        m = re.match(SINK_RE, sink)
        if m is None:
            raise RuntimeError
        gd = m.groupdict()
        sinks.append(Sink(int(gd["id"]), gd["unstripped_name"].strip(), gd["is_default"] is not None))

    return sinks


def get_input_ports() -> list[PwLinkPort]:
    all_inputs = subprocess.run(["pw-link", "-iI"], capture_output=True) \
        .stdout \
        .decode() \
        .split("\n")

    input_ports = []
    for input_str in all_inputs:
        m = re.match(PW_LINK_RE, input_str)
        if m is None:
            continue
        gd = m.groupdict()
        input_ports.append(PwLinkPort(int(gd["id"]), gd["node_name"], gd["port_name"]))

    return input_ports


def get_input_ports_by_node_name(node_name) -> list[PwLinkPort]:
    return tuple(filter(lambda port: port.node_name == node_name, get_input_ports()))


def get_output_ports() -> list[PwLinkPort]:
    all_inputs = subprocess.run(["pw-link", "-oI"], capture_output=True) \
        .stdout \
        .decode() \
        .split("\n")

    input_ports = []
    for input_str in all_inputs:
        m = re.match(PW_LINK_RE, input_str)
        if m is None:
            continue
        gd = m.groupdict()
        input_ports.append(PwLinkPort(int(gd["id"]), gd["node_name"], gd["port_name"]))

    return input_ports


def get_output_ports_by_node_name(node_name) -> list[PwLinkPort]:
    return tuple(filter(lambda port: port.node_name == node_name, get_output_ports()))
