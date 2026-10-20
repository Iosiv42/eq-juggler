from ctypes import ArgumentError
from os import PathLike
import os
import re
import math
import time
import numpy as np
from scipy import signal
from pathlib import Path

from peq_config import PEQConfig, ParametricFilter
from units import dB
from utils import lin_to_db, db_to_lin
import biquad_cookbook as rbj


FILTER_RE = re.compile(
    r"Filter\s+(?P<idx>\d+):\s+"
    r"(?P<state>ON|OFF>)\s+"
    r"(?P<type>PK|LP|LPQ|HP|HPQ|BP|LS|LSC|HS|HSC|NO|AP)\s+"
    r"Fc\s+(?P<frequency>\d+(\.\d+)?)\s+Hz"
    r"(\s+Gain\s+(?P<gain>-?\d+(\.\d+)?)\s+dB)?"
    r"(\s+(?P<q_or_bw_type>(Q|BW\s+Oct))\s+(?P<q_or_bandwidth_in_octaves>\d+(\.\d+)?))?"
)

PREAMP_RE = re.compile(r"Preamp:\s+(?P<gain>-?\d+(\.\d+)?)\sdB")


def bandwidth_in_octaves_to_q(bandwidth_in_octaves: float):
    tmp = 2 ** bandwidth_in_octaves
    return math.sqrt(tmp) / (tmp - 1)


def process_filter(line: str) -> ParametricFilter:
    m = FILTER_RE.match(line.strip())

    if m is None:
        raise SyntaxError(f"Current parser couldn't parse the following line: {line}")

    d = m.groupdict()
    
    if d["q_or_bandwidth_in_octaves"] is not None:
        q_or_bw = float(d["q_or_bandwidth_in_octaves"])
        if d["q_or_bw_type"] == "Q":
            q = q_or_bw
        else:
            q = bandwidth_in_octaves_to_q(q_or_bw)
    else:
        q = None

    if d["gain"] is not None:
        gain = float(d["gain"])
    else:
        gain = None

    return ParametricFilter(
        int(d["idx"]),
        d["state"] == "ON",
        d["type"],
        float(d["frequency"]),
        gain,
        q
    )


def process_preamp(line: str) -> dB:
    m = PREAMP_RE.match(line.strip())
    if m is None:
        raise SyntaxError(f"The following line has incorrect syntax: {line}")

    d = m.groupdict()
    return float(d["gain"])


def parse_eq_apo_config(config_or_path: str, fs: int, name: str | None = None) -> PEQConfig:
    try:
        Path(config_or_path).resolve()
        with open(config_or_path) as f:
            config = f.read()

        if name is None:
            name = Path(config_or_path).stem
    except (OSError, ValueError):
        if name is None:
            raise ValueError(
                "Cannot determine name because config_or_path is str "
                "and name is None"
            )
        config = config_or_path

    filters = []
    preamp_gain = 0
    for line in config.split("\n"):
        if line.startswith("Preamp"):
            preamp_gain = process_preamp(line)

        elif line.startswith("Filter"):
            try:
                filters.append(process_filter(line))
            except SyntaxError as e:
                print(e)

        else:
            continue

    return PEQConfig(name, preamp_gain, filters, fs)


if __name__ == "__main__":
    test_apo = """Preamp: -8.1 dB
    Filter 1: ON PK Fc 37 Hz Gain -0.65 dB BW Oct 1.857
    Filter 2: ON PK Fc 51 Hz Gain 1.57 dB Q 4.138
    Filter 3: ON PK Fc 69 Hz Gain -1.77 dB Q 4.138
    Filter 4: ON PK Fc 129 Hz Gain -9.85 dB Q 1.071
    Filter 5: ON PK Fc 248 Hz Gain 10.89 dB Q 1.414
    Filter 6: ON PK Fc 538 Hz Gain -3.62 dB Q 4.138
    Filter 7: ON PK Fc 715 Hz Gain 2.08 dB Q 1.414
    Filter 8: ON PK Fc 1076 Hz Gain -1.45 dB Q 4.138
    Filter 9: ON PK Fc 1780 Hz Gain 1.64 dB Q 3.172
    Filter 10: ON PK Fc 2747 Hz Gain -2.27 dB Q 3.172
    Filter 11: ON PK Fc 3633 Hz Gain 3.93 dB Q 7.026
    Filter 12: ON PK Fc 4156 Hz Gain -0.83 dB Q 7.026
    Filter 13: ON PK Fc 5777 Hz Gain -6.06 dB Q 5.393
    Filter 14: ON PK Fc 7123 Hz Gain 0.99 dB Q 4.138
    Filter 15: ON PK Fc 8109 Hz Gain -5.52 dB Q 7.074
    Filter 16: ON PK Fc 9656 Hz Gain 9.97 dB Q 4.165
    Filter 17: ON PK Fc 12452 Hz Gain -11.05 dB Q 3.172
    Filter 18: ON PK Fc 15051 Hz Gain 4.74 dB Q 5.393
    Filter 19: ON LP Fc 10000 Hz"""

    with open("./test-apo-cfg.txt") as f:
        test_apo = f.read()
    apo_cfg = parse_eq_apo_config("/home/paro/Downloads/JT1/PEQdB Diamond Beta for KB501X.txt", 48000)
    print(apo_cfg.filters)

    fs = 48000

    freqs = np.logspace(np.log10(20), np.log10(20_000), 1024)
    mr = apo_cfg.magnitude_response(freqs)
    np.savetxt("test_fr.txt", np.array((freqs, mr)).T)

    # noise = np.random.normal(size=1024)
    # ti = time.perf_counter()
    # filtered = apo_cfg.apply_unchecked(noise, fs)
    # print(time.perf_counter() - ti)
    # print(filtered)

    max_gain = apo_cfg.max_gain()
    print(np.ceil(max_gain * 10) / 10)

