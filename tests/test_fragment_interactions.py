from __future__ import annotations

from compneurovis.core import (
    KeyBindingSpec,
    AppFragmentSpec,
    AppRef,
    AppSpec,
    ControlPresentationSpec,
    ControlSpec,
    ControlValueSpec,
    InteractionCatalog,
    KeySample,
    LayoutCatalog,
    LayoutSpec,
    PanelSpec,
    ValueBindingSpec,
)
from compneurovis.core.messages import ValueChange
from compneurovis.frontends.keyboard_routing import KeyboardRouter, ShortcutRecognizer
from compneurovis.frontends.vispy.frontend import VispyFrontendWindow


def _fragmented_interactions_app() -> AppSpec:
    def fragment(fragment_id: str) -> AppFragmentSpec:
        return AppFragmentSpec(
            id=fragment_id,
            interactions=InteractionCatalog(
                controls={
                    "gain_control": ControlSpec(
                        id="gain_control",
                        label=f"Gain {fragment_id}",
                        value_spec=ControlValueSpec(
                            kind="scalar",
                            default=0.0,
                        ),
                        presentation=ControlPresentationSpec(kind="number"),
                        value_key="gain",
                        send_to_backend=True,
                    )
                },
                key_bindings={
                    "apply": KeyBindingSpec(
                        id="apply",
                        shortcuts=("Ctrl+K",),
                        invokes="apply",
                        payload={"gain": ValueBindingSpec("gain")},
                    )
                }
            ),
        )

    panel = PanelSpec(
        id="actions",
        kind="controls",
        control_ids=(
            AppRef("gain_control", "left"),
            AppRef("gain_control", "right"),
        ),
    )
    return AppSpec(
        fragments={
            "left": fragment("left"),
            "right": fragment("right"),
        },
        layout_catalog=LayoutCatalog.single(
            LayoutSpec(
                panels=(panel,),
                panel_grid=((panel.id,),),
            )
        ),
    )


def test_one_shortcut_invokes_every_matching_scoped_action():
    app_spec = _fragmented_interactions_app()
    values = {
        AppRef("gain", "left"): 1.0,
        AppRef("gain", "right"): 2.0,
    }

    class Window:
        def __init__(self):
            self.app_spec = app_spec
            self.invoked = []
            self._keyboard_router = KeyboardRouter()
            self._shortcut_recognizer = ShortcutRecognizer()

        def value_snapshot(self):
            return values

        def _invoke_interaction(self, ref, payload):
            self.invoked.append((ref, payload))

        _shortcut_claims = VispyFrontendWindow._shortcut_claims
        _dispatch_key_claim = VispyFrontendWindow._dispatch_key_claim
        _route_key_sample = VispyFrontendWindow._route_key_sample

    window = Window()
    handled = window._route_key_sample(
        KeySample(phase="press", key="K", modifiers=("control",))
    )

    assert handled
    assert window.invoked == [
        (AppRef("apply", "left"), {"gain": 1.0}),
        (AppRef("apply", "right"), {"gain": 2.0}),
    ]


def test_unmatched_key_remains_available_to_frontend_defaults():
    app_spec = _fragmented_interactions_app()

    class Window:
        def __init__(self):
            self.app_spec = app_spec
            self._keyboard_router = KeyboardRouter()
            self._shortcut_recognizer = ShortcutRecognizer()

        _shortcut_claims = VispyFrontendWindow._shortcut_claims
        _dispatch_key_claim = VispyFrontendWindow._dispatch_key_claim
        _route_key_sample = VispyFrontendWindow._route_key_sample

    window = Window()
    assert not window._route_key_sample(
        KeySample(phase="press", key="J", modifiers=("control",))
    )


def test_fragment_controls_keep_local_specs_and_route_with_scoped_refs():
    app_spec = _fragmented_interactions_app()

    class ResolverWindow:
        def _active_layout(self):
            return app_spec.layout_catalog.active_layout()

    resolver = ResolverWindow()
    resolver.app_spec = app_spec
    controls = VispyFrontendWindow._resolved_controls(resolver, "actions")

    assert [
        (control.ref, control.value_ref, control.spec.id, control.spec.value_key)
        for control in controls
    ] == [
        (
            AppRef("gain_control", "left"),
            AppRef("gain", "left"),
            "gain_control",
            "gain",
        ),
        (
            AppRef("gain_control", "right"),
            AppRef("gain", "right"),
            "gain_control",
            "gain",
        ),
    ]

    observed = {"applied": [], "commands": [], "planned": [], "refreshed": []}

    class Planner:
        def targets_for_value_change(self, value_ref):
            observed["planned"].append(value_ref)
            return {"refresh"}

    class Window:
        refresh_planner = Planner()

        def _apply_frontend_value(self, value_ref, value):
            observed["applied"].append((value_ref, value))

        def _emit_command(self, command, *, tags=None):
            observed["commands"].append((command, tags))

        def _apply_refresh_targets(self, targets):
            observed["refreshed"].append(targets)

    VispyFrontendWindow._on_control_changed(Window(), controls[1], 2.5)

    assert observed["applied"] == [(AppRef("gain", "right"), 2.5)]
    assert observed["planned"] == [AppRef("gain", "right")]
    assert observed["refreshed"] == [{"refresh"}]
    command, tags = observed["commands"][0]
    assert isinstance(command, ValueChange)
    assert command.updates == {"gain": 2.5}
    assert tags == {"fragment_id": "right"}
