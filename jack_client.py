#!/usr/bin/env python3

"""Create a JACK client that copies input audio directly to the outputs.

This is somewhat modeled after the "thru_client.c" example of JACK 2:
http://github.com/jackaudio/jack2/blob/master/example-clients/thru_client.c

If you have a microphone and loudspeakers connected, this might cause an
acoustical feedback!

"""
import os
import jack
import threading

peq_cfg = None
peq_cfg_lock = threading.RLock()
client_started_event = threading.Event()


def start_jack():
    global client
    global event

    clientname = "EQ Juggler"
    servername = None

    try:
        client = jack.Client(clientname, use_exact_name=True, servername=servername)
    except jack.JackOpenError:
        clientname = f"{clientname}-{os.getpid()}"
        client = jack.Client(clientname, use_exact_name=True, servername=servername)

    if client.status.server_started:
        print('JACK server started')
    if client.status.name_not_unique:
        print(f'unique name {client.name!r} assigned')

    event = threading.Event()

    @client.set_process_callback
    def process(frames):
        global peq_cfg
        global peq_cfg_lock

        assert len(client.inports) == len(client.outports)
        assert frames == client.blocksize
        for i, o, channel_filters_zi in zip(client.inports, client.outports, peq_cfg.zi):
            with peq_cfg_lock:
                new_buf, new_zi = peq_cfg.apply_inplace(i.get_array(), channel_filters_zi)
            o.get_array()[:] = new_buf
            channel_filters_zi[:] = new_zi


    @client.set_shutdown_callback
    def shutdown(status, reason):
        print('JACK shutdown!')
        print('status:', status)
        print('reason:', reason)
        event.set()


    @client.set_xrun_callback
    def xrun(delay):
        print('xrun; delay', delay, 'microseconds')


# create two port pairs
    for number in 1, 2:
        client.inports.register(f'input_{number}')
        client.outports.register(f'output_{number}')

    with client:
        # When entering this with-statement, client.activate() is called.
        # This tells the JACK server that we are ready to roll.
        # Our process() callback will start running now.

        # Connect the ports.  You can't do this before the client is activated,
        # because we can't make connections to clients that aren't running.
        # Note the confusing (but necessary) orientation of the driver backend
        # ports: playback ports are "input" to the backend, and capture ports
        # are "output" from it.

        client_started_event.set()

        capture = client.get_ports(is_physical=True, is_output=True)
        if not capture:
            raise RuntimeError('No physical capture ports')

        # for src, dest in zip(capture, client.inports):
        #     client.connect(src, dest)

        playback = client.get_ports(is_physical=True, is_input=True)
        if not playback:
            raise RuntimeError('No physical playback ports')

        # for src, dest in zip(client.outports, playback):
        #     client.connect(src, dest)

        try:
            event.wait()
        except KeyboardInterrupt:
            print('\nInterrupted by user')

# When the above with-statement is left (either because the end of the
# code block is reached, or because an exception was raised inside),
# client.deactivate() and client.close() are called automatically.
