"""Reproduce the Bus blocking-send deadlock with real PipeEndpoint pairs.

Topology mirrors T2 (local multiprocess desktop): a "frontend" thread and the
bus thread share this process, and a slow "backend" runs in a subprocess. The
backend polls at most one batch per tick, ticks slowly, and sends one large
latest-state frame per tick. The frontend sends one small ValueChange per
interval, like a slider emitting on every valueChanged during a drag.

    python scratch/transport_deadlock_repro.py --interval 1.0    # recovers
    python scratch/transport_deadlock_repro.py --interval 0.005  # deadlocks

A deadlock shows as "bus stalled" and "frontend stalled" growing without bound,
followed by a faulthandler stack dump with the frontend blocked sending to the
bus and the bus blocked sending to the backend.

See architecture/design/host-channel-bus-transport.md, "Known Issue: Blocking
Sends Can Deadlock Through the Bus".
"""

from __future__ import annotations

import argparse
import faulthandler
import multiprocessing as mp
import threading
import time

import numpy as np

from compneurovis.core.messages import ValueChange, command_message, update_message
from compneurovis.transports.pipe import make_pipe_pair

TICK_S = 0.3
FRAME_VALUES = 257_054  # segment count of examples/neuron/complete_interface.py


def backend_main(endpoint) -> None:
    while True:
        endpoint.poll()
        time.sleep(TICK_S)
        frame = np.zeros(FRAME_VALUES, dtype=np.float32)
        endpoint.send(update_message(ValueChange({"frame": frame})))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=float, default=0.005)
    parser.add_argument("--seconds", type=int, default=8)
    args = parser.parse_args()

    frontend_pair = make_pipe_pair(left_name="frontend", right_name="bus<->frontend")
    backend_pair = make_pipe_pair(left_name="backend", right_name="bus<->backend")
    backend = mp.get_context("spawn").Process(
        target=backend_main, args=(backend_pair.left,), daemon=True
    )
    backend.start()

    heartbeat = {"bus": time.monotonic(), "frontend": time.monotonic()}

    def bus_loop() -> None:
        # Same shape as Bus.step: drain every channel, then blocking-send.
        while True:
            for message in frontend_pair.right.poll():
                backend_pair.right.send(message)
            for message in backend_pair.right.poll():
                frontend_pair.right.send(message)
            heartbeat["bus"] = time.monotonic()
            time.sleep(0.001)

    def frontend_loop() -> None:
        index = 0
        while True:
            frontend_pair.left.poll()
            frontend_pair.left.send(
                command_message(ValueChange({"ctrl_1_dt": 0.025 + index * 1e-3}))
            )
            index += 1
            heartbeat["frontend"] = time.monotonic()
            time.sleep(args.interval)

    for target in (bus_loop, frontend_loop):
        threading.Thread(target=target, daemon=True).start()

    faulthandler.dump_traceback_later(args.seconds - 1, exit=False)
    for _ in range(args.seconds):
        time.sleep(1.0)
        now = time.monotonic()
        print(
            f"bus stalled {now - heartbeat['bus']:.1f}s  "
            f"frontend stalled {now - heartbeat['frontend']:.1f}s",
            flush=True,
        )


if __name__ == "__main__":
    main()
