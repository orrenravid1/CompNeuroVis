from neuron import h
import json

def export_section_json(filename, sections):
    """
    Export NEURON sections to a JSON file with per-segment biophysics,
    density mechanism parameters, ion reversal and concentration values,
    geometry (PT3D), and point processes.
    Example usage:
    sections = list(h.allsec())
    export_section_json("cell_full_per_segment.json", sections)

    Parameters:
      filename (str): Path to output JSON file.
      sections (list of h.Section): List of sections to export.
    """
    data = {"sections": {}}

    for sec in sections:
        # Parent topology
        pseg = sec.parentseg()  # None or Segment on the parent section
        parent_name = pseg.sec.hname() if pseg else None
        parent_x = pseg.x if pseg else 0.0

        # Geometry: all PT3D points
        geometry = [
            {"x": sec.x3d(i), "y": sec.y3d(i), "z": sec.z3d(i), "diam": sec.diam3d(i)}
            for i in range(sec.n3d())
        ]

        # Biophysics: nseg, Ra, cm per segment
        nseg = sec.nseg
        Ra = sec.Ra
        cm_values = [seg.cm for seg in sec]

        # Density mechanisms: per-segment parameter lists
        ps = sec.psection()
        density_mechs = {}
        for mech_name, mech_params in ps.get("density_mechs", {}).items():
            density_mechs[mech_name] = {}
            for p_name in mech_params:
                # Collect the value of this parameter on each segment's mechanism
                values = []
                for seg in sec:
                    mech = getattr(seg, mech_name)
                    values.append(getattr(mech, p_name))
                density_mechs[mech_name][p_name] = values

        # Ions: per-segment reversal potentials and concentrations
        ions = {}
        for ion_name, ion_params in ps.get("ions", {}).items():
            ions[ion_name] = {}
            for i_name, _ in ion_params.items():
                values = []
                for seg in sec:
                    # e.g. seg.ena, seg.ki, seg.cai, etc.
                    values.append(getattr(seg, i_name))
                ions[ion_name][i_name] = values

        # Point processes: extract from psection()
        point_processes = []
        for mech, inst_list in ps.get("point_processes", {}).items():
            for obj in inst_list:
                seg = obj.get_segment()
                # Safely collect numeric attributes
                params = {}
                for attr in dir(obj):
                    if attr.startswith('_'):
                        continue
                    try:
                        val = getattr(obj, attr)
                    except Exception:
                        continue
                    if isinstance(val, (int, float)):
                        params[attr] = val
                point_processes.append({
                    "type":       mech,
                    "section_loc": { "section": sec.hname(), "loc": seg.x },
                    "parameters": params
                })

        # Assemble section entry
        data["sections"][sec.hname()] = {
            "parent":           parent_name,
            "parent_x":         parent_x,
            "geometry":         geometry,
            "nseg":             nseg,
            "Ra":               Ra,
            "cm":               cm_values,
            "density_mechs":    density_mechs,
            "ions":             ions,
            "point_processes":  point_processes
        }

    # Write to JSON file
    with open(filename, "w") as fp:
        json.dump(data, fp, indent=2)
    print(f"Exported {len(sections)} sections to {filename}")

def import_section_json(filename):
    """
    Rebuilds a NEURON cell from a JSON file produced by the per-segment exporter.
    Ensures a 1:1 round-trip: export → import → export yields identical JSON.
    Returns a dict mapping section names to their h.Section instances and a list of point processes.

    Example usage:
    secs, pps = import_section_json("cell_per_segment.json")
    """
    # 1) Load JSON
    with open(filename, "r") as fp:
        data = json.load(fp)

    secs = {}
    pps = []

    # 2) Create all sections by name
    for sec_name in data["sections"]:
        secs[sec_name] = h.Section(name=sec_name)

    # 3) Reconnect topology
    for sec_name, info in data["sections"].items():
        parent = info["parent"]
        if parent is not None:
            secs[sec_name].connect(secs[parent], info["parent_x"])

    # 4) Rebuild each section
    for sec_name, info in data["sections"].items():
        sec = secs[sec_name]

        # 4a) Geometry
        sec.pt3dclear()
        for pt in info["geometry"]:
            sec.pt3dadd(pt["x"], pt["y"], pt["z"], pt["diam"])

        # 4b) Basic biophysics
        sec.nseg = info["nseg"]
        sec.Ra   = info["Ra"]
        # per-segment capacitance
        for seg, cm_val in zip(sec, info["cm"]):
            seg.cm = cm_val

        # 4c) Density mechanisms per segment
        density_mechs = info.get("density_mechs", {})
        existing = sec.psection().get("density_mechs", {})
        # Insert each mechanism first
        for mech_name in density_mechs:
            if mech_name not in existing:
                sec.insert(mech_name)
        # Assign parameters per-segment
        for mech_name, params in density_mechs.items():
            param_names = list(params.keys())
            value_lists = [params[p] for p in param_names]
            for seg, vals in zip(sec, zip(*value_lists)):
                mech_obj = getattr(seg, mech_name)
                for p_name, val in zip(param_names, vals):
                    setattr(mech_obj, p_name, val)

        # 4d) Ions per segment
        ions = info.get("ions", {})
        for ion_name, ion_params in ions.items():
            param_names = list(ion_params.keys())
            value_lists = [ion_params[p] for p in param_names]
            for seg, vals in zip(sec, zip(*value_lists)):
                for p_name, val in zip(param_names, vals):
                    setattr(seg, p_name, val)

        for pp in info["point_processes"]:
            mech_type  = pp["type"]                    # e.g. "ExpSyn"
            section    = secs[ pp["section_loc"]["section"] ]
            loc        = pp["section_loc"]["loc"]
            constructor = getattr(h, mech_type)        # fetch the class/factory
            # directly instantiate on the right section
            pp_obj     = constructor(section(loc))
            for name, val in pp["parameters"].items():
                setattr(pp_obj, name, val)
            pps.append(pp_obj)
            

    print(f"Imported {len(secs)} sections, {len(pps)} point processes from {filename}")
    return secs, pps
