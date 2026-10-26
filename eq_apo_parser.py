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
    r"(?P<state>ON|OFF)\s+"
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
        raise SyntaxError(f"Current parser couldn't parse the following line: {repr(line)}")

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
        raise SyntaxError(f"The following line has incorrect syntax: {repr(line)}")

    d = m.groupdict()
    return float(d["gain"])


def parse_eq_apo_config(
    config_or_path: str | Path, fs: int, name: str | None = None
) -> PEQConfig:
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
            filters.append(process_filter(line))
        elif line.strip() == "":
            continue
        else:
            raise SyntaxError(f"Current parser couldn't parse the following line: {repr(line)}")

    return PEQConfig(name, preamp_gain, filters, fs)


if __name__ == "__main__":

    with open("./test-apo-cfg.txt") as f:
        test_apo = f.read()
    test_apo = """Preamp: -11.3 dB
Filter 1: ON PK Fc 64 Hz Gain -8.74 dB Q 0.436
Filter 2: ON LSC Fc 108 Hz Gain 9.83 dB Q 0.728
Filter 3: ON PK Fc 392 Hz Gain -1.39 dB Q 3.202
Filter 4: ON PK Fc 821 Hz Gain 4.17 dB Q 0.598
Filter 5: ON PK Fc 2225 Hz Gain 2.65 dB Q 0.929
Filter 6: ON PK Fc 6187 Hz Gain 10.50 dB Q 0.720
Filter 7: ON PK Fc 6613 Hz Gain -9.26 dB Q 1.716
Filter 8: ON PK Fc 8413 Hz Gain 16.00 dB Q 2.892
Filter 9: ON PK Fc 10817 Hz Gain -15.08 dB Q 1.402
Filter 10: ON HSC Fc 14071 Hz Gain 2.80 dB Q 3.000"""
    apo_cfg = parse_eq_apo_config(test_apo, 48000, "a")
    print(apo_cfg.to_eq_apo())

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

