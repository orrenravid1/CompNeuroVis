from collections import defaultdict
from neuron import h
h.load_file("stdlib.hoc")
h.load_file("import3d.hoc")

def load_swc_neuron(swc_path):
    """Import an SWC file into NEURON and return the list of sections."""
    reader = h.Import3d_SWC_read()
    reader.input(swc_path)
    i3d = h.Import3d_GUI(reader, False)
    i3d.instantiate(None)
    secs = list(h.allsec())
    return secs

def parse_swc(swc_path):
    nodes = {}
    children = defaultdict(list)
    with open(swc_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            idx, ntype, x, y, z, rad, parent = line.split()
            idx, parent = int(idx), int(parent)
            x, y, z, rad = map(float, (x, y, z, rad))
            nodes[idx] = {
                'type': int(ntype),
                'x': x, 'y': y, 'z': z,
                'radius': rad,
                'parent': parent
            }
            if parent >= 0:
                children[parent].append(idx)
    return nodes, children

def _build_branch(nodes, children, parent_id, child_id, parent_sec, sections, counters, basename=None):
    """
    Recursively build NEURON Sections for one branch of the SWC morphology.
    Splits at type changes and branch points, ensures non-zero length by
    inserting a two-point stub when needed, and names each section
    explicitly as "{basename_}label[index]".
    """
    # 1) Determine label from SWC type
    type_names = {1: 'soma', 2: 'axon', 3: 'dendrite', 4: 'apical'}
    initial_type = nodes[parent_id]['type']
    label = type_names.get(initial_type, 'sec')

    # 2) Collect all points along this branch while same type & single child
    pts = [nodes[parent_id]]
    curr = child_id
    while (nodes[curr]['type'] == initial_type) and (len(children[curr]) == 1):
        pts.append(nodes[curr])
        curr = children[curr][0]
    # include the stopping node if it’s still the same type
    if nodes[curr]['type'] == initial_type:
        pts.append(nodes[curr])

    # 3) Detect zero-length (fewer than 2 unique coords) and replace with a stub
    uniq = {(p['x'], p['y'], p['z']) for p in pts}
    if len(uniq) < 2:
        r0 = pts[0]['radius'] or 1.0
        default_len = 2.0 * r0
        x0, y0, z0 = pts[0]['x'], pts[0]['y'], pts[0]['z']
        pts = [
            {'x': x0,           'y': y0, 'z': z0, 'radius': r0},
            {'x': x0+default_len,'y': y0, 'z': z0, 'radius': r0}
        ]

    # 4) Build an explicit name with your own counter
    idx = counters.get(label, 0)
    counters[label] = idx + 1
    if basename:
        sec_name = f"{basename}_{label}[{idx}]"
    else:
        sec_name = f"{label}[{idx}]"

    # 5) Create the NEURON Section and connect it
    sec = h.Section(name=sec_name)
    if parent_sec is not None:
        sec.connect(parent_sec, 0)

    # 6) Add the 3D points to the section
    sec.pt3dclear()
    for p in pts:
        sec.pt3dadd(p['x'], p['y'], p['z'], p['radius'])

    # 7) Keep track of it
    sections.append(sec)

    # 8) Recurse on any children of the stopping node
    for child in children.get(curr, []):
        _build_branch(nodes, children, curr, child, sec, sections, counters, basename)

def load_swc_multi(swc_path, basename=None):
    """
    Returns { root_id: [Section,...], ... }.
    Section names follow the form 'soma[0]', 'axon[0]', 'axon[1]', etc.
    """
    nodes, children = parse_swc(swc_path)
    # find all roots
    roots = [n for n, d in nodes.items() if d['parent'] < 0]
    all_trees = {}

    # one shared counter dict for this file
    counters = {}

    for r in roots:
        secs = []
        # isolated root?
        if not children[r]:
            label = {1:'soma'}.get(nodes[r]['type'], 'sec')
            idx = counters.get(label, 0)
            if basename is not None:
                sec = h.Section(name=f"{basename}_{label}[{idx}]")
            else:
                sec = h.Section(name=f"{label}[{idx}]")
            counters[label] = idx + 1
            sec.pt3dclear()
            n = nodes[r]
            sec.pt3dadd(n['x'], n['y'], n['z'], n['radius'])
            secs.append(sec)
        else:
            for c in children[r]:
                _build_branch(nodes, children, r, c, None, secs, counters, basename)

        all_trees[r] = secs

    return all_trees

