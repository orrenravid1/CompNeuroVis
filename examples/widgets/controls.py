"""Every control type the controls panel can render.

Nothing here is wired to a simulation: a control with no ``get``/``set`` simply
holds its own value in the frontend. The point is the widget vocabulary --
which value spec produces which widget, and which presentation kinds each
value spec accepts.

    ScalarValueSpec(value_type="float")  kind="slider"
    ScalarValueSpec(value_type="int")    kind="spinbox"   (default)
    ScalarValueSpec(value_type="int")    kind="slider"
    BoolValueSpec                        kind="checkbox"
    ChoiceValueSpec                      kind="dropdown"
    TextValueSpec                        kind="text"
    XYValueSpec                          kind="xy_pad"
    action(...)                          a push button

A float slider also takes ``scale="log"``, which changes how the slider maps to
the value, not how it looks.

Run: python examples/widgets/controls.py
"""

from __future__ import annotations

import compneurovis as cnv


src = cnv.source()

src.control(
    "float_slider",
    label="Float slider",
    value_spec=cnv.ScalarValueSpec(default=0.35, min=0.0, max=1.0),
    presentation=cnv.ControlPresentationSpec(kind="slider", steps=100),
)
src.control(
    "int_spinbox",
    label="Int spinbox",
    value_spec=cnv.ScalarValueSpec(default=4, min=1, max=32, value_type="int"),
)
src.control(
    "int_slider",
    label="Int slider",
    value_spec=cnv.ScalarValueSpec(default=8, min=1, max=64, value_type="int"),
    presentation=cnv.ControlPresentationSpec(kind="slider", steps=63),
)
src.control(
    "checkbox",
    label="Checkbox",
    value_spec=cnv.BoolValueSpec(default=True),
)
src.control(
    "dropdown",
    label="Dropdown",
    value_spec=cnv.ChoiceValueSpec(default="aquamarine", options=("fire", "bwr", "grayscale", "aquamarine")),
)
src.control(
    "text",
    label="Text field",
    value_spec=cnv.TextValueSpec(default="", placeholder="preset name", max_length=64),
)
src.control(
    "xy_pad",
    label="XY pad",
    value_spec=cnv.XYValueSpec(
        default={"x": 0.3, "y": 0.7},
        x_range=(0.0, 1.0),
        y_range=(0.0, 1.0),
        x_label="g (Na)",
        y_label="g (K)",
    ),
    presentation=cnv.ControlPresentationSpec(kind="xy_pad"),
)

src.action("say_hello", label="Action button", fn=lambda ctx: ctx.show_status("Action button pressed", 2000))
src.action(
    "reset_fields",
    label="Action (resets fields)",
    fn=lambda ctx: ctx.show_status("Fields reset", 2000),
    resets_fields=True,
)

cnv.layout(((src.controls_panel,),))

cnv.show(title="Control types")
