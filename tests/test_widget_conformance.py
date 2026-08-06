from __future__ import annotations

import importlib
import importlib.metadata
import shutil
import site
import subprocess
import sys
from multiprocessing.reduction import ForkingPickler
from pathlib import Path

import numpy as np
import pytest

import compneurovis as cnv
import compneurovis.inline as inline


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples" / "extensions" / "cnv_pointcloud_demo"


def _lower(source):
    source._panel_grid = inline._app._panel_grid
    backend = source._make_backend()
    return source._build_app_spec_for_backend(backend)


def test_pointcloud_fixture_respects_public_import_boundary():
    package = FIXTURE / "src" / "cnv_pointcloud_demo"
    for path in package.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "compneurovis.inline" not in source
        assert "compneurovis.core" not in source
        assert "compneurovis.frontends.vispy." not in source


def test_installed_pointcloud_fixture_lowers_headless_and_discovers_plugin(
    tmp_path,
):
    fixture_copy = tmp_path / "fixture"
    shutil.copytree(FIXTURE, fixture_copy)
    target = tmp_path / "site"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-deps",
            "--no-build-isolation",
            "--target",
            str(target),
            str(fixture_copy),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    site.addsitedir(str(target))
    importlib.invalidate_caches()

    distributions = tuple(importlib.metadata.distributions(path=[str(target)]))
    distribution = next(
        item for item in distributions if item.metadata["Name"] == "cnv-pointcloud-demo"
    )
    plugin = next(
        item
        for item in distribution.entry_points
        if item.group == "compneurovis.vispy_plugins"
    )
    assert plugin.name == "pointcloud"

    pointcloud = importlib.import_module("cnv_pointcloud_demo")
    assert "cnv_pointcloud_demo.vispy" not in sys.modules

    inline._reset_inline_session()
    source = cnv.source()
    cloud = source.add(
        pointcloud.PointCloud3D(
            "External cloud",
            positions=np.array(
                [
                    [0.0, 0.0, 0.0],
                    [1.0, 0.5, 0.25],
                    [2.0, 1.0, 0.5],
                ],
                dtype=np.float32,
            ),
            values=np.array([0.1, 0.5, 0.9], dtype=np.float32),
        )
    )
    cnv.layout(((cloud,),))
    app = _lower(source)

    geometry = next(iter(app.data.geometries.values()))
    view = next(iter(app.view_catalog.views.values()))
    assert isinstance(geometry, cnv.ExtensionGeometrySpec)
    assert geometry.kind == "point_cloud"
    assert isinstance(view, cnv.ExtensionViewSpec)
    assert view.kind == "point_cloud_3d"
    assert view.geometries["points"] == geometry.id
    transported = ForkingPickler.loads(ForkingPickler.dumps(app))
    assert isinstance(
        next(iter(transported.data.geometries.values())),
        cnv.ExtensionGeometrySpec,
    )
    assert "cnv_pointcloud_demo.vispy" not in sys.modules

    from compneurovis.frontends.vispy import (
        load_vispy_plugins,
        register_3d_visual,
    )
    from compneurovis.frontends.vispy.view3d.visuals import (
        create_3d_visuals,
        visual_key_for_target,
    )

    load_vispy_plugins()
    assert "cnv_pointcloud_demo.vispy" in sys.modules
    assert visual_key_for_target("point_cloud_3d") == "point_cloud_3d"

    constructed: list[str] = []

    def first_factory(view, *, panel_id=None):
        del view, panel_id
        constructed.append("first")
        return object()

    def second_factory(view, *, panel_id=None):
        del view, panel_id
        constructed.append("second")
        return object()

    register_3d_visual(
        "conformance_first",
        first_factory,
        targets=("conformance_first_target",),
    )
    register_3d_visual(
        "conformance_second",
        second_factory,
        targets=("conformance_second_target",),
    )
    created = create_3d_visuals(
        object(),
        kind="conformance_first",
        panel_id="fixture-panel",
    )
    assert tuple(created) == ("conformance_first",)
    assert constructed == ["first"]

    with pytest.raises(ValueError, match="already owned"):
        register_3d_visual(
            "conformance_collision",
            second_factory,
            targets=("conformance_first_target",),
        )
    with pytest.raises(LookupError, match="No Vispy 3-D visual"):
        create_3d_visuals(object(), kind="conformance_missing")
