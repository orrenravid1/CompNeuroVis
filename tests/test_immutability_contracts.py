from __future__ import annotations

from dataclasses import dataclass, replace
import pickle

import numpy as np
import pytest

from compneurovis.backends.startup import StartupData
from compneurovis.core import (
    AppFragmentSpec,
    AppProjection,
    AppRef,
    AppSpec,
    DataCatalog,
    Field,
    FieldSpec,
    LayoutCatalog,
    LayoutSpec,
    PanelSpec,
    ValueBindingSpec,
    ViewCatalog,
    ViewSpec,
)
from compneurovis.core.controls import ActionSpec
from compneurovis.core.messages import (
    AppMetadataPatch,
    AppSpecDeclared,
    FieldReplace,
    MessageType,
    ValueChange,
    update_message,
)
from compneurovis.core.specs import SpecBase
from compneurovis.frontends.vispy.refresh_planning import RefreshPlanner


def _field_spec(field_id: str = "samples") -> FieldSpec:
    return FieldSpec(
        id=field_id,
        initial_values=np.asarray([1.0, 2.0]),
        dims=("sample",),
        coords={"sample": np.asarray([0.0, 1.0])},
    )


def test_canonical_properties_payloads_and_metadata_are_deeply_frozen():
    positions = np.asarray([[1.0, 2.0, 3.0]])
    properties = {
        "style": {"colors": ["red", "blue"]},
        "positions": positions,
        "selection": ValueBindingSpec("selected"),
    }
    action_payload = {
        "selection": ValueBindingSpec("selected"),
        "options": ["a", "b"],
    }
    metadata = {"nested": {"labels": ["one"]}}

    view = ViewSpec(id="points", kind="points", properties=properties)
    action = ActionSpec(id="inspect", label="Inspect", payload=action_payload)
    app = AppSpec(
        view_catalog=ViewCatalog(views={view.id: view}),
        metadata=metadata,
    )

    properties["style"]["colors"].append("green")
    positions[0, 0] = 99.0
    action_payload["options"].append("c")
    metadata["nested"]["labels"].append("two")

    assert view.properties["style"]["colors"] == ("red", "blue")
    assert view.properties["positions"][0, 0] == 1.0
    assert not view.properties["positions"].flags.writeable
    assert action.payload["options"] == ("a", "b")
    assert app.metadata["nested"]["labels"] == ("one",)
    with pytest.raises(TypeError):
        view.properties["style"]["new"] = True
    with pytest.raises(ValueError):
        view.properties["positions"][0, 0] = 4.0


def test_runtime_field_owns_read_only_values_coords_and_attrs():
    values = np.asarray([1.0, 2.0])
    coords = np.asarray([10.0, 20.0])
    attrs = {"schema": {"labels": ["a", "b"]}}

    field = Field(
        id="samples",
        values=values,
        dims=("sample",),
        coords={"sample": coords},
        attrs=attrs,
    )
    values[0] = 99.0
    coords[0] = 99.0
    attrs["schema"]["labels"].append("c")

    np.testing.assert_array_equal(field.values, [1.0, 2.0])
    np.testing.assert_array_equal(field.coords["sample"], [10.0, 20.0])
    assert field.attrs["schema"]["labels"] == ("a", "b")
    assert not field.values.flags.writeable
    assert not field.coords["sample"].flags.writeable
    with pytest.raises(TypeError):
        field.coords["other"] = np.asarray([])


def test_messages_snapshot_sender_owned_arrays_and_list_values():
    values = np.asarray([1.0, 2.0])
    coords = np.asarray([0.0, 1.0])
    attrs = {"nested": {"labels": ["a"]}}
    replacement = FieldReplace(
        field_id="samples",
        values=values,
        coords={"sample": coords},
        attrs_update=attrs,
    )
    selection = ["first"]
    nested = {"gain": 2.0}
    change = ValueChange({"selection": selection, "nested": nested})

    values[0] = 99.0
    coords[0] = 99.0
    attrs["nested"]["labels"].append("b")
    selection.append("second")
    nested["gain"] = 8.0

    np.testing.assert_array_equal(replacement.values, [1.0, 2.0])
    np.testing.assert_array_equal(replacement.coords["sample"], [0.0, 1.0])
    assert replacement.attrs_update["nested"]["labels"] == ["a"]
    assert change.updates == {
        "selection": ["first"],
        "nested": {"gain": 2.0},
    }
    with pytest.raises(TypeError):
        change.updates["selection"].append("forbidden")


def test_serialized_specs_and_messages_restore_read_only_arrays():
    app = AppSpec(data=DataCatalog(fields={"samples": _field_spec()}))
    declared = update_message(AppSpecDeclared(app))
    replacement = update_message(
        FieldReplace(field_id="samples", values=np.asarray([3.0, 4.0]))
    )

    restored_app = pickle.loads(pickle.dumps(declared)).payload.app_spec
    restored_replacement = pickle.loads(pickle.dumps(replacement)).payload

    assert not restored_app.data.fields["samples"].initial_values.flags.writeable
    assert not restored_replacement.values.flags.writeable
    with pytest.raises(ValueError):
        restored_replacement.values[0] = 9.0


