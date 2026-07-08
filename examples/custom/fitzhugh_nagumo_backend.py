"""FitzHugh-Nagumo model using source-level inline authoring.

Run: python examples/custom/fitzhugh_nagumo_backend.py
"""

from __future__ import annotations

import compneurovis as cnv


DT_MS = 0.05


class FitzHughNagumoModel:
    def __init__(self) -> None:
        self.a = 0.7
        self.b = 0.8
        self.tau = 12.5
        self.holding_current = 0.4
        self.exc_weight = 0.9
        self.inh_weight = 0.7
        self.tau_exc = 18.0
        self.tau_inh = 30.0
        self.t_ms = 0.0
        self.reset()

    def reset(self) -> None:
        self.t_ms = 0.0
        self.v = -1.0
        self.w = 1.0
        self.g_exc = 0.0
        self.g_inh = 0.0
        self.dvdt = 0.0

    def excite(self) -> None:
        self.g_exc += self.exc_weight

    def inhibit(self) -> None:
        self.g_inh += self.inh_weight

    @property
    def drive_term(self) -> float:
        return self.holding_current + self.g_exc - self.g_inh

    @property
    def cubic_term(self) -> float:
        return self.v - (self.v**3) / 3.0

    @property
    def recovery_term(self) -> float:
        return -self.w

    def step(self, dt_ms: float = DT_MS) -> None:
        self.t_ms += dt_ms
        self.g_exc *= max(0.0, 1.0 - dt_ms / max(1e-6, self.tau_exc))
        self.g_inh *= max(0.0, 1.0 - dt_ms / max(1e-6, self.tau_inh))
        self.dvdt = self.cubic_term + self.recovery_term + self.drive_term
        dwdt = (self.v + self.a - self.b * self.w) / max(1e-6, self.tau)
        self.v += dt_ms * self.dvdt
        self.w += dt_ms * dwdt


model = FitzHughNagumoModel()
src = cnv.source(lambda ctx: model.step())

state = src.line(
    "State",
    x=lambda: model.t_ms,
    read={"Voltage": lambda: model.v, "Recovery": lambda: model.w},
    y_label="State",
    rolling_window=400.0,
    y_min=-3.0,
    y_max=3.0,
    series_colors={"Voltage": "#00d2be", "Recovery": "#ff50b4"},
)
drive = src.line(
    "Drive",
    x=lambda: model.t_ms,
    read={"Exc drive": lambda: model.g_exc, "Inh drive": lambda: model.g_inh},
    y_label="Drive",
    rolling_window=400.0,
    y_min=0.0,
    y_max=2.0,
    series_colors={"Exc drive": "#ff8c00", "Inh drive": "#a000ff"},
)
dv_terms = src.line(
    "dV terms",
    x=lambda: model.t_ms,
    read={
        "v - v^3/3": lambda: model.cubic_term,
        "-w": lambda: model.recovery_term,
        "drive": lambda: model.drive_term,
        "dV/dt": lambda: model.dvdt,
    },
    y_label="Term value",
    rolling_window=400.0,
    y_min=-4.0,
    y_max=4.0,
    series_colors={"v - v^3/3": "#00d2be", "-w": "#ff50b4", "drive": "#ff8c00", "dV/dt": "#ff3366"},
)


def slider(name: str, label: str, attr: str, min_value: float, max_value: float, steps: int, *, scale: str = "linear"):
    src.control(
        name,
        label=label,
        get=lambda attr=attr: getattr(model, attr),
        set=lambda ctx, value, attr=attr: setattr(model, attr, float(value)),
        min=min_value,
        max=max_value,
        presentation=cnv.ControlPresentationSpec(kind="slider", steps=steps, scale=scale),
    )


slider("a", "a", "a", 0.1, 1.5, 140)
slider("b", "b", "b", 0.1, 1.5, 140)
slider("tau", "tau (ms)", "tau", 1.0, 40.0, 195, scale="log")
slider("holding_current", "Holding current", "holding_current", -1.0, 2.0, 300)
slider("exc_weight", "Exc kick weight", "exc_weight", 0.0, 2.5, 200)
slider("inh_weight", "Inh kick weight", "inh_weight", 0.0, 2.5, 200)
slider("tau_exc", "Exc decay (ms)", "tau_exc", 2.0, 80.0, 195, scale="log")
slider("tau_inh", "Inh decay (ms)", "tau_inh", 2.0, 80.0, 195, scale="log")
src.action("excite", label="Excitatory kick", fn=lambda ctx: model.excite())
src.action("inhibit", label="Inhibitory kick", fn=lambda ctx: model.inhibit())
src.action("reset", label="Reset", fn=lambda ctx: model.reset(), resets_fields=True)

cnv.layout(((state, drive), (dv_terms,), (src.controls_panel,)))

cnv.show(title="FitzHugh-Nagumo model")
