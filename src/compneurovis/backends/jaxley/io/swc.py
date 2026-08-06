from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import os
import pickle

import networkx as nx


CACHE_FORMAT_VERSION = 1


def parse_swc(swc_path):
    nodes = {}
    children = defaultdict(list)
    with open(swc_path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            idx, ntype, x, y, z, radius, parent = line.split()
            node_id = int(idx)
            parent_id = int(parent)
            nodes[node_id] = {
                "id": node_id,
                "type": int(ntype),
                "x": float(x),
                "y": float(y),
                "z": float(z),
                "radius": float(radius),
                "parent": parent_id,
            }
            if parent_id >= 0:
                children[parent_id].append(node_id)
    return nodes, children


def _root_subtree_node_ids(children, root_id: int) -> tuple[int, ...]:
    pending = [root_id]
    visited: list[int] = []
    while pending:
        node_id = pending.pop()
        visited.append(node_id)
        pending.extend(reversed(children.get(node_id, ())))
    return tuple(sorted(visited))


def _root_name(base_name: str, *, index: int, multiple_roots: bool) -> str:
    return f"{base_name}_tree_{index}" if multiple_roots else base_name


def _build_root_swc_graph(nodes, children, root_id: int) -> nx.DiGraph:
    from jaxley.io.graph import _add_missing_graph_attrs

    subtree_ids = set(_root_subtree_node_ids(children, root_id))
    graph = nx.DiGraph()
    for node_id in subtree_ids:
        node = nodes[node_id]
        parent_id = node["parent"] if node["parent"] in subtree_ids else -1
        graph.add_node(
            node_id,
            id=node["type"],
            x=node["x"],
            y=node["y"],
            z=node["z"],
            r=node["radius"],
            p=parent_id,
        )
        if parent_id != -1:
            graph.add_edge(parent_id, node_id)
    return _add_missing_graph_attrs(graph)


def _build_compartment_graph(
    swc_graph: nx.DiGraph,
    *,
    ncomp: int,
    min_radius: float | None,
    max_branch_len: float | None,
    ignore_swc_tracing_interruptions: bool,
    relevant_type_ids: list[int] | None,
):
    from jaxley.io.graph import build_compartment_graph

    return build_compartment_graph(
        swc_graph,
        ncomp=ncomp,
        root=None,
        min_radius=min_radius,
        max_len=max_branch_len,
        ignore_swc_tracing_interruptions=ignore_swc_tracing_interruptions,
        relevant_type_ids=relevant_type_ids,
    )


def _build_cells_from_swc(
    swc_path: str,
    *,
    ncomp: int,
    min_radius: float | None,
    max_branch_len: float | None,
    assign_groups: bool,
    ignore_swc_tracing_interruptions: bool,
    relevant_type_ids: list[int] | None,
    basename: str | None,
):
    from jaxley.io.graph import from_graph

    nodes, children = parse_swc(swc_path)
    roots = [node_id for node_id, node in nodes.items() if node["parent"] < 0]
    if not roots:
        raise ValueError(f"No SWC roots found in {swc_path}")

    base_name = basename or os.path.splitext(os.path.basename(swc_path))[0]
    multiple_roots = len(roots) > 1
    loaded = []

    for index, root_id in enumerate(sorted(roots)):
        swc_graph = _build_root_swc_graph(nodes, children, root_id)
        comp_graph = _build_compartment_graph(
            swc_graph,
            ncomp=ncomp,
            min_radius=min_radius,
            max_branch_len=max_branch_len,
            ignore_swc_tracing_interruptions=ignore_swc_tracing_interruptions,
            relevant_type_ids=relevant_type_ids,
        )
        cell = from_graph(
            comp_graph,
            assign_groups=assign_groups,
            solve_root=None,
            traverse_for_solve_order=True,
        )
        name = _root_name(base_name, index=index, multiple_roots=multiple_roots)
        cell.meta_name = name
        loaded.append((name, cell))
    return loaded


def _build_cache_payload(
    swc_path: str,
    *,
    ncomp: int,
    min_radius: float | None,
    max_branch_len: float | None,
    assign_groups: bool,
    ignore_swc_tracing_interruptions: bool,
    relevant_type_ids: list[int] | None,
    basename: str | None,
):
    from jaxley.io.graph import _set_comp_and_branch_index

    nodes, children = parse_swc(swc_path)
    roots = [node_id for node_id, node in nodes.items() if node["parent"] < 0]
    if not roots:
        raise ValueError(f"No SWC roots found in {swc_path}")

    base_name = basename or os.path.splitext(os.path.basename(swc_path))[0]
    multiple_roots = len(roots) > 1
    cached_cells = []

    for index, root_id in enumerate(sorted(roots)):
        swc_graph = _build_root_swc_graph(nodes, children, root_id)
        comp_graph = _build_compartment_graph(
            swc_graph,
            ncomp=ncomp,
            min_radius=min_radius,
            max_branch_len=max_branch_len,
            ignore_swc_tracing_interruptions=ignore_swc_tracing_interruptions,
            relevant_type_ids=relevant_type_ids,
        )
        solve_ready_graph = _set_comp_and_branch_index(comp_graph, root=None)
        cached_cells.append(
            {
                "name": _root_name(base_name, index=index, multiple_roots=multiple_roots),
                "solve_ready_graph": solve_ready_graph,
            }
        )

    return {
        "format_version": CACHE_FORMAT_VERSION,
        "source_swc": str(Path(swc_path).resolve()),
        "ncomp": int(ncomp),
        "min_radius": min_radius,
        "max_branch_len": max_branch_len,
        "assign_groups": bool(assign_groups),
        "ignore_swc_tracing_interruptions": bool(ignore_swc_tracing_interruptions),
        "relevant_type_ids": None if relevant_type_ids is None else list(relevant_type_ids),
        "cells": cached_cells,
    }


def load_swc_multi_jaxley(
    swc_path: str,
    *,
    ncomp: int = 8,
    min_radius: float | None = 1.0,
    max_branch_len: float | None = None,
    assign_groups: bool = True,
    ignore_swc_tracing_interruptions: bool = True,
    relevant_type_ids: list[int] | None = None,
    basename: str | None = None,
):
    return _build_cells_from_swc(
        swc_path,
        ncomp=ncomp,
        min_radius=min_radius,
        max_branch_len=max_branch_len,
        assign_groups=assign_groups,
        ignore_swc_tracing_interruptions=ignore_swc_tracing_interruptions,
        relevant_type_ids=relevant_type_ids,
        basename=basename,
    )


def load_swc_jaxley(
    swc_path: str,
    *,
    ncomp: int = 8,
    min_radius: float | None = 1.0,
    max_branch_len: float | None = None,
    assign_groups: bool = True,
    ignore_swc_tracing_interruptions: bool = True,
    relevant_type_ids: list[int] | None = None,
    basename: str | None = None,
):
    loaded = load_swc_multi_jaxley(
        swc_path,
        ncomp=ncomp,
        min_radius=min_radius,
        max_branch_len=max_branch_len,
        assign_groups=assign_groups,
        ignore_swc_tracing_interruptions=ignore_swc_tracing_interruptions,
        relevant_type_ids=relevant_type_ids,
        basename=basename,
    )
    if len(loaded) != 1:
        raise ValueError(
            f"{swc_path} contains {len(loaded)} disconnected trees; use load_swc_multi_jaxley()"
        )
    return loaded[0][1]


def save_swc_multi_jaxley_cache(
    swc_path: str,
    cache_path: str,
    *,
    ncomp: int = 8,
    min_radius: float | None = 1.0,
    max_branch_len: float | None = None,
    assign_groups: bool = True,
    ignore_swc_tracing_interruptions: bool = True,
    relevant_type_ids: list[int] | None = None,
    basename: str | None = None,
) -> str:
    payload = _build_cache_payload(
        swc_path,
        ncomp=ncomp,
        min_radius=min_radius,
        max_branch_len=max_branch_len,
        assign_groups=assign_groups,
        ignore_swc_tracing_interruptions=ignore_swc_tracing_interruptions,
        relevant_type_ids=relevant_type_ids,
        basename=basename,
    )
    target = Path(cache_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as handle:
        pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
    return str(target)


def save_swc_jaxley_cache(
    swc_path: str,
    cache_path: str,
    *,
    ncomp: int = 8,
    min_radius: float | None = 1.0,
    max_branch_len: float | None = None,
    assign_groups: bool = True,
    ignore_swc_tracing_interruptions: bool = True,
    relevant_type_ids: list[int] | None = None,
    basename: str | None = None,
) -> str:
    path = save_swc_multi_jaxley_cache(
        swc_path,
        cache_path,
        ncomp=ncomp,
        min_radius=min_radius,
        max_branch_len=max_branch_len,
        assign_groups=assign_groups,
        ignore_swc_tracing_interruptions=ignore_swc_tracing_interruptions,
        relevant_type_ids=relevant_type_ids,
        basename=basename,
    )
    payload = _load_cache_payload(path)
    if len(payload["cells"]) != 1:
        raise ValueError(
            f"{swc_path} contains {len(payload['cells'])} disconnected trees; use save_swc_multi_jaxley_cache()"
        )
    return path


def _load_cache_payload(cache_path: str):
    with Path(cache_path).open("rb") as handle:
        payload = pickle.load(handle)
    if payload.get("format_version") != CACHE_FORMAT_VERSION:
        raise ValueError(
            f"Unsupported Jaxley SWC cache format {payload.get('format_version')}; "
            f"expected {CACHE_FORMAT_VERSION}"
        )
    if "cells" not in payload:
        raise ValueError(f"Invalid Jaxley SWC cache payload: {cache_path}")
    return payload


def load_cached_swc_multi_jaxley(cache_path: str):
    from jaxley.io.graph import from_graph

    payload = _load_cache_payload(cache_path)
    loaded = []
    for entry in payload["cells"]:
        cell = from_graph(
            entry["solve_ready_graph"],
            assign_groups=payload.get("assign_groups", True),
            solve_root=None,
            traverse_for_solve_order=False,
        )
        cell.meta_name = entry["name"]
        loaded.append((entry["name"], cell))
    return loaded


def load_cached_swc_jaxley(cache_path: str):
    loaded = load_cached_swc_multi_jaxley(cache_path)
    if len(loaded) != 1:
        raise ValueError(
            f"{cache_path} contains {len(loaded)} disconnected trees; use load_cached_swc_multi_jaxley()"
        )
    return loaded[0][1]
