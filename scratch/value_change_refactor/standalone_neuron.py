"""Standalone NEURON backend smoke — proves the backend runtime works with NO
inline-source layer. Subclass NeuronBackend directly, provide sections, tick it,
assert it emits display + history fields."""
from neuron import h
from compneurovis.backends.neuron.backend import NeuronBackend, DisplayConfig
from compneurovis.core.messages import FieldReplace, FieldAppend, EntityClicked, command_message


class StandaloneNeuron(NeuronBackend):
    def build_sections(self):
        soma = h.Section(name="soma")
        soma.L = soma.diam = 12.6157
        soma.insert("hh")
        return [soma]


be = StandaloneNeuron(
    dt=0.025,
    display=DisplayConfig(ref_of=lambda seg: seg._ref_v, unit="mV"),
    history_enabled=True,
    history_capture_mode=NeuronBackend.HISTORY_CAPTURE_ON_DEMAND,
)
be.build_startup_data()   # builds the model + geometry (side effect)
be.initialize(None)       # standalone: no source, no view info

# on-demand history needs a selection; click the first segment
be.handle(command_message(EntityClicked(be.geometry.entity_ids[0])))
be.take_outbound_messages()

display_seen = history_seen = False
for _ in range(15):
    be.tick()
    for m in be.take_outbound_messages():
        p = m.payload
        if isinstance(p, FieldReplace) and p.field_id == be.display_field_id():
            display_seen = True
        if isinstance(p, FieldAppend) and p.field_id == be.history_field_id():
            history_seen = True

assert display_seen, "standalone backend never emitted a display field update"
assert history_seen, "standalone backend never emitted a history field update"
print("STANDALONE NEURON OK: display + history emitted with no source layer")
