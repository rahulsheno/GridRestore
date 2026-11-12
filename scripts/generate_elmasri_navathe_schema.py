import os
from PIL import Image, ImageDraw, ImageFont

def render_elmasri_navathe():
    scale = 2  # 2x Retina resolution
    
    font_bold_path = "C:/Windows/Fonts/segoeuib.ttf"
    font_reg_path = "C:/Windows/Fonts/segoeui.ttf"
    font_semibold_path = "C:/Windows/Fonts/seguisb.ttf"
    
    font_main_title = ImageFont.truetype(font_bold_path, 20 * scale)
    font_sub_title = ImageFont.truetype(font_reg_path, 11 * scale)
    font_sec_title = ImageFont.truetype(font_bold_path, 14 * scale)
    font_tbl_title = ImageFont.truetype(font_bold_path, 12 * scale)
    font_cell_reg = ImageFont.truetype(font_reg_path, 10 * scale)
    font_cell_pk = ImageFont.truetype(font_bold_path, 10 * scale)

    # -------------------------------------------------------------
    # 1. CORE APPLICATION RELATIONS (14 Tables)
    # -------------------------------------------------------------
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
        # (src_table, src_col, dst_table, dst_col, route_side, channel)
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

    # -------------------------------------------------------------
    # 2. PHYSICS STUDY RELATIONS (11 Tables)
    # -------------------------------------------------------------
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

    physics_fks = [
        (tbl["name"], "run_id", "PHYSICS_RUNS", "run_id", "left", i + 1)
        for i, tbl in enumerate(physics_tables[1:])
    ]

    # Layout geometry
    canvas_w = 1200 * scale
    canvas_h = 2000 * scale

    img = Image.new("RGB", (canvas_w, canvas_h), "#0d1117")
    draw = ImageDraw.Draw(img)

    # Header
    draw.text((60 * scale, 35 * scale), "GridRestore Relational Database Schema", font=font_main_title, fill="#f0f6fc")
    draw.text((60 * scale, 65 * scale), "Elmasri–Navathe Relational Schema Notation • Contiguous Attribute Boxes • Directed Referential Integrity Constraints (FK → PK)", font=font_sub_title, fill="#8b949e")
    draw.line([60 * scale, 88 * scale, (canvas_w - 60 * scale), 88 * scale], fill="#30363d", width=scale)

    table_x = 95 * scale
    cell_h = 26 * scale
    row_pitch = 68 * scale
    pad_x = 16 * scale
    left_base = 30 * scale
    right_base = 960 * scale

    col_meta = {}

    # Section 1 Header
    cur_y = 115 * scale
    draw.text((60 * scale, cur_y), "1. Core Restoration, Grid Topology & Application Relations", font=font_sec_title, fill="#58a6ff")
    cur_y += 32 * scale

    for t in core_tables:
        t_name = t["name"]
        draw.text((table_x, cur_y - 18 * scale), t_name, font=font_tbl_title, fill="#f0f6fc")
        cx = table_x
        for col_name, is_pk in t["cols"]:
            use_font = font_cell_pk if is_pk else font_cell_reg
            bbox = use_font.getbbox(col_name)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            w = max(tw + pad_x, 70 * scale)

            # Colors matching user image 2 dark theme
            cell_bg = "#21262d" if is_pk else "#161b22"
            cell_border = "#58a6ff" if is_pk else "#30363d"
            text_color = "#ffffff" if is_pk else "#c9d1d9"

            draw.rectangle([cx, cur_y, cx + w, cur_y + cell_h], fill=cell_bg, outline=cell_border, width=scale)
            tx = cx + (w - tw) / 2
            ty = cur_y + (cell_h - th) / 2 - 1 * scale
            draw.text((tx, ty), col_name, font=use_font, fill=text_color)

            # Underline for Primary Key
            if is_pk:
                ul_y = ty + th + 2 * scale
                draw.line([tx, ul_y, tx + tw, ul_y], fill="#58a6ff", width=scale)

            col_meta[(t_name, col_name)] = {
                "cx": cx,
                "w": w,
                "center_x": cx + w / 2,
                "y_top": cur_y,
                "y_bottom": cur_y + cell_h
            }
            cx += w
        cur_y += row_pitch

    # Draw Section 1 Core FK arrows
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
            spacing = 9 * scale
            start_offset = -((tot - 1) * spacing) / 2
            target_x = d["center_x"] + start_offset + (idx * spacing)

        source_x = s["center_x"]
        source_y = s["y_bottom"]
        target_y = d["y_bottom"]

        drop_down_y = source_y + (10 + ch * 4) * scale
        channel_x = (left_base + ch * 12 * scale) if side == "left" else (right_base + ch * 14 * scale)
        enter_y = target_y + (12 + ch * 3.5) * scale

        line_color = "#58a6ff"  # crisp blue
        line_w = scale

        points = [
            (source_x, source_y),
            (source_x, drop_down_y),
            (channel_x, drop_down_y),
            (channel_x, enter_y),
            (target_x, enter_y),
            (target_x, target_y)
        ]
        for i in range(len(points) - 1):
            draw.line([points[i], points[i+1]], fill=line_color, width=line_w)

        # Draw source dot
        draw.ellipse([source_x - 2 * scale, source_y - 2 * scale, source_x + 2 * scale, source_y + 2 * scale], fill=line_color)

        # Draw arrowhead pointing UP into PK target
        ah = 6 * scale
        aw = 4 * scale
        draw.polygon([(target_x, target_y), (target_x - aw, target_y + ah), (target_x + aw, target_y + ah)], fill=line_color)

    # -------------------------------------------------------------
    # Section 2 Header: Physics Study Relations
    # -------------------------------------------------------------
    cur_y += 20 * scale
    draw.line([60 * scale, cur_y - 12 * scale, (canvas_w - 60 * scale), cur_y - 12 * scale], fill="#30363d", width=scale)
    draw.text((60 * scale, cur_y), "2. Analytical Physics-Study Result Relations", font=font_sec_title, fill="#58a6ff")
    cur_y += 32 * scale

    for t in physics_tables:
        t_name = t["name"]
        draw.text((table_x, cur_y - 18 * scale), t_name, font=font_tbl_title, fill="#f0f6fc")
        cx = table_x
        for col_name, is_pk in t["cols"]:
            use_font = font_cell_pk if is_pk else font_cell_reg
            bbox = use_font.getbbox(col_name)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            w = max(tw + pad_x, 70 * scale)

            cell_bg = "#21262d" if is_pk else "#161b22"
            cell_border = "#58a6ff" if is_pk else "#30363d"
            text_color = "#ffffff" if is_pk else "#c9d1d9"

            draw.rectangle([cx, cur_y, cx + w, cur_y + cell_h], fill=cell_bg, outline=cell_border, width=scale)
            tx = cx + (w - tw) / 2
            ty = cur_y + (cell_h - th) / 2 - 1 * scale
            draw.text((tx, ty), col_name, font=use_font, fill=text_color)

            if is_pk:
                ul_y = ty + th + 2 * scale
                draw.line([tx, ul_y, tx + tw, ul_y], fill="#58a6ff", width=scale)

            col_meta[(t_name, col_name)] = {
                "cx": cx,
                "w": w,
                "center_x": cx + w / 2,
                "y_top": cur_y,
                "y_bottom": cur_y + cell_h
            }
            cx += w
        cur_y += row_pitch

    # Draw Physics FK Arrows: all result tables reference PHYSICS_RUNS(run_id)
    # Using a clean vertical bus channel on the left
    pr_run_id = col_meta[("PHYSICS_RUNS", "run_id")]
    bus_x = table_x - 35 * scale

    # Arrow entering PHYSICS_RUNS.run_id from bottom
    draw.line([bus_x, pr_run_id["y_bottom"] + 14 * scale, pr_run_id["center_x"], pr_run_id["y_bottom"] + 14 * scale], fill="#58a6ff", width=scale)
    draw.line([pr_run_id["center_x"], pr_run_id["y_bottom"] + 14 * scale, pr_run_id["center_x"], pr_run_id["y_bottom"]], fill="#58a6ff", width=scale)
    draw.polygon([(pr_run_id["center_x"], pr_run_id["y_bottom"]),
                  (pr_run_id["center_x"] - 4 * scale, pr_run_id["y_bottom"] + 6 * scale),
                  (pr_run_id["center_x"] + 4 * scale, pr_run_id["y_bottom"] + 6 * scale)], fill="#58a6ff")

    # Connect all child tables to the bus
    lowest_bus_y = pr_run_id["y_bottom"] + 14 * scale
    for tbl in physics_tables[1:]:
        c = col_meta[(tbl["name"], "run_id")]
        # Line from child run_id to bus
        sy = c["y_bottom"]
        sx = c["center_x"]
        drop_y = sy + 10 * scale
        draw.line([sx, sy, sx, drop_y], fill="#58a6ff", width=scale)
        draw.line([sx, drop_y, bus_x, drop_y], fill="#58a6ff", width=scale)
        draw.ellipse([sx - 2 * scale, sy - 2 * scale, sx + 2 * scale, sy + 2 * scale], fill="#58a6ff")
        if drop_y > lowest_bus_y:
            lowest_bus_y = drop_y

    # Main trunk of the bus
    draw.line([bus_x, pr_run_id["y_bottom"] + 14 * scale, bus_x, lowest_bus_y], fill="#58a6ff", width=scale)

    out_png = r"c:\Users\Prabha Prabhu\Downloads\GridRestore\docs\figures\relational_schema_diagram.png"
    img.save(out_png, "PNG")
    print(f"Generated masterpiece Elmasri-Navathe relational schema at {out_png}")

if __name__ == "__main__":
    render_elmasri_navathe()
