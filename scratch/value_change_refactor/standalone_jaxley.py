"""Standalone Jaxley backend smoke — the backend runtime with NO source layer."""
import numpy as np
import jaxley as jx
from jaxley.channels import HH
from compneurovis.backends.jaxley.backend import JaxleyBackend
from compneurovis.core.messages import FieldReplace, FieldAppend, EntityClicked, command_message


class StandaloneJaxley(JaxleyBackend):
    def build_cells(self):
        comp = jx.Compartment()
        branch = jx.Branch(comp, ncomp=4)
        xyzr = [np.array([[0.0, 0.0, 0.0, 5.0], [40.0, 0.0, 0.0, 5.0]], dtype=np.float32)]
        cell = jx.Cell(branch, parents=[-1], xyzr=xyzr)
        return [cell]

    def setup_model(self, network, cells):
        network.insert(HH())


be = StandaloneJaxley(dt=0.025, v_init=-70.0, history_enabled=True)
be.build_startup_data()   # builds model + geometry
be.initialize(None)       # standalone: no source, no view info

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

assert display_seen, "standalone jaxley backend never emitted a display field update"
assert history_seen, "standalone jaxley backend never emitted a history field update"
print("STANDALONE JAXLEY OK: display + history emitted with no source layer")