def test_message_snapshot_preserves_default_fragment_catalog_aliases():
    app = AppSpec(data=DataCatalog(fields={"samples": _field_spec()}))

    snapshotted = ValueChange({"app": app}).updates["app"]

    assert (
        snapshotted.data.fields["samples"]
        is snapshotted.fragment("main").data.fields["samples"]
    )
    assert not snapshotted.data.fields["samples"].initial_values.flags.writeable


def test_object_arrays_and_mutable_spec_subclasses_cannot_cross_boundaries():
    with pytest.raises(TypeError, match="Object-dtype arrays"):
        FieldReplace(
            field_id="samples",
            values=np.asarray([[object()]], dtype=object),
        )

    class MutableSpec(SpecBase):
        def __init__(self) -> None:
            self.values = []

    with pytest.raises(TypeError, match="frozen dataclasses"):
        ValueChange({"unsafe": MutableSpec()})


def test_numpy_scalars_still_pass_through_the_scalar_whitelist():
    assert ValueChange({"gain": np.float32(2.5)}).updates["gain"] == pytest.approx(2.5)
    with pytest.raises(TypeError, match="message-safe"):
        ValueChange({"gain": np.complex64(1 + 2j)})


def test_message_type_owns_its_allowed_intents():
    intents = ["update"]
    message_type = MessageType(
        name="metadata_copy",
        payload_type=AppMetadataPatch,
        allowed_intents=intents,  # type: ignore[arg-type]
    )

    intents.append("command")

    assert message_type.allowed_intents == ("update",)
    with pytest.raises(ValueError, match="does not allow"):
        message_type.validate("command", AppMetadataPatch())


def test_catalog_keys_must_match_contained_spec_ids():
    with pytest.raises(ValueError, match="must match contained spec id"):
        DataCatalog(fields={"wrong": _field_spec("actual")})

    class MutableFieldDuck:
        id = "samples"

    with pytest.raises(TypeError, match="must be FieldSpec"):
        DataCatalog(fields={"samples": MutableFieldDuck()})


def test_package_owned_spec_subclasses_cannot_become_canonical_identity():
    @dataclass(frozen=True, slots=True)
    class VendorView(ViewSpec):
        vendor_setting: str = "private"

    vendor_view = VendorView(id="vendor", kind="vendor")

    with pytest.raises(TypeError, match="must be ViewSpec"):
        ViewCatalog(views={vendor_view.id: vendor_view})


def test_panel_and_view_host_kinds_are_non_empty_canonical_strings():
    assert PanelSpec(id="panel", kind=" custom ").kind == "custom"
    assert ViewSpec(id="view", kind="view", panel_kind=" custom ").panel_kind == "custom"
    with pytest.raises(ValueError, match="PanelSpec.kind"):
        PanelSpec(id="panel", kind="  ")
    with pytest.raises(ValueError, match="ViewSpec.panel_kind"):
        ViewSpec(id="view", kind="view", panel_kind="  ")


def test_fragment_scoped_ids_are_unqualified_and_unambiguous():
    with pytest.raises(ValueError, match="cannot contain ':'"):
        AppRef("field:other", "source")
    with pytest.raises(ValueError, match="surrounding whitespace"):
        AppRef(" field ", "source")
    with pytest.raises(ValueError, match="AppFragmentSpec.id"):
        AppFragmentSpec(id="source:other")
    with pytest.raises(ValueError, match="cannot contain ':'"):
        DataCatalog(fields={"samples:other": _field_spec("samples:other")})

    local_view = ViewSpec(id="trace", kind="line_plot")
    local_fragment = AppFragmentSpec(
        id="source",
        view_catalog=ViewCatalog(views={"trace": local_view}),
        layout_catalog=LayoutCatalog.single(
            LayoutSpec(
                panels=(
                    PanelSpec(
                        id="nested:panel",
                        kind="standalone",
                        view_ids=("trace",),
                    ),
                ),
                panel_grid=(("nested:panel",),),
            )
        ),
    )
    with pytest.raises(ValueError, match="local panel id"):
        AppSpec(fragments={"source": local_fragment})


def test_default_fragment_catalogs_remain_the_public_top_level_aliases():
    view = ViewSpec(id="trace", kind="line_plot", title="Before")
    app = AppSpec(view_catalog=ViewCatalog(views={view.id: view}))
    projection = AppProjection(app)

    projection.replace_view("trace", {"title": "After"})

    root_view = projection.spec.view_catalog.views["trace"]
    fragment_view = projection.spec.fragment("main").view_catalog.views["trace"]
    assert root_view is fragment_view
    assert root_view.title == "After"
    with pytest.raises(ValueError, match="must match contained spec id"):
        projection.replace_view("trace", {"id": "renamed"})

    relaid = replace(
        projection.spec,
        layout_catalog=LayoutCatalog.single(LayoutSpec(title="Relayout")),
    )
    assert relaid.fragment("main").view_catalog.views["trace"] is root_view
    assert relaid.layout_catalog.active_layout().title == "Relayout"


