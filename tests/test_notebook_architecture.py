from __future__ import annotations

from pathlib import Path

import pytest

from compneurovis._source_runtime import SourceRunPlan
from compneurovis.core import AppSpec
from compneurovis.core.run_spec import MessageMatch, RouteSpec, RoutingSpec
from compneurovis.core.runtime.actor import ActorBase
from compneurovis.frontends.vispy.notebook.registries import (
    control_renderer,
    register_control_renderer,
)
from compneurovis.frontends.vispy.notebook.runtime import (
    NotebookRuntimeOptions,
    build_builder_run_spec,
    build_source_run_spec,
)


ROOT = Path(__file__).resolve().parents[1]


def test_notebook_runtime_uses_one_generic_renderer_actor():
    routing = RoutingSpec(
        routes=(
            RouteSpec(
                match=MessageMatch(intent="command"),
                targets=("backend",),
            ),
            RouteSpec(
                match=MessageMatch(intent="update"),
                targets=("frontend",),
            ),
        )
    )
    plan = SourceRunPlan(backend=ActorBase(), app_spec=AppSpec(), routing=routing)

    run_spec = build_source_run_spec(
        plan,
        options=NotebookRuntimeOptions(backend_process=False),
    )

    assert tuple(actor.id for actor in run_spec.actors) == (
        "backend",
        "renderer",
        "frontend",
    )
    field_route = next(
        route
        for route in run_spec.routing.routes
        if route.match.message_type == "field_replace"
    )
    assert field_route.targets == ("renderer",)


def test_notebook_builder_uses_the_same_generic_frontend_topology():
    run_spec = build_builder_run_spec(lambda: None)

    assert tuple(actor.id for actor in run_spec.actors) == (
        "backend",
        "renderer",
        "frontend",
    )
    update_route = next(
        route
        for route in run_spec.routing.routes
        if route.match.message_type == "app_spec_declared"
    )
    assert update_route.targets == ("frontend", "renderer")


def test_notebook_in_kernel_rendering_remains_explicitly_selectable():
    routing = RoutingSpec(
        routes=(
            RouteSpec(
                match=MessageMatch(intent="command"),
                targets=("backend",),
            ),
            RouteSpec(
                match=MessageMatch(intent="update"),
                targets=("frontend",),
            ),
        )
    )
    plan = SourceRunPlan(backend=ActorBase(), app_spec=AppSpec(), routing=routing)

    run_spec = build_source_run_spec(
        plan,
        options=NotebookRuntimeOptions(render_process=False),
    )

    assert tuple(actor.id for actor in run_spec.actors) == (
        "backend",
        "frontend",
    )
    assert run_spec.routing == routing


def test_notebook_builder_requires_its_declared_subprocess_placement():
    with pytest.raises(ValueError, match="backend subprocess"):
        build_builder_run_spec(
            lambda: None,
            options=NotebookRuntimeOptions(backend_process=False),
        )


def test_notebook_control_presentations_have_an_open_collision_safe_registry():
    kind = "notebook_test_control"

    def first(context, control, current):
        del context, control, current
        return None

    def second(context, control, current):
        del context, control, current
        return None

    register_control_renderer(kind, first)

    assert control_renderer(kind) is first
    with pytest.raises(ValueError, match="already registered"):
        register_control_renderer(kind, second)


def test_notebook_package_contains_no_widget_kind_or_environment_topology_branch():
    notebook = ROOT / "src" / "compneurovis" / "frontends" / "vispy" / "notebook"
    source_runtime = (
        ROOT / "src" / "compneurovis" / "_source_runtime.py"
    ).read_text(encoding="utf-8")
    implementation = "\n".join(
        path.read_text(encoding="utf-8")
        for path in notebook.glob("*.py")
    )

    assert "NotebookMorphologyRenderActor" not in implementation
    assert "NotebookLinePlotRenderActor" not in implementation
    assert "CNV_NOTEBOOK_" not in implementation
    assert 'use(app="pyqt6", gl="gl+")' in implementation
    assert "line_plot_renderer" not in source_runtime
    assert "morphology_process" not in source_runtime


def test_external_notebook_shell_does_not_mount_a_second_panel_graph():
    implementation = (
        ROOT
        / "src"
        / "compneurovis"
        / "frontends"
        / "vispy"
        / "notebook"
        / "frontend.py"
    ).read_text(encoding="utf-8")

    assert "mount_panels=not self._external_frames" in implementation
    assert "if not self._external_frames:\n            _configure_notebook_vispy_backend()" in implementation
