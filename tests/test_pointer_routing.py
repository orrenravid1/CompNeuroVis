from __future__ import annotations

from dataclasses import dataclass

import compneurovis as cnv
import compneurovis.inline as inline
from compneurovis.core import AppRef, HitRecord, PointerEvent, PointerSample
from compneurovis.core.messages import PointerInteractionEvent, command_message
from compneurovis.frontends.pointer_routing import (
    ClickRecognizer,
    PointerClaim,
    PointerObservationHub,
    PointerRouter,
)


def _event(
    pointer_id: str,
    phase: str,
    *,
    role: str | None = "entities",
    x: float = 0.25,
) -> PointerEvent:
    return PointerEvent(
        sample=PointerSample(
            pointer_id=pointer_id,
            pointer_type="mouse",
            phase=phase,
            position=(x, 0.5),
            local_position=(x * 100.0, 50.0),
            button="primary" if phase in ("press", "release") else None,
            buttons=("primary",) if phase in ("press", "move") else (),
        ),
        hits=() if role is None else (HitRecord(role, f"primitive-{x}"),),
    )


def test_pointer_observation_is_non_claiming_and_unsubscribable():
    activity = []
    hub = PointerObservationHub(activity.append)
    observed = []
    unsubscribe = hub.subscribe(observed.append, needs_hits=True)

    assert hub.active
    assert hub.needs_hits
    assert activity == [True]
    event = _event("mouse", "move")
    hub.emit(event)
    assert observed == [event]

    unsubscribe()
    assert not hub.active
    assert not hub.needs_hits
    assert activity == [True, False]
    hub.emit(_event("mouse", "move", x=0.5))
    assert observed == [event]


def test_broken_pointer_observer_is_disabled_without_blocking_siblings(caplog):
    hub = PointerObservationHub()
    observed = []

    def broken(_event):
        raise RuntimeError("broken preview")

    hub.subscribe(broken, needs_hits=True)
    hub.subscribe(observed.append)
    first = _event("mouse", "move")
    second = _event("mouse", "move", x=0.5)

    hub.emit(first)
    hub.emit(second)

    assert observed == [first, second]
    assert "Pointer observer failed and was disabled" in caplog.text


def test_pointer_router_falls_through_without_a_claim_and_captures_per_pointer():
    router = PointerRouter()
    dispatched = []

    def resolve(event):
        hit = event.hits[0] if event.hits else None
        if hit is None:
            return None
        return PointerClaim(AppRef(f"owner-{event.sample.pointer_id}"), hit.target_role)

    assert not router.route(
        _event("background", "press", role=None),
        resolve_claim=resolve,
        dispatch=lambda *args: dispatched.append(args),
    )
    assert not router.is_captured("background")

    assert router.route(
        _event("a", "press"),
        resolve_claim=resolve,
        dispatch=lambda *args: dispatched.append(args),
    )
    assert router.route(
        _event("b", "press", x=0.75),
        resolve_claim=resolve,
        dispatch=lambda *args: dispatched.append(args),
    )
    assert router.is_captured("a")
    assert router.is_captured("b")

    # Ownership is stable even when a captured move has no current hit.
    assert router.route(
        _event("a", "move", role=None, x=0.4),
        resolve_claim=resolve,
        dispatch=lambda *args: dispatched.append(args),
    )
    assert router.route(
        _event("a", "release", role=None, x=0.4),
        resolve_claim=resolve,
        dispatch=lambda *args: dispatched.append(args),
    )
    assert not router.is_captured("a")
    assert router.is_captured("b")
    assert [event.sample.phase for _, event in dispatched] == [
        "press",
        "press",
        "move",
        "release",
    ]


def test_pointer_router_cancels_live_owners_without_geometry_or_camera_policy():
    router = PointerRouter()
    dispatched = []
    event = _event("pen-4", "press")
    claim = PointerClaim(AppRef("paint", "source2"), "entities")
    assert router.route(
        event,
        resolve_claim=lambda _event: claim,
        dispatch=lambda *args: dispatched.append(args),
    )
    router.cancel_all(lambda *args: dispatched.append(args))
    assert not router.is_captured("pen-4")
    assert dispatched[-1][0] == claim
    assert dispatched[-1][1].sample.phase == "cancel"
    assert dispatched[-1][1].hits == event.hits


def test_click_is_a_derived_pointer_gesture():
    recognizer = ClickRecognizer(max_distance=5.0)
    press = _event("mouse", "press", x=0.10)
    release = _event("mouse", "release", x=0.13)
    assert recognizer.feed(press) is None
    assert recognizer.feed(_event("mouse", "move", x=0.13)) is None
    click = recognizer.feed(release)
    assert click is not None
    assert click.press is press
    assert click.release is release

    assert recognizer.feed(_event("mouse", "press", x=0.10)) is None
    assert recognizer.feed(_event("mouse", "release", x=0.20)) is None


