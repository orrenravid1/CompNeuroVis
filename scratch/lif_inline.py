"""
scratch/lif_inline.py — LIF model using compneurovis.inline sugar API.

Simulation runs in a child process; Qt stays in main process.
No if __name__ == '__main__' required.

Run: python scratch/lif_inline.py
"""
import compneurovis as cnv


class LIFModel:
    def __init__(self) -> None:
        self.rest_voltage_mv      = -68.0
        self.reset_voltage_mv     = -72.0
        self.threshold_voltage_mv = -50.0
        self.membrane_tau_ms      = 18.0
        self.membrane_resistance_mohm = 10.0
        self.tonic_current_na     = 1.7
        self.pulse_amplitude_na   = 2.8
        self.pulse_decay_ms       = 14.0
        self.refractory_ms        = 2.5
        self.reset()

    def reset(self) -> None:
        self.v_mv = float(self.rest_voltage_mv)
        self.pulse_current_na = 0.0
        self.refractory_remaining_ms = 0.0
        self.spike_flag = 0.0

    def deliver_pulse(self) -> None:
        self.pulse_current_na = max(0.0, self.pulse_current_na + self.pulse_amplitude_na)

    @property
    def total_current_na(self) -> float:
        return self.tonic_current_na + self.pulse_current_na

    @property
    def refractory_fraction(self) -> float:
        if self.refractory_remaining_ms <= 0.0:
            return 0.0
        return min(1.0, self.refractory_remaining_ms / max(1e-6, self.refractory_ms))

    def step(self, dt_ms: float) -> None:
        self.spike_flag = 0.0
        self.pulse_current_na = max(
            0.0, self.pulse_current_na * (1.0 - dt_ms / max(1e-6, self.pulse_decay_ms))
        )
        if self.refractory_remaining_ms > 0.0:
            self.refractory_remaining_ms = max(0.0, self.refractory_remaining_ms - dt_ms)
            self.v_mv = float(self.reset_voltage_mv)
            return
        drive_mv = self.membrane_resistance_mohm * self.total_current_na
        dvdt = (self.rest_voltage_mv - self.v_mv + drive_mv) / max(1e-6, self.membrane_tau_ms)
        self.v_mv += dt_ms * dvdt
        if self.v_mv >= self.threshold_voltage_mv:
            self.spike_flag = 1.0
            self.v_mv = float(self.reset_voltage_mv)
            self.refractory_remaining_ms = float(self.refractory_ms)


DT_MS = 0.25
model = LIFModel()
t_ms = [0.0]
paused = [False]
display_dt_ms = [1.0]


def _step():
    if not paused[0]:
        model.step(DT_MS)
        t_ms[0] += DT_MS


def _advance(ctx):
    for _ in range(max(1, int(display_dt_ms[0] / DT_MS))):
        _step()


def _reset(ctx):
    model.reset()
    t_ms[0] = 0.0


sim = cnv.source(_advance)

sim.trace("Membrane voltage",
          read={"Membrane": lambda: model.v_mv,
                "Threshold": lambda: model.threshold_voltage_mv,
                "Reset V":   lambda: model.reset_voltage_mv},
          x=lambda: t_ms[0], y_min=-80, y_max=-40, y_unit="mV")

sim.trace("Drive currents",
          read={"Tonic": lambda: model.tonic_current_na,
                "Pulse":  lambda: model.pulse_current_na,
                "Total":  lambda: model.total_current_na},
          x=lambda: t_ms[0], y_min=0, y_max=12.5, y_unit="nA")

sim.trace("Spike events",
          read={"Spike":      lambda: model.spike_flag,
                "Refractory": lambda: model.refractory_fraction},
          x=lambda: t_ms[0], y_min=-0.05, y_max=1.05)

sim.control("membrane_tau",  label="Membrane tau (ms)",
            get=lambda: model.membrane_tau_ms,
            set=lambda ctx, v: setattr(model, "membrane_tau_ms", v),          min=2.0,   max=80.0)
sim.control("resistance",    label="Resistance (MOhm)",
            get=lambda: model.membrane_resistance_mohm,
            set=lambda ctx, v: setattr(model, "membrane_resistance_mohm", v), min=1.0,   max=25.0)
sim.control("tonic_current", label="Tonic drive (nA)",
            get=lambda: model.tonic_current_na,
            set=lambda ctx, v: setattr(model, "tonic_current_na", v),         min=0.0,   max=4.0)
sim.control("pulse_amp",     label="Pulse amplitude (nA)",
            get=lambda: model.pulse_amplitude_na,
            set=lambda ctx, v: setattr(model, "pulse_amplitude_na", v),       min=0.0,   max=8.0)
sim.control("pulse_decay",   label="Pulse decay (ms)",
            get=lambda: model.pulse_decay_ms,
            set=lambda ctx, v: setattr(model, "pulse_decay_ms", v),           min=2.0,   max=60.0)
sim.control("threshold",     label="Threshold (mV)",
            get=lambda: model.threshold_voltage_mv,
            set=lambda ctx, v: setattr(model, "threshold_voltage_mv", v),     min=-62.0, max=-42.0)
sim.control("refractory",    label="Refractory (ms)",
            get=lambda: model.refractory_ms,
            set=lambda ctx, v: setattr(model, "refractory_ms", v),            min=0.0,   max=10.0)
sim.control("display_dt",    label="Simulation speed (ms/update)",
            get=lambda: display_dt_ms[0],
            set=lambda ctx, v: display_dt_ms.__setitem__(0, v),               min=DT_MS, max=20.0)

sim.action("pause", label="Pause / Resume", fn=lambda ctx: paused.__setitem__(0, not paused[0]))
sim.action("pulse", label="Inject pulse",   fn=lambda ctx: model.deliver_pulse())
sim.action("reset", label="Reset state",    fn=_reset, resets_fields=True)

cnv.show()
