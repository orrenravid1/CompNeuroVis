from __future__ import annotations

from compneurovis.core import (
    ActionSpec,
    AppFragmentSpec,
    AppRef,
    AppSpec,
    ControlPresentationSpec,
    ControlSpec,
    ControlValueSpec,
    InteractionCatalog,
    LayoutCatalog,
    LayoutSpec,
    PanelSpec,
    ValueBindingSpec,
)
from compneurovis.core.messages import KeyPressed, ValueChange
from compneurovis.frontends.vispy.controls.panel import ControlsPanel
from compneurovis.frontends.vispy.frontend import VispyFrontendWindow
from compneurovis.frontends.vispy.registries.controls import (
    ResolvedAction,
)


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
                actions={
                    "apply": ActionSpec(
                        id="apply",
                        label=f"Apply {fragment_id}",
                        payload={"gain": ValueBindingSpec("gain")},
                        shortcuts=("Ctrl+K",),
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
        action_ids=(AppRef("apply", "left"), AppRef("apply", "right")),
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


def test_control_panel_resolves_action_payload_in_the_actions_fragment():
    app_spec = _fragmented_interactions_app()

    class Window:
        def _active_layout(self):
            return app_spec.layout_catalog.active_layout()

    window = Window()
    window.app_spec = app_spec
    _, actions = VispyFrontendWindow._resolved_controls_and_actions(
        window, "actions"
    )
    values = {
        "gain": "unscoped",
        AppRef("gain", "left"): 1.0,
        AppRef("gain", "right"): 2.0,
    }
    observed = []
    panel = type(
        "Panel",
        (),
        {"on_action_invoked": lambda self, action, payload: observed.append(
            (action.ref, payload)
        )},
    )()

    for action in actions:
        ControlsPanel._invoke_action(panel, action, values)

    assert observed == [
        (AppRef("apply", "left"), {"gain": 1.0}),
        (AppRef("apply", "right"), {"gain": 2.0}),
    ]


def test_interaction_target_receives_the_scoped_action_reference():
    action_ref = AppRef("apply", "right")
    observed = []

    class Target:
        def on_action(self, action_id, payload, context):
            observed.append((action_id, payload, context))
            return True

    context = object()

    class Window:
        interaction_target = Target()

        def _interaction_context(self):
            return context

        _invoke_interaction_action = VispyFrontendWindow._invoke_interaction_action

        def _toggle_selection_action_mode(self, action):
            raise AssertionError(f"consumed action was toggled: {action}")

        def _send_action(self, action, payload):
            raise AssertionError(f"consumed action was sent: {action}, {payload}")

    action = ResolvedAction(
        ref=action_ref,
        spec=_fragmented_interactions_app().action(action_ref),
    )
    VispyFrontendWindow._on_action_invoked(Window(), action, {"gain": 2.0})

    assert observed == [(action_ref, {"gain": 2.0}, context)]


def test_one_shortcut_invokes_every_matching_scoped_action():
    app_spec = _fragmented_interactions_app()
    values = {
        AppRef("gain", "left"): 1.0,
        AppRef("gain", "right"): 2.0,
    }

    class Event:
        accepted = False

        def accept(self):
            self.accepted = True

    class Window:
        def __init__(self):
            self.app_spec = app_spec
            self.invoked = []
            self.emitted = []

        def _event_key_text(self, event):
            del event
            return "Ctrl+K"

        def _invoke_interaction_key_press(self, key):
            del key
            return False

        def value_snapshot(self):
            return values

        def _on_action_invoked(self, action, payload):
            self.invoked.append((action.ref, payload))

        def _emit_command(self, command):
            self.emitted.append(command)

        _actions_for_event = VispyFrontendWindow._actions_for_event

    event = Event()
    window = Window()
    VispyFrontendWindow.keyPressEvent(window, event)

    assert event.accepted
    assert window.invoked == [
        (AppRef("apply", "left"), {"gain": 1.0}),
        (AppRef("apply", "right"), {"gain": 2.0}),
    ]
    assert window.emitted == []


def test_unmatched_shortcut_keeps_the_raw_key_fallback():
    app_spec = _fragmented_interactions_app()

    class Event:
        accepted = False

        def accept(self):
            self.accepted = True

    class Window:
        def __init__(self):
            self.app_spec = app_spec
            self.emitted = []

        def _event_key_text(self, event):
            del event
            return "Ctrl+J"

        def _invoke_interaction_key_press(self, key):
            del key
            return False

        def _emit_command(self, command):
            self.emitted.append(command)

        _actions_for_event = VispyFrontendWindow._actions_for_event

    event = Event()
    window = Window()
    VispyFrontendWindow.keyPressEvent(window, event)

    assert event.accepted
    assert len(window.emitted) == 1
    assert isinstance(window.emitted[0], KeyPressed)
    assert window.emitted[0].key == "Ctrl+J"


def test_fragment_controls_keep_local_specs_and_route_with_scoped_refs():
    app_spec = _fragmented_interactions_app()

    class ResolverWindow:
        def _active_layout(self):
            return app_spec.layout_catalog.active_layout()

    resolver = ResolverWindow()
    resolver.app_spec = app_spec
    controls, _ = VispyFrontendWindow._resolved_controls_and_actions(
        resolver, "actions"
    )

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
