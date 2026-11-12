import os

def generate_svg():
    core_tables = [
        {
            "name": "GRID_NODES",
            "cols": [("node_id", True), ("node_name", False), ("node_type", False), ("criticality", False), ("region_code", False)]
        },
        {
            "name": "GRID_EDGES",
            "cols": [("edge_id", True), ("from_node_id", False), ("to_node_id", False), ("component_type", False), ("nominal_capacity_kw", False)]
        },
        {
            "name": "OUTAGE_SCENARIOS",
            "cols": [("scenario_id", True), ("scenario_name", False), ("budget", False), ("crew_count", False), ("created_at", False)]
        },
        {
            "name": "REPAIR_TASKS",
            "cols": [("task_id", True), ("scenario_id", False), ("edge_id", False), ("component_name", False), ("estimated_hours", False), ("estimated_cost", False), ("priority", False), ("status", False)]
        },
        {
            "name": "TASK_DEPENDENCIES",
            "cols": [("task_id", True), ("prerequisite_task_id", True)]
        },
        {
            "name": "CREWS",
            "cols": [("crew_id", True), ("crew_name", False), ("skill", False), ("available_from", False)]
        },
        {
            "name": "RESTORATION_RUNS",
            "cols": [("run_id", True), ("scenario_id", False), ("strategy_name", False), ("total_cost", False), ("makespan_hours", False), ("weighted_recovery_score", False)]
        },
        {
            "name": "SCHEDULED_ACTIONS",
            "cols": [("action_id", True), ("run_id", False), ("task_id", False), ("crew_label", False), ("start_hour", False), ("finish_hour", False)]
        },
        {
            "name": "APP_USERS",
            "cols": [("user_id", True), ("username", True), ("password_hash", False), ("role", False), ("created_at", False)]
        },
        {
            "name": "REFRESH_TOKENS",
            "cols": [("token_hash", True), ("username", False), ("expires_at", False), ("revoked", False)]
        },
        {
            "name": "SCENARIO_VERSIONS",
            "cols": [("scenario_id", True), ("version_no", True), ("snapshot_data", False), ("created_at", False)]
        },
        {
            "name": "AUDIT_LOG",
            "cols": [("audit_id", True), ("table_name", False), ("operation", False), ("row_key", False), ("changed_at", False)]
        },
        {
            "name": "REPAIR_EMBEDDINGS",
            "cols": [("task_id", True), ("narrative", False), ("embedding", False), ("embedding_st", False), ("narrative_tsv", False)]
        },
        {
            "name": "ELEMENT_PHYSICS_MAP",
            "cols": [("edge_id", True), ("case_name", False), ("element_type", False), ("element_index", False)]
        }
    ]

    core_fks = [
        ("GRID_EDGES", "from_node_id", "GRID_NODES", "node_id", "left", 1),
        ("GRID_EDGES", "to_node_id", "GRID_NODES", "node_id", "left", 2),
        ("ELEMENT_PHYSICS_MAP", "edge_id", "GRID_EDGES", "edge_id", "left", 3),
        ("REPAIR_TASKS", "scenario_id", "OUTAGE_SCENARIOS", "scenario_id", "left", 1),
        ("REPAIR_TASKS", "edge_id", "GRID_EDGES", "edge_id", "right", 1),
        ("TASK_DEPENDENCIES", "task_id", "REPAIR_TASKS", "task_id", "left", 1),
        ("TASK_DEPENDENCIES", "prerequisite_task_id", "REPAIR_TASKS", "task_id", "left", 2),
        ("REPAIR_EMBEDDINGS", "task_id", "REPAIR_TASKS", "task_id", "left", 3),
        ("RESTORATION_RUNS", "scenario_id", "OUTAGE_SCENARIOS", "scenario_id", "right", 2),
        ("SCHEDULED_ACTIONS", "run_id", "RESTORATION_RUNS", "run_id", "left", 1),
        ("SCHEDULED_ACTIONS", "task_id", "REPAIR_TASKS", "task_id", "right", 3),
        ("SCENARIO_VERSIONS", "scenario_id", "OUTAGE_SCENARIOS", "scenario_id", "right", 4),
        ("REFRESH_TOKENS", "username", "APP_USERS", "username", "left", 1),
    ]

    physics_tables = [
        {
            "name": "PHYSICS_RUNS",
            "cols": [("run_id", True), ("mode", False), ("settings", False), ("created_at", False)]
        },
        {
            "name": "PHYSICS_VALIDATION",
            "cols": [("run_id", True), ("benchmark_name", True), ("case_name", True), ("metric", True), ("value", False)]
        },
        {
            "name": "PHYSICS_CONTINUATION",
            "cols": [("run_id", True), ("case_name", True), ("alpha", True), ("status", False), ("max_loading", False)]
        },
        {
            "name": "PHYSICS_CONTINUATION_SUMMARY",
            "cols": [("run_id", True), ("case_name", True), ("voltage_limit_alpha", False), ("knee_alpha", False)]
        },
        {
            "name": "PHYSICS_FDIA_SUMMARY",
            "cols": [("run_id", True), ("case_name", True), ("kind", True), ("accuracy", False), ("f1_score", False)]
        },
        {
            "name": "PHYSICS_FDIA_TRIALS",
            "cols": [("run_id", True), ("case_name", True), ("trial", True), ("stealthy_feasible", False)]
        },
        {
            "name": "PHYSICS_MDP_POLICY",
            "cols": [("run_id", True), ("case_name", True), ("stress_vector", True), ("weight_set", True), ("state", True), ("optimal_action", False)]
        },
        {
            "name": "PHYSICS_MDP_TRANSITIONS",
            "cols": [("run_id", True), ("case_name", True), ("stress_vector", True), ("collapse_model", True), ("action", True), ("probabilities", False)]
        },
        {
            "name": "PHYSICS_SENSITIVITY",
            "cols": [("run_id", True), ("sweep", True), ("k", True), ("lambda0", True), ("w1", True), ("w3", True), ("k_voltage", True), ("gamma", True)]
        },
        {
            "name": "PHYSICS_CONVERGENCE",
            "cols": [("run_id", True), ("case_name", True), ("stress_vector", True), ("method", True), ("step", True), ("max_dx_change", False)]
        },
        {
            "name": "PHYSICS_FIGURES",
            "cols": [("run_id", True), ("name", True), ("fig_type", False), ("file_path", False)]
        }
    ]

    width = 1200
    height = 2000

    table_x = 95
    cell_h = 26
    row_pitch = 68
    pad_x = 16
    left_base = 30
    right_base = 960

    svg = []
    svg.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="100%" height="100%" style="background-color: #0d1117; font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Helvetica, Arial, sans-serif;">')
    svg.append('<defs>')
    svg.append('  <marker id="arrow" viewBox="0 0 10 10" refX="5" refY="3" markerWidth="6" markerHeight="6" orient="auto">')
    svg.append('    <path d="M 0 6 L 5 0 L 10 6 z" fill="#58a6ff" />')
    svg.append('  </marker>')
    svg.append('</defs>')

    # Header
    svg.append('<text x="60" y="45" fill="#f0f6fc" font-size="20" font-weight="bold">GridRestore Relational Database Schema</text>')
    svg.append('<text x="60" y="68" fill="#8b949e" font-size="11">Elmasri–Navathe Relational Schema Notation • Contiguous Attribute Boxes • Directed Referential Integrity Constraints (FK → PK)</text>')
    svg.append(f'<line x1="60" y1="88" x2="{width - 60}" y2="88" stroke="#30363d" stroke-width="1"/>')

    col_meta = {}

    # Section 1
    cur_y = 115
    svg.append(f'<text x="60" y="{cur_y}" fill="#58a6ff" font-size="14" font-weight="bold">1. Core Restoration, Grid Topology &amp; Application Relations</text>')
    cur_y += 32

    for t in core_tables:
        t_name = t["name"]
        svg.append(f'<text x="{table_x}" y="{cur_y - 8}" fill="#f0f6fc" font-size="12" font-weight="bold">{t_name}</text>')
        cx = table_x
        for col_name, is_pk in t["cols"]:
            tw = len(col_name) * 7.5
            w = max(tw + pad_x, 70)
            cell_bg = "#21262d" if is_pk else "#161b22"
            cell_border = "#58a6ff" if is_pk else "#30363d"
            text_color = "#ffffff" if is_pk else "#c9d1d9"
            font_weight = "bold" if is_pk else "normal"

            svg.append(f'<rect x="{cx}" y="{cur_y}" width="{w}" height="{cell_h}" fill="{cell_bg}" stroke="{cell_border}" stroke-width="1"/>')
            tx = cx + w / 2
            ty = cur_y + cell_h / 2 + 4
            text_decor = ' text-decoration="underline" text-decoration-color="#58a6ff"' if is_pk else ''
            svg.append(f'<text x="{tx}" y="{ty}" fill="{text_color}" font-size="10" font-weight="{font_weight}" text-anchor="middle"{text_decor}>{col_name}</text>')

            col_meta[(t_name, col_name)] = {
                "cx": cx,
                "w": w,
                "center_x": cx + w / 2,
                "y_top": cur_y,
                "y_bottom": cur_y + cell_h
            }
            cx += w
        cur_y += row_pitch

    # Section 1 FK arrows
    dst_counts = {}
    for src_t, src_c, dst_t, dst_c, side, ch in core_fks:
        k = (dst_t, dst_c)
        dst_counts[k] = dst_counts.get(k, 0) + 1

    dst_current_idx = {}
    for src_t, src_c, dst_t, dst_c, side, ch in core_fks:
        s = col_meta[(src_t, src_c)]
        d = col_meta[(dst_t, dst_c)]

        tot = dst_counts[(dst_t, dst_c)]
        idx = dst_current_idx.get((dst_t, dst_c), 0)
        dst_current_idx[(dst_t, dst_c)] = idx + 1

        if tot == 1:
            target_x = d["center_x"]
        else:
            spacing = 9
            start_offset = -((tot - 1) * spacing) / 2
            target_x = d["center_x"] + start_offset + (idx * spacing)

        source_x = s["center_x"]
        source_y = s["y_bottom"]
        target_y = d["y_bottom"]

        drop_down_y = source_y + (10 + ch * 4)
        channel_x = (left_base + ch * 12) if side == "left" else (right_base + ch * 14)
        enter_y = target_y + (12 + ch * 3.5)

        # SVG polyline or path
        path_d = f"M {source_x} {source_y} L {source_x} {drop_down_y} L {channel_x} {drop_down_y} L {channel_x} {enter_y} L {target_x} {enter_y} L {target_x} {target_y}"
        svg.append(f'<path d="{path_d}" fill="none" stroke="#58a6ff" stroke-width="1.2" marker-end="url(#arrow)"/>')
        svg.append(f'<circle cx="{source_x}" cy="{source_y}" r="2.5" fill="#58a6ff"/>')

    # Section 2: Physics Tables
    cur_y += 20
    svg.append(f'<line x1="60" y1="{cur_y - 12}" x2="{width - 60}" y2="{cur_y - 12}" stroke="#30363d" stroke-width="1"/>')
    svg.append(f'<text x="60" y="{cur_y}" fill="#58a6ff" font-size="14" font-weight="bold">2. Analytical Physics-Study Result Relations</text>')
    cur_y += 32

    for t in physics_tables:
        t_name = t["name"]
        svg.append(f'<text x="{table_x}" y="{cur_y - 8}" fill="#f0f6fc" font-size="12" font-weight="bold">{t_name}</text>')
        cx = table_x
        for col_name, is_pk in t["cols"]:
            tw = len(col_name) * 7.5
            w = max(tw + pad_x, 70)
            cell_bg = "#21262d" if is_pk else "#161b22"
            cell_border = "#58a6ff" if is_pk else "#30363d"
            text_color = "#ffffff" if is_pk else "#c9d1d9"
            font_weight = "bold" if is_pk else "normal"

            svg.append(f'<rect x="{cx}" y="{cur_y}" width="{w}" height="{cell_h}" fill="{cell_bg}" stroke="{cell_border}" stroke-width="1"/>')
            tx = cx + w / 2
            ty = cur_y + cell_h / 2 + 4
            text_decor = ' text-decoration="underline" text-decoration-color="#58a6ff"' if is_pk else ''
            svg.append(f'<text x="{tx}" y="{ty}" fill="{text_color}" font-size="10" font-weight="{font_weight}" text-anchor="middle"{text_decor}>{col_name}</text>')

            col_meta[(t_name, col_name)] = {
                "cx": cx,
                "w": w,
                "center_x": cx + w / 2,
                "y_top": cur_y,
                "y_bottom": cur_y + cell_h
            }
            cx += w
        cur_y += row_pitch

    # Bus for physics tables
    pr_run_id = col_meta[("PHYSICS_RUNS", "run_id")]
    bus_x = table_x - 35
    top_bus_y = pr_run_id["y_bottom"] + 14

    # Path from bus to PHYSICS_RUNS.run_id
    svg.append(f'<path d="M {bus_x} {top_bus_y} L {pr_run_id["center_x"]} {top_bus_y} L {pr_run_id["center_x"]} {pr_run_id["y_bottom"]}" fill="none" stroke="#58a6ff" stroke-width="1.2" marker-end="url(#arrow)"/>')

    lowest_bus_y = top_bus_y
    for tbl in physics_tables[1:]:
        c = col_meta[(tbl["name"], "run_id")]
        sy = c["y_bottom"]
        sx = c["center_x"]
        drop_y = sy + 10
        svg.append(f'<path d="M {sx} {sy} L {sx} {drop_y} L {bus_x} {drop_y}" fill="none" stroke="#58a6ff" stroke-width="1.2"/>')
        svg.append(f'<circle cx="{sx}" cy="{sy}" r="2.5" fill="#58a6ff"/>')
        if drop_y > lowest_bus_y:
            lowest_bus_y = drop_y

    svg.append(f'<line x1="{bus_x}" y1="{top_bus_y}" x2="{bus_x}" y2="{lowest_bus_y}" stroke="#58a6ff" stroke-width="1.2"/>')

    svg.append('</svg>')

    out_svg = r"c:\Users\Prabha Prabhu\Downloads\GridRestore\docs\figures\relational_schema_diagram.svg"
    with open(out_svg, "w", encoding="utf-8") as f:
        f.write("\n".join(svg))
    print(f"Generated clean SVG relational schema at {out_svg}")

if __name__ == "__main__":
    generate_svg()