def test_independent_fragments_keep_same_local_ids_isolated():
    left = AppFragmentSpec(
        id="left",
        view_catalog=ViewCatalog(
            views={"trace": ViewSpec(id="trace", kind="line_plot", title="Left")}
        ),
    )
    right = AppFragmentSpec(
        id="right",
        view_catalog=ViewCatalog(
            views={"trace": ViewSpec(id="trace", kind="line_plot", title="Right")}
        ),
    )
    projection = AppProjection(AppSpec(fragments={"left": left, "right": right}))

    projection.replace_view(AppRef("trace", "left"), {"title": "Changed"})

    assert projection.spec.view(AppRef("trace", "left")).title == "Changed"
    assert projection.spec.view(AppRef("trace", "right")).title == "Right"
    assert not projection.spec.view_catalog.views


def test_fragment_layout_replacement_preserves_peer_source_panels():
    def fragment(fragment_id: str, title: str) -> AppFragmentSpec:
        view = ViewSpec(id="trace", kind="line_plot", title=title)
        panel = PanelSpec(
            id="trace-panel",
            kind=view.panel_kind,
            view_ids=(view.id,),
        )
        return AppFragmentSpec(
            id=fragment_id,
            view_catalog=ViewCatalog(views={view.id: view}),
            layout_catalog=LayoutCatalog.single(
                LayoutSpec(panels=(panel,), panel_grid=((panel.id,),))
            ),
        )

    left = fragment("left", "Left")
    right = fragment("right", "Right")
    shell = LayoutSpec(
        panels=(
            PanelSpec(
                id="left:trace-panel",
                kind="standalone",
                view_ids=(AppRef("trace", "left"),),
            ),
            PanelSpec(
                id="right:trace-panel",
                kind="standalone",
                view_ids=(AppRef("trace", "right"),),
            ),
        ),
        panel_grid=(("left:trace-panel",), ("right:trace-panel",)),
    )
    projection = AppProjection(
        AppSpec(
            fragments={"left": left, "right": right},
            layout_catalog=LayoutCatalog.single(shell),
        )
    )

    projection.replace_fragment_layout_panels(
        "left",
        (
            PanelSpec(
                id="renamed-panel",
                kind="standalone",
                view_ids=("trace",),
            ),
        ),
        (("renamed-panel",),),
    )

    assert tuple(panel.id for panel in projection.active_layout().panels) == (
        "left:renamed-panel",
        "right:trace-panel",
    )
    assert projection.active_layout().panel_grid == (
        ("left:renamed-panel",),
        ("right:trace-panel",),
    )
    assert (
        projection.spec.fragment("left").active_layout().panels[0].id
        == "renamed-panel"
    )
    assert (
        projection.spec.fragment("right").active_layout().panels[0].id
        == "trace-panel"
    )


def test_refresh_planner_reads_the_live_fragment_projection():
    first = _field_spec("first")
    second = _field_spec("second")
    view = ViewSpec(
        id="trace",
        kind="line_plot",
        inputs={"data": first.id},
    )
    layout = LayoutSpec(
        panels=(
            PanelSpec(
                id="trace-panel",
                kind=view.panel_kind,
                view_ids=(view.id,),
            ),
        ),
        panel_grid=(("trace-panel",),),
    )
    projection = AppProjection(
        AppSpec(
            data=DataCatalog(fields={first.id: first, second.id: second}),
            view_catalog=ViewCatalog(views={view.id: view}),
            layout_catalog=LayoutCatalog.single(layout),
        )
    )
    planner = RefreshPlanner(
        lambda: projection.spec,
        projection.active_layout,
    )

    assert planner.targets_for_field_replace(first.id)
    projection.replace_view("trace", {"inputs": {"data": second.id}})

    assert not planner.targets_for_field_replace(first.id)
    assert planner.targets_for_field_replace(second.id)


def test_metadata_patch_updates_the_live_app_spec():
    projection = AppProjection(AppSpec(metadata={"existing": {"value": 1}}))

    projection.patch_metadata(AppMetadataPatch({"added": ["safe"]}).updates)

    assert projection.metadata is projection.spec.metadata
    assert projection.spec.metadata == {
        "existing": {"value": 1},
        "added": ("safe",),
    }
    with pytest.raises(TypeError):
        projection.metadata["later"] = True


def test_startup_data_snapshots_collections_and_metadata():
    fields = [_field_spec()]
    metadata = {"nested": {"labels": ["a"]}}
    startup = StartupData(fields=fields, metadata=metadata)

    fields.clear()
    metadata["nested"]["labels"].append("b")

    assert len(startup.fields) == 1
    assert startup.metadata["nested"]["labels"] == ("a",)
