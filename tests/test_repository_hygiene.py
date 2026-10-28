from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _python_and_markdown_files(root: Path):
    yield from root.rglob("*.py")
    yield from root.rglob("*.md")


def test_retired_widget_taxonomy_does_not_return_to_active_code_or_user_docs():
    forbidden = (
        "ExtensionViewSpec",
        "ExtensionGeometrySpec",
        "ExtensionOperatorSpec",
        "PANEL_KIND_EXTENSION",
        "ExtensionPanelLifecycle",
        "LinePlotViewSpec",
        "BarPlotViewSpec",
        "SurfaceViewSpec",
        "MorphologyViewSpec",
        "Network2DViewSpec",
    )
    paths = [
        *_python_and_markdown_files(ROOT / "src"),
        *_python_and_markdown_files(ROOT / "examples"),
        *(ROOT / "docs").rglob("*.md"),
        ROOT / "README.md",
    ]
    this_file = Path(__file__).resolve()
    failures: list[str] = []
    for path in paths:
        if path.resolve() == this_file or path.suffix == ".ipynb":
            continue
        text = path.read_text(encoding="utf-8")
        for term in forbidden:
            if term in text:
                failures.append(f"{path.relative_to(ROOT)} contains {term}")
    assert not failures, "\n".join(failures)


def test_published_documented_example_paths_exist():
    documented = "\n".join(
        path.read_text(encoding="utf-8") for path in (ROOT / "docs").glob("*.md")
    )
    example_paths = sorted(
        set(re.findall(r"examples/[A-Za-z0-9_./-]+\.py", documented))
    )
    assert example_paths
    missing = [path for path in example_paths if not (ROOT / path).is_file()]
    assert not missing, f"Documented examples do not exist: {missing}"

    example_directories = sorted(
        set(re.findall(r"examples/[A-Za-z0-9_./-]+/", documented))
    )
    missing_directories = [
        path for path in example_directories if not (ROOT / path).is_dir()
    ]
    assert not missing_directories, (
        f"Documented example directories do not exist: {missing_directories}"
    )


def test_every_published_markdown_page_is_in_navigation():
    config = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    pages = sorted(path.name for path in (ROOT / "docs").glob("*.md"))
    missing = [page for page in pages if page not in config]
    assert not missing, f"Published docs missing from mkdocs navigation: {missing}"


def test_current_architecture_records_do_not_claim_removed_runtime_contracts():
    routing = (
        ROOT / "architecture/design/host-channel-bus-transport.md"
    ).read_text(encoding="utf-8")
    assert "default_targets" not in routing
    assert "message_type=\"set_control\"" not in routing

    package_readmes = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "src/compneurovis").rglob("README.md")
    )
    for retired in (
        "NeuronSession",
        "JaxleySession",
        "NeuronSceneBuilder",
        "JaxleySceneBuilder",
        "SessionUpdate",
    ):
        assert retired not in package_readmes
