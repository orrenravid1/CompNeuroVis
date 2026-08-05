"""Built-in refresh contributions for the vispy frontend's view/operator kinds.

The refresh planner ships with **no** kind-specific knowledge. The built-in
surface/morphology view kinds and the grid-slice operator register their refresh
behaviour here, through the exact same public calls a third-party widget uses
(``register_view_refresh_schema`` / ``register_operator_refresh``) -- so a built-in
is not privileged over an extension in any way.

This module is intentionally light (pure data + spec-attribute logic, no
``vispy.scene``); the vispy frontend package imports it eagerly so that any use of
the frontend -- including planner-only unit tests -- has the built-ins registered.
"""

from __future__ import annotations

from compneurovis.core.operators import GridSliceOperatorSpec
from compneurovis.frontends.vispy.refresh_planning import (
    RefreshTarget,
    _binding_matches,
    _optional_ref,
    _ref,
    _value_key_matches,
    register_operator_refresh,
    register_view_refresh_schema,
)

# --- surface ------------------------------------------------------------------


def _surface_field_replace(
    target, view, view_id, field_ref, fragment_id, coords_changed
):
    """Surface's field-replace routing -- conditional, so a hook not a table.

    A replaced surface field always repaints the visual; it only rebuilds the axes
    geometry when the coordinates changed (or when auto color-limits must be
    recomputed from the new data).
    """
    targets: set = set()
    if _ref(view.field_id, fragment_id) == field_ref:
        targets.add(target("surface_visual", view_id))
        if coords_changed or view.color_limits is None:
            targets.add(target("surface_axes_geometry", view_id))
    return targets


register_view_refresh_schema(
    "surface",
    patch={
        "surface_visual":        frozenset({"field_id", "geometry_id", "max_refresh_hz"}),
        "surface_style":         frozenset({"color_map", "color_limits", "color_by",
                                            "surface_color", "surface_shading", "surface_alpha",
                                            "background_color"}),
        "surface_axes_geometry": frozenset({"field_id", "geometry_id", "render_axes",
                                            "axes_in_middle", "tick_count", "tick_length_scale",
                                            "axis_labels"}),
        "surface_axes_style":    frozenset({"tick_label_size", "axis_label_size",
                                            "axis_color", "text_color", "axis_alpha"}),
        "operator_overlay":      frozenset({"field_id", "geometry_id"}),
    },
    value_binding={
        "surface_visual":        frozenset({"field_id", "geometry_id"}),
        "surface_style":         frozenset({"color_map", "color_limits", "color_by",
                                            "surface_color", "surface_shading", "surface_alpha",
                                            "background_color"}),
        "surface_axes_geometry": frozenset({"render_axes", "axes_in_middle",
                                            "tick_count", "tick_length_scale"}),
        "surface_axes_style":    frozenset({"tick_label_size", "axis_label_size",
                                            "axis_color", "text_color", "axis_alpha"}),
    },
    full_refresh=("surface_visual", "surface_axes_geometry", "operator_overlay"),
    field_replace_hook=_surface_field_replace,
)

# --- morphology ---------------------------------------------------------------

register_view_refresh_schema(
    "morphology",
    patch={"morphology": None},
    value_binding={"morphology": frozenset({"background_color", "color_limits"})},
    full_refresh=("morphology",),
    field_id_props={"color_field_id": "morphology"},
)

# --- grid-slice operator ------------------------------------------------------


class _GridSliceOverlayContributor:
    """How a grid-slice operator contributes refresh targets to the surface it cuts.

    The operator draws its cut line as an overlay in the surface panel. It matches a
    surface view when its source field (and, if set, geometry) is the surface's, and
    routes the relevant change to an ``operator_overlay`` target for that view.
    """

    # Props that carry ValueBindingSpec references (live appearance of the cut line).
    _VALUE_BINDING_PROPS = frozenset({"color", "alpha", "fill_alpha", "width"})
    # Props whose change alters the operator's computed output (its sampled slice),
    # so a view consuming the operator as a data input must refresh.
    _COMPUTE_PROPS = frozenset({"field_id", "geometry_id",
                                "axis_value_key", "position_value_key"})

    def _geom_compatible(self, ctx) -> bool:
        return _optional_ref(ctx.op.geometry_id, ctx.op_ref.fragment_id) in {
            None,
            _optional_ref(getattr(ctx.view, "geometry_id", None), ctx.view_ref.fragment_id),
        }

    def _slices_view(self, ctx) -> bool:
        view_field = getattr(ctx.view, "field_id", None)
        if view_field is None:
            return False
        return (
            _ref(ctx.op.field_id, ctx.op_ref.fragment_id)
            == _ref(view_field, ctx.view_ref.fragment_id)
            and self._geom_compatible(ctx)
        )

    def on_value_change(self, ctx, value_key) -> set:
        if not self._slices_view(ctx):
            return set()
        op, frag = ctx.op, ctx.op_ref.fragment_id
        if (
            any(_binding_matches(getattr(op, p, None), value_key, frag) for p in self._VALUE_BINDING_PROPS)
            or _value_key_matches(op.axis_value_key, value_key, frag)
            or _value_key_matches(op.position_value_key, value_key, frag)
        ):
            return {RefreshTarget("operator_overlay", ctx.view_id)}
        return set()

    def on_field_replace(self, ctx, field_ref) -> set:
        # The overlay recomputes when the *replaced* field is the one the slice
        # samples (and its geometry matches this surface).
        if getattr(ctx.view, "field_id", None) is None:
            return set()
        if (
            _ref(ctx.op.field_id, ctx.op_ref.fragment_id) == field_ref
            and self._geom_compatible(ctx)
        ):
            return {RefreshTarget("operator_overlay", ctx.view_id)}
        return set()

    def on_operator_patch(self, ctx, changed_props) -> set:
        # Any patch to a slice that cuts this surface repaints its overlay.
        if self._slices_view(ctx):
            return {RefreshTarget("operator_overlay", ctx.view_id)}
        return set()

    def affects_output(self, changed_props) -> bool:
        return bool(changed_props & self._COMPUTE_PROPS)

    def output_field_deps(self, op, fragment_id) -> tuple:
        # A view consuming the slice as data depends on the field the slice samples.
        return (op.field_id,)

    def output_binds_value(self, op, value_key, fragment_id) -> bool:
        # The slice output tracks its axis/position controls.
        return _value_key_matches(op.axis_value_key, value_key, fragment_id) or _value_key_matches(
            op.position_value_key, value_key, fragment_id
        )


register_operator_refresh(GridSliceOperatorSpec, _GridSliceOverlayContributor())
