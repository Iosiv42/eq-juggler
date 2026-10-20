from dataclasses import dataclass
import ctypes

import numpy as np
import numpy.ctypeslib as npct
from scipy import signal

from units import dB
import biquad_cookbook as rbj
from utils import db_to_lin, lin_to_db

# FILTER_TYPES = (
#     "PK", "LP", "LPQ", "HP", "HPQ", "AP",
#     "BP", "LS", "LSC", "HS", "HSC", "NO",
# )

clib_apply_peq = npct.load_library("./apply_peq.so", ".")
clib_apply_peq.apply_inplace.argtypes = [
    npct.ndpointer(dtype=np.float32, ndim=2, flags=("C", "W")),
    npct.ndpointer(dtype=np.float32, ndim=2, flags=("C", "W")),
    npct.ndpointer(dtype=np.float32, ndim=1, flags=("C", "W")),
    npct.ndpointer(dtype=np.float32, ndim=2, flags=("C", "W")),
    ctypes.c_int,
    ctypes.c_int,
]
clib_apply_peq.apply_inplace.restype = None


class PEQConfig:
    def __init__(
        self,
        name: str,
        preamp_gain: dB,
        filters: list[ParametricFilter],
        fs: int,
    ):
        self.name = name
        self.preamp_gain = preamp_gain
        self._preamp_gain_lin = db_to_lin(preamp_gain)
        self.filters = filters
        self.change_sample_rate(fs)
        self.zi = (
            np.array([filter.zi for filter in self.filters], np.float32),
            np.array([filter.zi for filter in self.filters], np.float32)
        )


    def change_sample_rate(self, fs: int):
        self.fs = fs
        self.filters_b, self.filters_a = self.calculate_filters_ba()


    def apply_inplace(self, samples, filters_zi):
        try:
            clib_apply_peq.apply_inplace(
                self.filters_b, self.filters_a,
                samples, filters_zi,
                len(self.filters), len(samples)
            )
        except ctypes.ArgumentError:
            pass

        samples *= self._preamp_gain_lin


    def apply_temp(self, samples):
        new_samples = np.copy(samples)
        filters_zi = []
        for b, a in zip(self.filters_b, self.filters_a):
            filters_zi.append(np.real(signal.lfilter_zi(b, a)))

        filters_zi = np.array(filters_zi, np.float32)

        self.apply_inplace(new_samples, filters_zi)
        return new_samples


    def calculate_filters_ba(self):
        all_b = np.empty((len(self.filters), 3), np.float32)
        all_a = np.empty((len(self.filters), 3), np.float32)
        for i, filter in enumerate(self.filters):
            b, a = filter.calculate_ba(self.fs)
            all_b[i] = b
            all_a[i] = a

        return (all_b, all_a)


    def magnitude_response(self, freq_bins, *, in_db=True):
        mag_resp = np.zeros_like(freq_bins)
        for filter in self.filters:
            _, h = signal.freqz(filter.b, filter.a, worN=freq_bins, fs=self.fs)
            mag_resp += lin_to_db(np.abs(h))

        if in_db:
            return mag_resp + self.preamp_gain

        return db_to_lin(mag_resp) * db_to_lin(self.preamp_gain)


    def max_gain(self, *, initial_bins_amount: int = 65536) -> dB:
        bins = np.linspace(0, self.fs, initial_bins_amount)
        mag_resp = self.magnitude_response(bins)

        ranges_of_maximums = []
        for i in range(1, len(mag_resp) - 1):
            left = mag_resp[i - 1]
            mid = mag_resp[i]
            right = mag_resp[i + 1]

            if left < mid and right < mid:
                ranges_of_maximums.append((bins[i - 1], bins[i + 1]))

        maximum = max(mag_resp)
        for f1, f2 in ranges_of_maximums:
            tmp_bins = np.linspace(f1, f2, 1024)
            maximum = max(
                maximum,
                max(self.magnitude_response(tmp_bins))
            )

        return maximum


    @property
    def preamp_gain(self):
        return self._preamp_gain

    @preamp_gain.setter
    def preamp_gain(self, new_gain: dB):
        self._preamp_gain = new_gain
        self._preamp_gain_lin = db_to_lin(new_gain)


@dataclass
class ParametricFilter:
    idx: int
    state: bool
    type: str
    frequency: float
    gain: dB | None
    q: float | None

    def calculate_ba(self, fs):
        Wn = 2 * self.frequency / fs

        match self.type:
            case "PK":
                self.b, self.a = rbj.peaking(Wn, self.gain, self.q)
            case "LP":
                self.b, self.a = rbj.lowpass(Wn)
            case "LPQ":
                self.b, self.a = rbj.lowpass(Wn, self.q)
            case "HP":
                self.b, self.a = rbj.highpass(Wn)
            case "HPQ":
                self.b, self.a = rbj.highpass(Wn, self.q)
            case "BP":
                self.b, self.a = rbj.bandpass(Wn, self.q)
            case "LS":
                self.b, self.a = rbj.shelf(Wn, self.gain)
            case "LSC":
                self.b, self.a = rbj.shelf(Wn, self.gain, self.__q_to_s())
            case "HS":
                self.b, self.a = rbj.shelf(Wn, self.gain, btype="high")
            case "HSC":
                self.b, self.a = rbj.shelf(Wn, self.gain, self.__q_to_s(), btype="high")
            case "NO":
                if self.q is None:
                    self.b, self.a = rbj.notch(Wn, 1)    # 1?
                self.b, self.a = rbj.notch(Wn, self.q)
            case "AP":
                self.b, self.a = rbj.allpass(Wn, self.q)
            case _:
                raise RuntimeError()

        self.b = np.astype(self.b, np.float64)
        self.a = np.astype(self.a, np.float64)

        self.zi = signal.lfilter_zi(self.b, self.a)
        return (self.b, self.a)


    def __q_to_s(self):
        A = 10 ** (self.gain / 40)
        v1 = 1 / self.q**2 - 2
        v2 = A + 1/A

        return 1 / (v1/v2 + 1)
