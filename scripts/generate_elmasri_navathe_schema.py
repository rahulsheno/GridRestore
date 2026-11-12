import os
from PIL import Image, ImageDraw, ImageFont

def generate_schema_diagrams():
    scale = 2  # 2x Retina resolution
    
    font_bold_path = "C:/Windows/Fonts/segoeuib.ttf"
    font_reg_path = "C:/Windows/Fonts/segoeui.ttf"
    
    font_main_title = ImageFont.truetype(font_bold_path, 18 * scale)
    font_sub_title = ImageFont.truetype(font_reg_path, 10 * scale)
    font_tbl_title = ImageFont.truetype(font_bold_path, 12 * scale)
    font_cell_reg = ImageFont.truetype(font_reg_path, 9.5 * scale)
    font_cell_pk = ImageFont.truetype(font_bold_path, 9.5 * scale)

    # Core GridRestore Relational Schema (14 Tables)
    tables = [
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
            "name": "SCENARIO_VERSIONS",
            "cols": [("scenario_id", True), ("version_no", True), ("snapshot_data", False), ("created_at", False)]
        },
        {
            "name": "REPAIR_EMBEDDINGS",
            "cols": [("task_id", True), ("narrative", False), ("embedding", False), ("embedding_st", False), ("narrative_tsv", False)]
        },
        {
            "name": "ELEMENT_PHYSICS_MAP",
            "cols": [("edge_id", True), ("case_name", False), ("element_type", False), ("element_index", False)]
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
            "name": "AUDIT_LOG",
            "cols": [("audit_id", True), ("table_name", False), ("operation", False), ("row_key", False), ("changed_at", False)]
        }
    ]

    # Explicit collision-free routing: all vertical conduits run in the dedicated LEFT gutter
    fks = [
        ("GRID_EDGES", "from_node_id", "GRID_NODES", "node_id", 1),
        ("GRID_EDGES", "to_node_id", "GRID_NODES", "node_id", 2),
        ("REPAIR_TASKS", "scenario_id", "OUTAGE_SCENARIOS", "scenario_id", 1),
        ("REPAIR_TASKS", "edge_id", "GRID_EDGES", "edge_id", 3),
        ("TASK_DEPENDENCIES", "task_id", "REPAIR_TASKS", "task_id", 1),
        ("TASK_DEPENDENCIES", "prerequisite_task_id", "REPAIR_TASKS", "task_id", 2),
        ("RESTORATION_RUNS", "scenario_id", "OUTAGE_SCENARIOS", "scenario_id", 2),
        ("SCHEDULED_ACTIONS", "run_id", "RESTORATION_RUNS", "run_id", 1),
        ("SCHEDULED_ACTIONS", "task_id", "REPAIR_TASKS", "task_id", 4),
        ("SCENARIO_VERSIONS", "scenario_id", "OUTAGE_SCENARIOS", "scenario_id", 3),
        ("REPAIR_EMBEDDINGS", "task_id", "REPAIR_TASKS", "task_id", 5),
        ("ELEMENT_PHYSICS_MAP", "edge_id", "GRID_EDGES", "edge_id", 6),
        ("REFRESH_TOKENS", "username", "APP_USERS", "username", 1),
    ]

    canvas_w = 1200 * scale
    canvas_h = 1380 * scale

    table_x = 160 * scale
    cell_h = 24 * scale
    title_gap = 14 * scale
    table_inter_gap = 46 * scale
    pad_x = 14 * scale

    left_channels = {
        1: 138 * scale,
        2: 116 * scale,
        3: 94 * scale,
        4: 72 * scale,
        5: 50 * scale,
        6: 28 * scale
    }

    def render_png(theme="dark"):
        if theme == "dark":
            bg_color = "#0d1117"
            title_color = "#f0f6fc"
            subtitle_color = "#8b949e"
            divider_color = "#30363d"
            tbl_name_color = "#f0f6fc"
            cell_reg_bg = "#161b22"
            cell_reg_border = "#30363d"
            cell_reg_text = "#c9d1d9"
            cell_pk_bg = "#21262d"
            cell_pk_border = "#58a6ff"
            cell_pk_text = "#ffffff"
            pk_underline_color = "#58a6ff"
            arrow_color = "#58a6ff"
        else:
            bg_color = "#ffffff"
            title_color = "#1f2328"
            subtitle_color = "#656d76"
            divider_color = "#d0d7de"
            tbl_name_color = "#1f2328"
            cell_reg_bg = "#f6f8fa"
            cell_reg_border = "#202124"
            cell_reg_text = "#202124"
            cell_pk_bg = "#e8eaed"
            cell_pk_border = "#202124"
            cell_pk_text = "#202124"
            pk_underline_color = "#202124"
            arrow_color = "#202124"

        img = Image.new("RGB", (canvas_w, canvas_h), bg_color)
        draw = ImageDraw.Draw(img)

        # Header
        draw.text((60 * scale, 28 * scale), "GridRestore Relational Database Schema", font=font_main_title, fill=title_color)
        draw.text((60 * scale, 54 * scale), "Elmasri–Navathe Relational Schema Notation • Contiguous Attribute Boxes • Directed Referential Integrity Constraints (FK → PK)", font=font_sub_title, fill=subtitle_color)
        draw.line([60 * scale, 72 * scale, (canvas_w - 60 * scale), 72 * scale], fill=divider_color, width=scale)

        col_meta = {}
        cur_y = 100 * scale

        for t in tables:
            t_name = t["name"]
            draw.text((table_x, cur_y), t_name, font=font_tbl_title, fill=tbl_name_color)
            cells_y = cur_y + title_gap

            cx = table_x
            for col_name, is_pk in t["cols"]:
                use_font = font_cell_pk if is_pk else font_cell_reg
                bbox = use_font.getbbox(col_name)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
                w = max(tw + pad_x, 62 * scale)

                c_bg = cell_pk_bg if is_pk else cell_reg_bg
                c_border = cell_pk_border if is_pk else cell_reg_border
                c_text = cell_pk_text if is_pk else cell_reg_text

                draw.rectangle([cx, cells_y, cx + w, cells_y + cell_h], fill=c_bg, outline=c_border, width=scale)
                tx = cx + (w - tw) / 2
                ty = cells_y + (cell_h - th) / 2 - 1 * scale
                draw.text((tx, ty), col_name, font=use_font, fill=c_text)

                if is_pk:
                    ul_y = ty + th + 2 * scale
                    draw.line([tx, ul_y, tx + tw, ul_y], fill=pk_underline_color, width=scale)

                col_meta[(t_name, col_name)] = {
                    "cx": cx,
                    "w": w,
                    "center_x": cx + w / 2,
                    "y_top": cells_y,
                    "y_bottom": cells_y + cell_h
                }
                cx += w

            cur_y = cells_y + cell_h + table_inter_gap

        # Multiple arrowheads spacing
        dst_counts = {}
        for src_t, src_c, dst_t, dst_c, ch in fks:
            k = (dst_t, dst_c)
            dst_counts[k] = dst_counts.get(k, 0) + 1

        dst_current_idx = {}

        for src_t, src_c, dst_t, dst_c, ch in fks:
            s = col_meta[(src_t, src_c)]
            d = col_meta[(dst_t, dst_c)]

            tot = dst_counts[(dst_t, dst_c)]
            idx = dst_current_idx.get((dst_t, dst_c), 0)
            dst_current_idx[(dst_t, dst_c)] = idx + 1

            if tot == 1:
                target_x = d["center_x"]
            else:
                spacing = 8 * scale
                start_offset = -((tot - 1) * spacing) / 2
                target_x = d["center_x"] + start_offset + (idx * spacing)

            source_x = s["center_x"]
            source_y = s["y_bottom"]
            target_y = d["y_bottom"]

            channel_x = left_channels[ch]
            exit_y = source_y + (16 + ch * 3.5) * scale
            feeder_y = target_y + (8 + ch * 2.5) * scale

            points = [
                (source_x, source_y),
                (source_x, exit_y),
                (channel_x, exit_y),
                (channel_x, feeder_y),
                (target_x, feeder_y),
                (target_x, target_y)
            ]

            for i in range(len(points) - 1):
                draw.line([points[i], points[i+1]], fill=arrow_color, width=scale)

            # FK source circle
            dot_r = 2 * scale
            draw.ellipse([source_x - dot_r, source_y - dot_r, source_x + dot_r, source_y + dot_r], fill=arrow_color)

            # Sharp arrowhead pointing UP into PK
            ah = 5 * scale
            aw = 3.5 * scale
            draw.polygon([(target_x, target_y), (target_x - aw, target_y + ah), (target_x + aw, target_y + ah)], fill=arrow_color)

        return img

    def render_svg(theme="dark"):
        if theme == "dark":
            bg_color = "#0d1117"
            title_color = "#f0f6fc"
            subtitle_color = "#8b949e"
            divider_color = "#30363d"
            tbl_name_color = "#f0f6fc"
            cell_reg_bg = "#161b22"
            cell_reg_border = "#30363d"
            cell_reg_text = "#c9d1d9"
            cell_pk_bg = "#21262d"
            cell_pk_border = "#58a6ff"
            cell_pk_text = "#ffffff"
            pk_underline_color = "#58a6ff"
            arrow_color = "#58a6ff"
        else:
            bg_color = "#ffffff"
            title_color = "#1f2328"
            subtitle_color = "#656d76"
            divider_color = "#d0d7de"
            tbl_name_color = "#1f2328"
            cell_reg_bg = "#f6f8fa"
            cell_reg_border = "#202124"
            cell_reg_text = "#202124"
            cell_pk_bg = "#e8eaed"
            cell_pk_border = "#202124"
            cell_pk_text = "#202124"
            pk_underline_color = "#202124"
            arrow_color = "#202124"

        w_svg = 1200
        h_svg = 1380
        t_x = 160
        c_h = 24
        t_gap = 14
        t_inter_gap = 46
        p_x = 14
        l_channels = {1: 138, 2: 116, 3: 94, 4: 72, 5: 50, 6: 28}

        svg = []
        svg.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w_svg} {h_svg}" width="100%" height="100%" style="background-color: {bg_color}; font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Helvetica, Arial, sans-serif;">')
        svg.append('<defs>')
        svg.append(f'  <marker id="arrow-{theme}" viewBox="0 0 10 10" refX="5" refY="3" markerWidth="6" markerHeight="6" orient="auto">')
        svg.append(f'    <path d="M 0 6 L 5 0 L 10 6 z" fill="{arrow_color}" />')
        svg.append('  </marker>')
        svg.append('</defs>')

        # Header
        svg.append(f'<text x="60" y="42" fill="{title_color}" font-size="18" font-weight="bold">GridRestore Relational Database Schema</text>')
        svg.append(f'<text x="60" y="62" fill="{subtitle_color}" font-size="10">Elmasri–Navathe Relational Schema Notation • Contiguous Attribute Boxes • Directed Referential Integrity Constraints (FK → PK)</text>')
        svg.append(f'<line x1="60" y1="72" x2="{w_svg - 60}" y2="72" stroke="{divider_color}" stroke-width="1"/>')

        col_meta_svg = {}
        c_y = 100

        for t in tables:
            t_name = t["name"]
            svg.append(f'<text x="{t_x}" y="{c_y + 10}" fill="{tbl_name_color}" font-size="12" font-weight="bold">{t_name}</text>')
            cells_y = c_y + t_gap

            cx = t_x
            for col_name, is_pk in t["cols"]:
                tw = len(col_name) * 7.2
                w = max(tw + p_x, 62)
                c_bg = cell_pk_bg if is_pk else cell_reg_bg
                c_border = cell_pk_border if is_pk else cell_reg_border
                c_text = cell_pk_text if is_pk else cell_reg_text
                f_weight = "bold" if is_pk else "normal"

                svg.append(f'<rect x="{cx}" y="{cells_y}" width="{w}" height="{c_h}" fill="{c_bg}" stroke="{c_border}" stroke-width="1"/>')
                tx = cx + w / 2
                ty = cells_y + c_h / 2 + 4
                text_decor = f' text-decoration="underline" text-decoration-color="{pk_underline_color}"' if is_pk else ''
                svg.append(f'<text x="{tx}" y="{ty}" fill="{c_text}" font-size="9.5" font-weight="{f_weight}" text-anchor="middle"{text_decor}>{col_name}</text>')

                col_meta_svg[(t_name, col_name)] = {
                    "cx": cx,
                    "w": w,
                    "center_x": cx + w / 2,
                    "y_top": cells_y,
                    "y_bottom": cells_y + c_h
                }
                cx += w

            c_y = cells_y + c_h + t_inter_gap

        dst_counts = {}
        for src_t, src_c, dst_t, dst_c, ch in fks:
            k = (dst_t, dst_c)
            dst_counts[k] = dst_counts.get(k, 0) + 1

        dst_current_idx = {}

        for src_t, src_c, dst_t, dst_c, ch in fks:
            s = col_meta_svg[(src_t, src_c)]
            d = col_meta_svg[(dst_t, dst_c)]

            tot = dst_counts[(dst_t, dst_c)]
            idx = dst_current_idx.get((dst_t, dst_c), 0)
            dst_current_idx[(dst_t, dst_c)] = idx + 1

            if tot == 1:
                target_x = d["center_x"]
            else:
                spacing = 8
                start_offset = -((tot - 1) * spacing) / 2
                target_x = d["center_x"] + start_offset + (idx * spacing)

            source_x = s["center_x"]
            source_y = s["y_bottom"]
            target_y = d["y_bottom"]

            channel_x = l_channels[ch]
            exit_y = source_y + 16 + ch * 3.5
            feeder_y = target_y + 8 + ch * 2.5

            path_d = f"M {source_x} {source_y} L {source_x} {exit_y} L {channel_x} {exit_y} L {channel_x} {feeder_y} L {target_x} {feeder_y} L {target_x} {target_y}"
            svg.append(f'<path d="{path_d}" fill="none" stroke="{arrow_color}" stroke-width="1.2" marker-end="url(#arrow-{theme})"/>')
            svg.append(f'<circle cx="{source_x}" cy="{source_y}" r="2" fill="{arrow_color}"/>')

        svg.append('</svg>')
        return "\n".join(svg)

    # 1. Dark Theme PNG (default)
    p_dark = render_png("dark")
    p_dark.save(r"c:\Users\Prabha Prabhu\Downloads\GridRestore\docs\figures\relational_schema_diagram.png", "PNG")

    # 2. Light Theme PNG (textbook scan match)
    p_light = render_png("light")
    p_light.save(r"c:\Users\Prabha Prabhu\Downloads\GridRestore\docs\figures\relational_schema_diagram_light.png", "PNG")

    # 3. Dark Theme SVG
    svg_dark = render_svg("dark")
    with open(r"c:\Users\Prabha Prabhu\Downloads\GridRestore\docs\figures\relational_schema_diagram.svg", "w", encoding="utf-8") as f:
        f.write(svg_dark)

    # 4. Light Theme SVG
    svg_light = render_svg("light")
    with open(r"c:\Users\Prabha Prabhu\Downloads\GridRestore\docs\figures\relational_schema_diagram_light.svg", "w", encoding="utf-8") as f:
        f.write(svg_light)

    print("Successfully generated all 4 diagrams: dark PNG, light PNG, dark SVG, light SVG!")

if __name__ == "__main__":
    generate_schema_diagrams()
