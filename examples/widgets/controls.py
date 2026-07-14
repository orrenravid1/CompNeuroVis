"""Every control type, via its named call.

Nothing here is wired to a simulation: a control with no ``get``/``set`` simply
holds its own value in the frontend. The point is the vocabulary -- one call per
widget kind, with presentation refinements as inline kwargs:

    src.slider(...)                 float slider (scale="log", int=True for an int slider)
    src.number(...)                 integer spinbox
    src.checkbox(...)               boolean checkbox
    src.dropdown(...)               single-select dropdown
    src.text(...)                   text field
    src.xy_pad(...)                 2D draggable pad
    src.button(...) / src.hotkey(.) a push button / a key binding

Run: python examples/widgets/controls.py
"""

from __future__ import annotations

import compneurovis as cnv


src = cnv.source()

src.slider("float_slider", label="Float slider", min=0.0, max=1.0, default=0.35, steps=100)
src.number("int_spinbox", label="Int spinbox", min=1, max=32, default=4)
src.slider("int_slider", label="Int slider", min=1, max=64, default=8, steps=63, int=True)
src.checkbox("checkbox", label="Checkbox", default=True)
src.dropdown("dropdown", label="Dropdown", options=("fire", "bwr", "grayscale", "aquamarine"), default="aquamarine")
src.text("text", label="Text field", default="", placeholder="preset name", max_length=64)
src.xy_pad("xy_pad", label="XY pad", x=("g (Na)", 0.0, 1.0), y=("g (K)", 0.0, 1.0), default={"x": 0.3, "y": 0.7})

src.button("say_hello", label="Action button", fn=lambda ctx: ctx.show_status("Action button pressed", 2000))

cnv.layout(((src.controls_panel,),))

cnv.show(title="Control types")
