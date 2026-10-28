from __future__ import annotations

import numpy as np
import pytest

from compneurovis.core import (
    AppProjection,
    AppSpec,
    DataCatalog,
    Field,
    FieldSpec,
    GeometrySpec,
    InteractionCatalog,
    LayoutCatalog,
    LayoutSpec,
    OperatorSpec,
    PanelSpec,
    SelectionSpec,
    ValueBindingSpec,
    ViewCatalog,
    ViewSpec,
    VisualContributionSpec,
    app_ref,
)
from compneurovis.frontends.vispy.frontend import VispyFrontendWindow
from compneurovis.frontends.vispy.refresh_planning import RefreshPlanner
from compneurovis.frontends.vispy.registries.operators import (
    _OPERATOR_ADAPTERS,
    operator_adapter,
    register_operator_adapter,
)


def test_app_spec_rejects_operator_cycles() -> None:
    first = OperatorSpec(
        id="first",
        kind="cycle_fixture",
        inputs={"source": "second"},
    )
    second = OperatorSpec(
        id="second",
        kind="cycle_fixture",
        inputs={"source": "first"},
    )

    with pytest.raises(
        ValueError,
        match=r"Operator dependency cycle: .*first.*second.*first",
    ):
        AppSpec(
            view_catalog=ViewCatalog(
                operators={first.id: first, second.id: second},
            )
        )


def test_visual_contribution_selection_must_belong_to_declared_geometry() -> None:
    selected_geometry = GeometrySpec(id="selected", kind="point_cloud")
    rendered_geometry = GeometrySpec(id="rendered", kind="point_cloud")
    selection = SelectionSpec(
        id="points",
        target_id=selected_geometry.id,
    )
    contribution = VisualContributionSpec(
        id="overlay",
        kind="selection_overlay",
        capability="scene_layer",
        geometries={"points": rendered_geometry.id},
        selections={"points": selection.id},
    )

    with pytest.raises(
        ValueError,
        match="which the contribution does not declare",
    ):
        AppSpec(
            data=DataCatalog(
                geometries={
                    selected_geometry.id: selected_geometry,
                    rendered_geometry.id: rendered_geometry,
                }
            ),
            view_catalog=ViewCatalog(
                contributions={contribution.id: contribution},
            ),
            interactions=InteractionCatalog(
                selections={selection.id: selection},
            ),
        )


class _ScaleAdapter:
    @staticmethod
    def affects_output(changed_props: set[str]) -> bool:
        return "factor" in changed_props

    @staticmethod
    def output_field_deps(operator, fragment_id):
        del fragment_id
        return tuple(operator.inputs.values())

    @staticmethod
    def output_binds_value(operator, value_key, fragment_id) -> bool:
        factor = operator.properties.get("factor")
        if not isinstance(factor, ValueBindingSpec):
            return False
        return app_ref(
            factor.key,
            fragment_id=fragment_id,
        ) == app_ref(value_key)

    @staticmethod
    def resolve_field(operator, context):
        source = context.field(operator.inputs["source"])
        factor = operator.properties["factor"]
        if isinstance(factor, ValueBindingSpec):
            factor = context.values[factor.key]
        return Field(
            id=operator.id,
            values=np.asarray(source.values) * float(factor),
            dims=source.dims,
            coords=dict(source.coords),
            unit=source.unit,
            attrs=dict(source.attrs),
        )


def test_operator_adapter_contract_is_validated_and_missing_kinds_are_explicit():
    with pytest.raises(TypeError, match="resolve_field"):
        register_operator_adapter("incomplete_adapter_fixture", object())

    operator = OperatorSpec(
        id="missing",
        kind="missing_adapter_fixture",
    )
    with pytest.raises(LookupError, match="missing_adapter_fixture"):
        operator_adapter(operator)


def _operator_chain_app() -> AppSpec:
    raw = FieldSpec(
        id="raw",
        initial_values=np.asarray([1.0, 2.0], dtype=np.float32),
        dims=("sample",),
        coords={"sample": np.asarray(("a", "b"))},
    )
    inner = OperatorSpec(
        id="inner",
        kind="scale_chain_fixture",
        inputs={"source": raw.id},
        properties={"factor": ValueBindingSpec("gain")},
    )
    outer = OperatorSpec(
        id="outer",
        kind="scale_chain_fixture",
        inputs={"source": inner.id},
        properties={"factor": 3.0},
    )
    view = ViewSpec(
        id="derived-view",
        kind="operator_chain_view",
        inputs={"data": outer.id},
    )
    contribution = VisualContributionSpec(
        id="derived-overlay",
        kind="operator_chain_overlay",
        capability="scene_layer",
        inputs={"data": outer.id},
    )
    panel = PanelSpec(
        id="derived-panel",
        kind="standalone",
        view_ids=(view.id,),
        contribution_ids=(contribution.id,),
    )
    return AppSpec(
        data=DataCatalog(fields={raw.id: raw}),
        view_catalog=ViewCatalog(
            views={view.id: view},
            operators={inner.id: inner, outer.id: outer},
            contributions={contribution.id: contribution},
        ),
        layout_catalog=LayoutCatalog.single(
            LayoutSpec(
                panels=(panel,),
                panel_grid=((panel.id,),),
            )
        ),
    )


def test_vispy_resolves_chained_operator_inputs_recursively() -> None:
    adapter = _ScaleAdapter()
    register_operator_adapter("scale_chain_fixture", adapter)
    try:
        app = _operator_chain_app()

        class _FrontendFixture:
            _resolve_view_input = VispyFrontendWindow._resolve_view_input

            def __init__(self):
                self.app_spec = app
                self.app_projection = AppProjection(app)

            def _field(self, field_id, *, fragment_id):
                return self.app_projection.field(
                    field_id,
                    fragment_id=fragment_id,
                )

        resolved = _FrontendFixture()._resolve_view_input(
            "outer",
            "main",
            {"gain": 2.0},
        )
        np.testing.assert_allclose(resolved.values, [6.0, 12.0])
    finally:
        _OPERATOR_ADAPTERS.pop("scale_chain_fixture", None)


def test_refresh_planner_tracks_transitive_operator_dependencies() -> None:
    adapter = _ScaleAdapter()
    register_operator_adapter("scale_chain_fixture", adapter)
    try:
        app = _operator_chain_app()
        planner = RefreshPlanner(app, app.layout_catalog.active_layout)

        for targets in (
            planner.targets_for_field_replace("raw"),
            planner.targets_for_value_change("gain"),
            planner.targets_for_operator_patch("inner", {"factor"}),
        ):
            assert any(
                target.kind == "view"
                and str(target.view_id) == "derived-view"
                for target in targets
            )
            assert any(
                target.kind == "visual_contribution"
                and str(target.contribution_id) == "derived-overlay"
                for target in targets
            )

        assert not planner.targets_for_operator_patch(
            "inner",
            {"display_only"},
        )
    finally:
        _OPERATOR_ADAPTERS.pop("scale_chain_fixture", None)
