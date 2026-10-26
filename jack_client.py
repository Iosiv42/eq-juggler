import os
import jack
import threading
import numpy as np

from peq_config import PEQConfig
from dataclasses import dataclass, field
from utils import SingletonMeta


@dataclass
class JackSettings(metaclass=SingletonMeta):
    lock: threading.RLock = threading.RLock()
    current_eq_preset: PEQConfig | None = None
    eq_presets: list[PEQConfig] = field(default_factory=list)
    bypass: bool = False
    swap_channels: bool = False
    post_gain_lin: float = 1

settings = JackSettings()
client: jack.Client
kill_jack_event = threading.Event()
scratch_buf: np.ndarray
client_started_event = threading.Event()


def start_jack():
    global client
    global kill_jack_event
    global settings
    global scratch_buf

    clientname = "EQ Juggler"
    servername = None

    try:
        client = jack.Client(clientname, use_exact_name=True, servername=servername)
    except jack.JackOpenError:
        clientname = f"{clientname}-{os.getpid()}"
        client = jack.Client(clientname, use_exact_name=True, servername=servername)

    if client.status.name_not_unique:
        raise RuntimeError(
            f"Jack client name -- {clientname} -- is not unique. "
            "It's an issue that needs to be fixed."
        )

    @client.set_process_callback
    def process(frames):
        global settings
        global client
        global scratch_buf

        assert len(client.inports) == len(client.outports)
        assert frames == client.blocksize

        with settings.lock:
            if settings.bypass:
                for i, o in zip(client.inports, client.outports):
                    o.get_buffer()[:] = i.get_buffer()

                return

            if settings.swap_channels:
                outports = client.outports[::-1]
            else:
                outports = client.outports

            for idx, (i, o) in enumerate(zip(client.inports, outports)):
                scratch_buf[:] = i.get_array()
                try:
                    settings.current_eq_preset.apply_inplace_double(
                        scratch_buf, settings.current_eq_preset.zi_double[idx]
                    )
                except AttributeError:
                    pass
                scratch_buf *= settings.post_gain_lin
                o.get_array()[:] = scratch_buf


    @client.set_shutdown_callback
    def shutdown(status, reason):
        print('JACK shutdown!')
        print('status:', status)
        print('reason:', reason)
        kill_jack_event.set()


    @client.set_xrun_callback
    def xrun(delay):
        print('xrun; delay', delay, 'microseconds')


    @client.set_blocksize_callback
    def blocksize_callback(blocksize: int):
        global scratch_buf
        scratch_buf = np.empty(blocksize, np.float32)


    for number in 1, 2:
        client.inports.register(f'input_{number}')
        client.outports.register(f'output_{number}')

    with client:
        client_started_event.set()
        scratch_buf = np.empty(client.blocksize, np.float32)

        try:
            kill_jack_event.wait()
        except KeyboardInterrupt:
            print('\nInterrupted by user')
