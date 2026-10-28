from collections import deque, defaultdict
from dataclasses import dataclass, field

import numpy as np
from neuron import h


@dataclass
class SectionNode:
    sec: object
    parent: 'SectionNode | None' = None
    parent_x: float = 0.0
    children: list['SectionNode'] = field(default_factory=list)


def _build_topology_tree(sections, cell_connections=None):
    """
    Build a forest of SectionNode.

    Always uses NEURON's parentseg() for intra-cell topology (sections linked
    via sec.connect()). If cell_connections is provided, those are layered on
    top as inter-cell relationships linking separate cell trees together.

    Returns (roots, node_map) where node_map keys are section names.
    """
    node_map = {}
    for sec in sections:
        node_map[sec.name()] = SectionNode(sec=sec)

    # Intra-cell: always use NEURON's parentseg()
    for sec in sections:
        pseg = sec.parentseg()
        if pseg is None:
            continue
        parent_name = pseg.sec.name()
        if parent_name not in node_map:
            continue
        child_node = node_map[sec.name()]
        parent_node = node_map[parent_name]
        child_node.parent = parent_node
        child_node.parent_x = pseg.x
        parent_node.children.append(child_node)

    # Inter-cell: layer on custom connections between cells
    if cell_connections is not None:
        for child_sec, parent_sec, parent_x in cell_connections:
            child_name = child_sec.name()
            parent_name = parent_sec.name()
            if child_name not in node_map or parent_name not in node_map:
                continue
            child_node = node_map[child_name]
            parent_node = node_map[parent_name]
            # Only add if this node is currently a root (no intra-cell parent).
            # This connects a cell's root section to another cell's section.
            if child_node.parent is not None:
                continue
            child_node.parent = parent_node
            child_node.parent_x = parent_x
            parent_node.children.append(child_node)

    roots = [node for name, node in node_map.items() if node.parent is None]
    return roots, node_map


def _topological_order(roots):
    """BFS traversal yielding SectionNode in parent-before-children order."""
    queue = deque(roots)
    while queue:
        node = queue.popleft()
        yield node
        for child in node.children:
            queue.append(child)


def _interpolate_pt3d(sec, x):
    """
    Interpolate a section's pt3d data at normalized position x (0-1).
    Returns (position, direction, diameter) as numpy arrays/float.
    The section must have n3d() >= 2.
    """
    n = int(sec.n3d())
    pts = np.array(
        [[sec.x3d(i), sec.y3d(i), sec.z3d(i)] for i in range(n)],
        dtype=np.float64,
    )
    diams = np.array([sec.diam3d(i) for i in range(n)], dtype=np.float64)

    diffs = np.diff(pts, axis=0)
    seg_lens = np.linalg.norm(diffs, axis=1)
    cum_lens = np.concatenate(([0.0], np.cumsum(seg_lens)))
    total_len = cum_lens[-1]

    if total_len < 1e-12:
        return pts[0].copy(), np.array([0.0, 0.0, 1.0]), float(diams[0])

    target = x * total_len
    seg_idx = int(np.searchsorted(cum_lens, target, side='right')) - 1
    seg_idx = max(0, min(seg_idx, n - 2))

    seg_start = cum_lens[seg_idx]
    seg_end = cum_lens[seg_idx + 1]
    seg_total = seg_end - seg_start

    t = 0.0 if seg_total < 1e-12 else (target - seg_start) / seg_total

    position = pts[seg_idx] + t * (pts[seg_idx + 1] - pts[seg_idx])
    diameter = diams[seg_idx] + t * (diams[seg_idx + 1] - diams[seg_idx])

    direction = pts[seg_idx + 1] - pts[seg_idx]
    dir_len = np.linalg.norm(direction)
    if dir_len < 1e-12:
        direction = np.array([0.0, 0.0, 1.0])
    else:
        direction = direction / dir_len

    return position, direction, float(diameter)


def _compute_perpendicular(direction):
    """Return a unit vector perpendicular to direction (numerically stable)."""
    d = direction / np.linalg.norm(direction)
    abs_d = np.abs(d)
    if abs_d[0] <= abs_d[1] and abs_d[0] <= abs_d[2]:
        aux = np.array([1.0, 0.0, 0.0])
    elif abs_d[1] <= abs_d[2]:
        aux = np.array([0.0, 1.0, 0.0])
    else:
        aux = np.array([0.0, 0.0, 1.0])

    perp = np.cross(d, aux)
    perp_len = np.linalg.norm(perp)
    if perp_len < 1e-12:
        # Fallback: try a different auxiliary
        aux = np.array([0.0, 1.0, 0.0]) if abs_d[1] > abs_d[0] else np.array([1.0, 0.0, 0.0])
        perp = np.cross(d, aux)
        perp_len = np.linalg.norm(perp)
    return perp / perp_len


