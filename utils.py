import numpy as np
from units import dB

RATIO_TO_K = {"amplitude": 2, "power": 1}

def db_to_lin(db: dB | np.ndarray, ratio="amplitude", reference=1) -> float | np.ndarray:
    k = RATIO_TO_K[ratio]
    return 10 ** (db / (10*k)) * reference


def lin_to_db(lin: float | np.ndarray, ratio="amplitude", reference=1) -> dB | np.ndarray:
    k = RATIO_TO_K[ratio]
    return k * 10 * np.log10(lin / reference)


def biquad_derivative(b, a, z):
    hi = b[0] + b[1] / z + b[2] / z**2
    lo = a[0] + a[1] / z + a[2] / z**2

    dhi = -b[1] / z**2 - 2*b[2] / z**3
    dlo = -a[1] / z**2 - 2*a[2] / z**3

    return (lo * dhi - dlo * hi) / lo**2

def biquad(b, a, z):
    return (b[0] + b[1] * z**(-1) + b[2] * z**(-2)) / (a[0] + a[1] * z**(-1) + a[2] * z**(-2))