def test_widget_can_author_a_pointer_target_without_authoring_a_click():
    observed = []

    @dataclass(frozen=True, slots=True)
    class PointerOnly(cnv.Widget):
        def declare(self, context):
            geometry = context.geometry(
                "test_geometry",
                "pointer geometry",
                data={"entity_ids": ("one",)},
                metadata={"entities": {"one": {"owner": "pointer"}}},
            )
            unrelated = context.geometry(
                "test_geometry",
                "selection geometry",
                data={"entity_ids": ("one",)},
                metadata={"entities": {"one": {"owner": "selection"}}},
            )
            context.selection("unrelated", geometry=unrelated, initial="one")
            target = context.hit_target("pointer geometry")
            pointer = context.entity_pointer(
                "pointer stream",
                hit_target=target,
                geometry=geometry,
            )
            context.on_entity_pointer(
                pointer,
                lambda ctx, event: observed.append(
                    ctx.entity_info(event.value)["owner"]
                ),
            )
            panel = context.view(
                "pointer_only_view",
                "Pointer only",
                geometries={"entities": geometry},
                hit_targets={"entities": target},
            )
            return panel, pointer

    inline._reset_authoring_app()
    try:
        source = cnv.source()
        source.add(PointerOnly())
        app = source._build_app_spec_for_backend(source._make_backend())
        target_ref, target = next(app.iter_hit_targets())
        pointer_ref, pointer = next(app.iter_pointer_interactions())
        view_ref, view = next(app.iter_view_specs())

        assert not app.interactions.clicks
        assert pointer.hit_target_id == target_ref.id
        assert view.hit_targets["entities"] == target_ref.id
        assert pointer_ref.fragment_id == view_ref.fragment_id
        assert pointer.result_kind == "entity"
        assert pointer.geometry_scope_id == view.geometries["entities"]

        backend = source._make_backend()
        backend.initialize(app)
        backend.take_outbound_messages()
        backend.handle(
            command_message(
                PointerInteractionEvent(
                    interaction_id=pointer_ref.id,
                    pointer=_event("mouse", "press"),
                    value="one",
                )
            )
        )
        assert observed == ["pointer"]
    finally:
        inline._reset_authoring_app()


def test_generic_pointer_interaction_needs_no_geometry_or_entity_contract():
    observed = []

    @dataclass(frozen=True, slots=True)
    class SurfaceBrush(cnv.Widget):
        def declare(self, context):
            target = context.hit_target("surface")
            selected = context.selection(
                "surface point",
                hit_target=target,
                item_kind="point2",
                initial=(0.25, 0.5),
            )
            pointer = context.pointer("brush", hit_target=target)
            context.on_pointer(
                pointer,
                lambda _ctx, event: observed.append(event.value),
            )
            panel = context.view(
                "test_surface",
                "Surface",
                hit_targets={"surface": target},
                selections={"surface": selected},
            )
            return panel, pointer

    inline._reset_authoring_app()
    try:
        source = cnv.source()
        source.add(SurfaceBrush())
        app = source._build_app_spec_for_backend(source._make_backend())
        pointer_ref, pointer = next(app.iter_pointer_interactions())

        assert not app.data.geometries
        assert pointer.result_kind == "hit"
        assert pointer.geometry_scope_id is None
        selection = next(iter(app.interactions.selections.values()))
        assert selection.initial == ((0.25, 0.5),)

        backend = source._make_backend()
        backend.initialize(app)
        backend.take_outbound_messages()
        value = cnv.HitValue(
            primitive_id=7,
            world_position=(1.0, 2.0, 3.0),
        )
        backend.handle(
            command_message(
                PointerInteractionEvent(
                    interaction_id=pointer_ref.id,
                    pointer=_event("mouse", "press", role="surface"),
                    value=value,
                )
            )
        )
        assert observed == [value]
    finally:
        inline._reset_authoring_app()


def test_visual_contribution_can_own_pointer_hit_target():
    @dataclass(frozen=True, slots=True)
    class ContributionBrush(cnv.Widget):
        def declare(self, context):
            panel = context.view("test_surface", "Surface")
            target = context.hit_target("brush overlap")
            context.visual_contribution(
                "test_brush_preview",
                "Brush preview",
                target=panel,
                capability="scene3d.layers/v1",
                hit_targets={"brush": target},
            )
            pointer = context.pointer("brush", hit_target=target)
            return panel, pointer

    inline._reset_authoring_app()
    try:
        source = cnv.source()
        source.add(ContributionBrush())
        app = source._build_app_spec_for_backend(source._make_backend())
        view_ref, _view = next(app.iter_view_specs())

        class Window:
            app_spec = app

            def _active_layout(self):
                return app.layout_catalog.active_layout()

            def value_snapshot(self):
                return {}

        from compneurovis.frontends.vispy.frontend import VispyFrontendWindow

        claim = VispyFrontendWindow._resolve_pointer_interaction(
            Window(), view_ref, "brush", "primary"
        )
        assert claim is not None
        assert claim.target_role == "brush"
        assert claim.result_kind == "hit"
    finally:
        inline._reset_authoring_app()