def _rotation_matrix_axis_angle(axis, angle_rad):
    """Rodrigues rotation matrix: rotate around axis by angle_rad."""
    a = axis / np.linalg.norm(axis)
    K = np.array([
        [0, -a[2], a[1]],
        [a[2], 0, -a[0]],
        [-a[1], a[0], 0],
    ])
    return np.eye(3) + np.sin(angle_rad) * K + (1 - np.cos(angle_rad)) * (K @ K)


def _fan_directions(parent_dir, num_children, branch_angle_deg):
    """
    Compute num_children direction vectors fanned around parent_dir.
    1 child: continue straight. 2+: evenly distributed in a cone.
    """
    if num_children == 0:
        return []

    parent_dir = parent_dir / np.linalg.norm(parent_dir)

    if num_children == 1:
        return [parent_dir.copy()]

    branch_angle_rad = np.radians(branch_angle_deg)
    perp = _compute_perpendicular(parent_dir)

    directions = []
    for i in range(num_children):
        azimuth = 2.0 * np.pi * i / num_children

        # Tilt parent_dir toward perp by branch_angle
        tilt_axis = np.cross(parent_dir, perp)
        tilt_axis_len = np.linalg.norm(tilt_axis)
        if tilt_axis_len < 1e-12:
            tilt_axis = _compute_perpendicular(perp)
        else:
            tilt_axis = tilt_axis / tilt_axis_len

        R_tilt = _rotation_matrix_axis_angle(tilt_axis, branch_angle_rad)
        tilted = R_tilt @ parent_dir

        # Rotate tilted vector around parent_dir by azimuth
        R_azimuth = _rotation_matrix_axis_angle(parent_dir, azimuth)
        child_dir = R_azimuth @ tilted
        child_dir = child_dir / np.linalg.norm(child_dir)
        directions.append(child_dir)

    return directions


def generate_layout(
    sections,
    cell_connections=None,
    default_direction=(0, 0, 1),
    branch_angle=30.0,
    min_length=1.0,
    root_spacing=100.0,
):
    """
    Generate pt3d data for sections that lack it, using a tree-walking algorithm.

    Intra-cell topology is always inferred from NEURON's sec.connect() /
    parentseg() relationships. Sections connected this way form cells
    (connected components in the topology tree).

    cell_connections optionally specifies inter-cell spatial relationships
    (e.g. gap junctions, NetCons) as (child_sec, parent_sec, parent_x) tuples.
    Each tuple attaches a cell's root section to a section in another cell,
    positioning the child cell relative to the parent cell. Sections that
    already have an intra-cell parent (via sec.connect()) are not affected
    by cell_connections.

    Disconnected cell trees with no cell_connections are auto-spaced by
    root_spacing so they don't overlap.

    Parameters:
        sections:          iterable of h.Section
        cell_connections:  optional list of (child_sec, parent_sec, parent_x) tuples
                           for inter-cell spatial relationships
        default_direction: unit vector direction for root sections
        branch_angle:      degrees of spread between sibling branches
        min_length:        minimum length for zero-length sections
        root_spacing:      distance between disconnected root sections
    """
    roots, node_map = _build_topology_tree(sections, cell_connections)

    default_dir = np.array(default_direction, dtype=np.float64)
    dir_len = np.linalg.norm(default_dir)
    if dir_len > 1e-12:
        default_dir = default_dir / dir_len
    else:
        default_dir = np.array([0.0, 0.0, 1.0])

    # Pre-assign fan directions for children as we visit each node
    assigned_directions = {}

    root_count = 0
    for node in _topological_order(roots):
        sec = node.sec
        length = max(float(sec.L), min_length)
        diam = float(sec.diam)

        if node.parent is None:
            # Root section
            start_pos = np.array([root_count * root_spacing, 0.0, 0.0])
            direction = default_dir.copy()
            root_count += 1
        else:
            # Child section - parent is guaranteed to have pt3d already (BFS order)
            start_pos, parent_dir, _ = _interpolate_pt3d(node.parent.sec, node.parent_x)
            direction = assigned_directions.get(id(node), parent_dir)

        end_pos = start_pos + direction * length

        sec.pt3dclear()
        sec.pt3dadd(float(start_pos[0]), float(start_pos[1]), float(start_pos[2]), diam)
        sec.pt3dadd(float(end_pos[0]), float(end_pos[1]), float(end_pos[2]), diam)

        # Compute fan directions for this node's children, grouped by parent_x
        children_by_x = defaultdict(list)
        for child in node.children:
            children_by_x[child.parent_x].append(child)

        for cx, child_nodes in children_by_x.items():
            _, conn_dir, _ = _interpolate_pt3d(sec, cx)
            fan_dirs = _fan_directions(conn_dir, len(child_nodes), branch_angle)
            for child_node, fan_dir in zip(child_nodes, fan_dirs):
                assigned_directions[id(child_node)] = fan_dir


def define_shape_layout():
    """Fallback: call NEURON's built-in h.define_shape()."""
    h.define_shape()
