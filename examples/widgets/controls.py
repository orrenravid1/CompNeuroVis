"""Every control type, via its named call.

Nothing here is wired to a simulation: a control with no ``get``/``set`` simply
holds its own value in the frontend. The point is the vocabulary -- one call per
widget kind, with presentation refinements as inline kwargs:

    panel.slider(...)                 float slider (scale="log", int=True for an int slider)
    panel.number(...)                 integer spinbox
    panel.checkbox(...)               boolean checkbox
    panel.dropdown(...)               single-select dropdown
    panel.text(...)                   text field
    panel.xy_pad(...)                 2D draggable pad
    panel.button(...) / panel.hotkey(.) a push button / a key binding

Run: python examples/widgets/controls.py
"""

from __future__ import annotations

import compneurovis as cnv


src = cnv.source()
simulation = src.controls("Simulation")
display = src.controls("Display")

simulation.slider("float_slider", label="Float slider", min=0.0, max=1.0, default=0.35, steps=100)
simulation.number("int_spinbox", label="Int spinbox", min=1, max=32, default=4)
simulation.slider("int_slider", label="Int slider", min=1, max=64, default=8, steps=63, int=True)
simulation.xy_pad("xy_pad", label="XY pad", x=("g (Na)", 0.0, 1.0), y=("g (K)", 0.0, 1.0), default={"x": 0.3, "y": 0.7})

display.checkbox("checkbox", label="Checkbox", default=True)
display.dropdown("dropdown", label="Dropdown", options=("fire", "bwr", "grayscale", "aquamarine"), default="aquamarine")
display.text("text", label="Text field", default="", placeholder="preset name", max_length=64)
hello_hotkey = display.hotkey(
    "H", fn=lambda ctx: ctx.show_status("Action button pressed", 2000)
)
display.button("say_hello", label="Action button", hotkey=hello_hotkey)

cnv.layout(((simulation, display),))

cnv.show(title="Control types")
