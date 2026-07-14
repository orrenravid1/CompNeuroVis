"""
Scratch exploration of an HH -> competing ligands -> receptor/effector -> HH chain
where the downstream effector additively modulates a selected HH parameter while the
downstream neuron also receives tonic current.

What this tests:
  - upstream Hodgkin-Huxley point cell produces spikes
  - a NetCon delivers event-driven transmitter pulses into GenericLigand.NET_RECEIVE
  - a second GenericLigand acts as a continuously applied competing drug
  - both ligands compete for the same GenericReceptor with separate Kd / efficacy / decay sliders
  - receptor activation drives a SetpointRelaxEffector
  - effector output additively modulates one selected downstream HH parameter
  - downstream HH point cell also receives independent tonic current drive

Rewritten on the inline source API (was a BufferedSession subclass). The model
(HHPointCell, the cascade build, the per-step downstream modulation) is unchanged;
only the CompNeuroVis layer moved to cnv.neuron.source + record_refs + line.

The original per-target modulation-gain slider was re-ranged whenever you picked a
different target parameter. The inline control layer has no runtime re-spec, so the
gain is expressed instead as a single dimensionless "modulation strength" that scales
each target's natural gain: strength 1.0 reproduces the original per-target default
delta, and switching targets keeps a sensible magnitude automatically.

Requires compiled bundled mechanisms under examples/neuron/signaling_cascade_mod/.
Compile from inside that directory (for example `nrnivmodl.bat .` on Windows or
`nrnivmodl .` on Unix/macOS).

Run: python scratch/hh_competing_ligand_parameter_modulation_exploration.py
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from neuron import h, load_mechanisms

import compneurovis as cnv


h.load_file("stdrun.hoc")

TITLE = "HH ligand parameter-modulation exploration"

POINT_LENGTH_UM = 12.6157
POINT_DIAM_UM = 12.6157
CONTINUOUS_CLAMP_DUR_MS = 1.0e9

DT_MS = 0.025
DISPLAY_DT_MS = 0.10
V_INIT = -65.0
ROLLING_WINDOW_MS = 180.0
LINE_PLOT_MAX_REFRESH_HZ = 40.0

MECHANISM_DIR = Path(__file__).resolve().parents[1] / "examples" / "neuron" / "signaling_cascade_mod"

VOLTAGE_COLOR = "#00d2be"
TRANSMITTER_COLOR = "#2356b8"
DRUG_COLOR = "#d1495b"
TRANSMITTER_BOUND_COLOR = "#6fb7ff"
DRUG_BOUND_COLOR = "#ff93ae"
OCCUPANCY_COLOR = "#2f9e44"
ACTIVATION_COLOR = "#7d3cff"
EFFECTOR_S_COLOR = "#ff8c00"
EFFECTOR_S_INF_COLOR = "#222222"
BASELINE_PARAM_COLOR = "#6c757d"
PARAM_DELTA_COLOR = "#1c7c54"
EFFECTIVE_PARAM_COLOR = "#e67700"


class HHPointCell:
    def __init__(
        self,
        name: str,
        *,
        clamp_amp: float,
        gnabar: float = 0.12,
        gkbar: float = 0.036,
        gl: float = 0.0003,
        el: float = -54.3,
        ena: float = 50.0,
        ek: float = -77.0,
        cm: float = 1.0,
    ) -> None:
        self.name = name
        self.clamp_amp = float(clamp_amp)
        self.gnabar = float(gnabar)
        self.gkbar = float(gkbar)
        self.gl = float(gl)
        self.el = float(el)
        self.ena = float(ena)
        self.ek = float(ek)
        self.cm = float(cm)

        self.section = None
        self.segment = None
        self.clamp = None
        self.commanded_current_na = float(clamp_amp)

    def build(self) -> None:
        self.section = h.Section(name=self.name)
        self.section.L = POINT_LENGTH_UM
        self.section.diam = POINT_DIAM_UM
        self.section.nseg = 1
        self.section.insert("hh")

        self.segment = self.section(0.5)
        self.clamp = h.IClamp(self.segment)
        self.clamp.delay = 0.0
        self.clamp.dur = CONTINUOUS_CLAMP_DUR_MS

        self.apply_runtime_parameters()
        self.set_commanded_current(self.clamp_amp)

    def apply_runtime_parameters(self) -> None:
        if self.section is None:
            return
        self.section.cm = float(self.cm)
        for seg in self.section:
            seg.gnabar_hh = float(self.gnabar)
            seg.gkbar_hh = float(self.gkbar)
            seg.gl_hh = float(self.gl)
            seg.el_hh = float(self.el)
            seg.ena = float(self.ena)
            seg.ek = float(self.ek)

    def set_commanded_current(self, amplitude_na: float) -> None:
        self.commanded_current_na = float(amplitude_na)
        if self.clamp is None:
            return
        self.clamp.delay = 0.0
        self.clamp.dur = CONTINUOUS_CLAMP_DUR_MS
        self.clamp.amp = self.commanded_current_na


@dataclass(frozen=True, slots=True)
class ParameterSpec:
    key: str
    label: str
    default: float
    min_value: float
    max_value: float
    slider_steps: int
    clip_min: float
    clip_max: float
    gain: float  # additive delta per unit effector output at modulation strength 1.0


# (key, label, default, min, max, steps, clip_min, clip_max, gain)
DOWNSTREAM_PARAMETER_SPECS = (
    ParameterSpec("gnabar", "Downstream gNa (S/cm^2)", 0.12, 0.01, 0.30, 290, 0.0, 0.35, 0.08),
    ParameterSpec("gkbar", "Downstream gK (S/cm^2)", 0.036, 0.005, 0.10, 190, 0.0, 0.12, 0.03),
    ParameterSpec("gl", "Downstream gL (S/cm^2)", 0.0003, 0.00005, 0.005, 220, 0.0, 0.01, 0.001),
    ParameterSpec("el", "Downstream EL (mV)", -54.3, -80.0, -30.0, 250, -90.0, -20.0, 12.0),
    ParameterSpec("ena", "Downstream ENa (mV)", 50.0, 35.0, 80.0, 225, 20.0, 90.0, 8.0),
    ParameterSpec("ek", "Downstream EK (mV)", -77.0, -110.0, -50.0, 240, -120.0, -40.0, 8.0),
    ParameterSpec("cm", "Downstream Cm (uF/cm^2)", 1.0, 0.2, 3.0, 280, 0.1, 4.0, 0.8),
)
DOWNSTREAM_PARAMETER_MAP = {spec.key: spec for spec in DOWNSTREAM_PARAMETER_SPECS}
DOWNSTREAM_PARAMETER_KEYS = tuple(spec.key for spec in DOWNSTREAM_PARAMETER_SPECS)
DEFAULT_MOD_TARGET = "el"


def ensure_bundled_mechanisms_loaded() -> None:
    if load_mechanisms(str(MECHANISM_DIR), warn_if_already_loaded=False):
        return
    raise RuntimeError(
        "Bundled NEURON mechanisms are not compiled. "
        f"From inside '{MECHANISM_DIR}', compile .mod files so NEURON can load "
        "nrnmech.dll on Windows or platform-specific libnrnmech.* on Unix/macOS."
    )


ensure_bundled_mechanisms_loaded()

# --- runtime parameters not owned by a single mechanism -------------------------
runtime = SimpleNamespace(
    celsius=6.3,
    pulse_event_weight=2.5,
    pulse_threshold=0.0,
    downstream_tonic_current=0.06,
    downstream_mod_target=DEFAULT_MOD_TARGET,
    downstream_mod_strength=1.0,
    # live readouts for the modulation plot, refreshed every step
    downstream_target_base=DOWNSTREAM_PARAMETER_MAP[DEFAULT_MOD_TARGET].default,
    downstream_target_delta=0.0,
    downstream_target_value=DOWNSTREAM_PARAMETER_MAP[DEFAULT_MOD_TARGET].default,
)

# per-parameter baseline values the effector modulates around
downstream_base = SimpleNamespace(**{spec.key: spec.default for spec in DOWNSTREAM_PARAMETER_SPECS})

# --- build the model ------------------------------------------------------------
upstream = HHPointCell("upstream_hh", clamp_amp=0.18)
downstream = HHPointCell("downstream_hh", clamp_amp=0.06)
upstream.build()
downstream.build()

cascade_section = h.Section(name="cascade")
cascade_section.L = 10.0
cascade_section.diam = 10.0
cascade_section.nseg = 1
cascade_section.insert("pas")

pulse_ligand = h.GenericLigand(cascade_section(0.5))
drug_ligand = h.GenericLigand(cascade_section(0.5))
receptor = h.GenericReceptor(cascade_section(0.5))
effector = h.SetpointRelaxEffector(cascade_section(0.5))

pulse_ligand.C_init = 0.0
pulse_ligand.external_input = 0.0
drug_ligand.C_init = 0.0
receptor.n_ligands = 2

h.setpointer(pulse_ligand._ref_C, "C_lig1", receptor)
h.setpointer(drug_ligand._ref_C, "C_lig2", receptor)
h.setpointer(receptor._ref_activation, "drive", effector)

upstream_to_pulse_ligand = h.NetCon(upstream.segment._ref_v, pulse_ligand, sec=upstream.section)
upstream_to_pulse_ligand.delay = 0.0


def apply_downstream_modulation() -> None:
    # reset every downstream parameter to its baseline, then let the effector push
    # only the selected target away from baseline; also drive the tonic current.
    for key in DOWNSTREAM_PARAMETER_KEYS:
        setattr(downstream, key, float(getattr(downstream_base, key)))

    spec = DOWNSTREAM_PARAMETER_MAP[str(runtime.downstream_mod_target)]
    base_value = float(getattr(downstream_base, spec.key))
    delta = float(runtime.downstream_mod_strength) * spec.gain * float(effector.effect)
    effective_value = min(spec.clip_max, max(spec.clip_min, base_value + delta))

    setattr(downstream, spec.key, effective_value)
    downstream.apply_runtime_parameters()
    downstream.set_commanded_current(float(runtime.downstream_tonic_current))

    runtime.downstream_target_base = base_value
    runtime.downstream_target_delta = effective_value - base_value
    runtime.downstream_target_value = effective_value


def apply_runtime_parameters() -> None:
    h.celsius = float(runtime.celsius)
    upstream.apply_runtime_parameters()
    upstream.set_commanded_current(upstream.clamp_amp)
    upstream_to_pulse_ligand.threshold = float(runtime.pulse_threshold)
    upstream_to_pulse_ligand.weight[0] = float(runtime.pulse_event_weight)
    apply_downstream_modulation()


def step() -> None:
    # runs in place of h.fadvance(): re-apply the effector-driven modulation to the
    # downstream cell every solver step, then advance.
    apply_downstream_modulation()
    h.fadvance()


apply_runtime_parameters()
h.dt = DT_MS
h.finitialize(V_INIT)

# --- source ---------------------------------------------------------------------
src = cnv.neuron.source(
    sections=[upstream.section, downstream.section, cascade_section],
    dt=DT_MS,
    display_dt=DISPLAY_DT_MS,
    v_init=V_INIT,
    step=step,
    title=TITLE,
)


def plot(name, refs, series, colors, *, y_label, y_unit="", show_legend=True, y_min=None, y_max=None):
    data = src.record_refs(name, refs=tuple(refs), series=tuple(series), unit=y_unit or "a.u.", window=ROLLING_WINDOW_MS)
    return src.line(
        name,
        source=data,
        x_label="Time",
        x_unit="ms",
        y_label=y_label,
        y_unit=y_unit,
        show_legend=show_legend,
        colors={label: color for label, color in zip(series, colors)},
        background_color="white",
        rolling_window=ROLLING_WINDOW_MS,
        trim_to_rolling_window=True,
        max_refresh_hz=LINE_PLOT_MAX_REFRESH_HZ,
        y_min=y_min,
        y_max=y_max,
        x_major_tick_spacing=40.0,
        x_minor_tick_spacing=10.0,
    )


upstream_voltage = plot(
    "Upstream HH voltage",
    (upstream.segment._ref_v,),
    ("Voltage",),
    (VOLTAGE_COLOR,),
    y_label="Voltage", y_unit="mV", show_legend=False, y_min=-90.0, y_max=60.0,
)
competition = plot(
    "Ligands and receptor competition",
    (pulse_ligand._ref_C, drug_ligand._ref_C, receptor._ref_bound1, receptor._ref_bound2,
     receptor._ref_occupancy, receptor._ref_activation),
    ("Transmitter ligand", "Drug ligand", "Bound transmitter", "Bound drug", "Occupancy", "Activation"),
    (TRANSMITTER_COLOR, DRUG_COLOR, TRANSMITTER_BOUND_COLOR, DRUG_BOUND_COLOR, OCCUPANCY_COLOR, ACTIVATION_COLOR),
    y_label="Concentration / occupancy",
)
effector_plot = plot(
    "Effector state",
    (receptor._ref_activation, effector._ref_s, effector._ref_s_inf),
    ("Drive", "s", "s_inf"),
    (ACTIVATION_COLOR, EFFECTOR_S_COLOR, EFFECTOR_S_INF_COLOR),
    y_label="Signal", y_min=-0.05, y_max=1.2,
)
# The modulation readouts are plain Python floats (base / delta / effective value of
# the selected parameter), not NEURON refs, so this plot samples them per frame with
# line(read=...) rather than record_refs.
modulation = src.line(
    "Downstream parameter modulation",
    read={
        "Baseline value": lambda: float(runtime.downstream_target_base),
        "Added delta": lambda: float(runtime.downstream_target_delta),
        "Effective value": lambda: float(runtime.downstream_target_value),
    },
    x=lambda: float(h.t),
    x_label="Time",
    x_unit="ms",
    y_label="Selected parameter value",
    colors={
        "Baseline value": BASELINE_PARAM_COLOR,
        "Added delta": PARAM_DELTA_COLOR,
        "Effective value": EFFECTIVE_PARAM_COLOR,
    },
    background_color="white",
    rolling_window=ROLLING_WINDOW_MS,
    trim_to_rolling_window=True,
    max_refresh_hz=LINE_PLOT_MAX_REFRESH_HZ,
    x_major_tick_spacing=40.0,
    x_minor_tick_spacing=10.0,
)
downstream_voltage = plot(
    "Downstream HH voltage",
    (downstream.segment._ref_v,),
    ("Voltage",),
    (VOLTAGE_COLOR,),
    y_label="Voltage", y_unit="mV", show_legend=False, y_min=-90.0, y_max=60.0,
)


# --- controls -------------------------------------------------------------------
def set_upstream_clamp(value):
    upstream.clamp_amp = float(value)
    upstream.set_commanded_current(upstream.clamp_amp)


def set_runtime(attr, value, *, propagate=True):
    setattr(runtime, attr, float(value))
    if propagate:
        apply_runtime_parameters()


def set_mod_target(value):
    runtime.downstream_mod_target = str(value)
    apply_downstream_modulation()


def set_base(key, value):
    setattr(downstream_base, key, float(value))
    apply_downstream_modulation()


# (name, label, get, set, default, min, max, steps, scale, value_type)
# Defaults are the exploration's intended values, which differ from the raw mechanism
# defaults (e.g. effector tau_on 12 ms vs the mechanism's 5000 ms), so they are
# written into the model, not read out of it.
PHYSIOLOGY_CONTROLS = [
    ("celsius", "Temperature (degC)", lambda: runtime.celsius, lambda ctx, v: set_runtime("celsius", v), 6.3, 3.0, 37.0, 340, "linear", "float"),
    ("upstream_clamp_amp", "Upstream IClamp amplitude (nA)", lambda: upstream.clamp_amp, lambda ctx, v: set_upstream_clamp(v), 0.18, -0.05, 0.40, 225, "linear", "float"),
    ("pulse_event_weight", "Transmitter event weight (uM)", lambda: runtime.pulse_event_weight, lambda ctx, v: set_runtime("pulse_event_weight", v), 2.5, 0.0, 5.0, 250, "linear", "float"),
    ("pulse_threshold", "Spike detection threshold (mV)", lambda: runtime.pulse_threshold, lambda ctx, v: set_runtime("pulse_threshold", v), 0.0, -20.0, 20.0, 160, "linear", "float"),
    ("pulse_decay_rate", "Transmitter decay (/ms)", lambda: pulse_ligand.decay_rate, lambda ctx, v: setattr(pulse_ligand, "decay_rate", float(v)), 0.08, 0.001, 0.5, 200, "log", "float"),
    ("drug_external_input", "Drug external_input (uM/ms)", lambda: drug_ligand.external_input, lambda ctx, v: setattr(drug_ligand, "external_input", float(v)), 0.0, 0.0, 0.08, 200, "linear", "float"),
    ("drug_decay_rate", "Drug decay (/ms)", lambda: drug_ligand.decay_rate, lambda ctx, v: setattr(drug_ligand, "decay_rate", float(v)), 0.03, 0.001, 0.5, 200, "log", "float"),
    ("capacity", "Receptor capacity", lambda: receptor.capacity, lambda ctx, v: setattr(receptor, "capacity", float(v)), 1.0, 0.1, 2.0, 190, "linear", "float"),
    ("baseline_activity", "Receptor baseline_activity", lambda: receptor.baseline_activity, lambda ctx, v: setattr(receptor, "baseline_activity", float(v)), 0.0, 0.0, 1.0, 200, "linear", "float"),
    ("kd1", "Transmitter Kd (uM)", lambda: receptor.kd1, lambda ctx, v: setattr(receptor, "kd1", float(v)), 0.75, 0.01, 10.0, 200, "log", "float"),
    ("efficacy1", "Transmitter efficacy", lambda: receptor.efficacy1, lambda ctx, v: setattr(receptor, "efficacy1", float(v)), 1.0, -1.0, 2.0, 240, "linear", "float"),
    ("decay1", "Transmitter bound decay (/ms)", lambda: receptor.decay1, lambda ctx, v: setattr(receptor, "decay1", float(v)), 0.12, 0.001, 1.0, 200, "log", "float"),
    ("kd2", "Drug Kd (uM)", lambda: receptor.kd2, lambda ctx, v: setattr(receptor, "kd2", float(v)), 0.60, 0.01, 10.0, 200, "log", "float"),
    ("efficacy2", "Drug efficacy", lambda: receptor.efficacy2, lambda ctx, v: setattr(receptor, "efficacy2", float(v)), 0.0, -1.0, 2.0, 240, "linear", "float"),
    ("decay2", "Drug bound decay (/ms)", lambda: receptor.decay2, lambda ctx, v: setattr(receptor, "decay2", float(v)), 0.06, 0.001, 1.0, 200, "log", "float"),
    ("s_min", "Effector s_min", lambda: effector.s_min, lambda ctx, v: setattr(effector, "s_min", float(v)), 0.0, 0.0, 1.0, 100, "linear", "float"),
    ("s_max", "Effector s_max", lambda: effector.s_max, lambda ctx, v: setattr(effector, "s_max", float(v)), 1.0, 0.0, 2.0, 120, "linear", "float"),
    ("K", "Effector K", lambda: effector.K, lambda ctx, v: setattr(effector, "K", float(v)), 0.30, 0.01, 10.0, 200, "log", "float"),
    ("n", "Effector Hill coefficient n", lambda: effector.n, lambda ctx, v: setattr(effector, "n", int(round(float(v)))), 3, 1, 6, None, "linear", "int"),
    ("tau_on", "Effector tau_on (ms)", lambda: effector.tau_on, lambda ctx, v: setattr(effector, "tau_on", float(v)), 12.0, 1.0, 200.0, 200, "linear", "float"),
    ("tau_off", "Effector tau_off (ms)", lambda: effector.tau_off, lambda ctx, v: setattr(effector, "tau_off", float(v)), 45.0, 1.0, 300.0, 200, "linear", "float"),
    ("downstream_tonic_current", "Downstream tonic current (nA)", lambda: runtime.downstream_tonic_current, lambda ctx, v: set_runtime("downstream_tonic_current", v), 0.06, -0.05, 0.40, 225, "linear", "float"),
]

# modulation-strength slider + one baseline slider per downstream parameter
MODULATION_CONTROLS = [
    ("downstream_mod_strength", "Modulation strength (x per-target gain)", lambda: runtime.downstream_mod_strength, lambda ctx, v: set_runtime("downstream_mod_strength", v), 1.0, -2.0, 2.0, 200, "linear", "float"),
] + [
    (
        f"downstream_{spec.key}",
        spec.label,
        (lambda k=spec.key: getattr(downstream_base, k)),
        (lambda ctx, v, k=spec.key: set_base(k, v)),
        spec.default,
        spec.min_value,
        spec.max_value,
        spec.slider_steps,
        "linear",
        "float",
    )
    for spec in DOWNSTREAM_PARAMETER_SPECS
]

ALL_CONTROLS = PHYSIOLOGY_CONTROLS + MODULATION_CONTROLS

# Write the exploration defaults into the model before the run starts.
for _name, _label, _get, _set_fn, _default, *_rest in ALL_CONTROLS:
    _set_fn(None, _default)


def register(controls):
    for name, label, get, set_fn, default, min_value, max_value, steps, scale, value_type in controls:
        if value_type == "int":
            src.number(name, label=label, get=get, set=set_fn, default=default, min=min_value, max=max_value)
        else:
            src.slider(name, label=label, get=get, set=set_fn, default=default, min=min_value, max=max_value, steps=steps, scale=scale)


register(PHYSIOLOGY_CONTROLS)

src.dropdown(
    "downstream_mod_target",
    label="Downstream modulation target",
    get=lambda: runtime.downstream_mod_target,
    set=lambda ctx, v: set_mod_target(v),
    options=DOWNSTREAM_PARAMETER_KEYS,
    default=DEFAULT_MOD_TARGET,
)

register(MODULATION_CONTROLS)


def reset(ctx) -> None:
    apply_runtime_parameters()
    ctx.reset()


src.button("reset", label="Reset", fn=reset)

cnv.layout(
    (
        (competition, effector_plot),
        (upstream_voltage, modulation),
        (downstream_voltage, src.controls_panel),
    )
)

cnv.show(title=TITLE)
