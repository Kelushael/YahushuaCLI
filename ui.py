#!/usr/bin/env python3
"""
sovereign-agent/ui.py
Generate simple HTML UIs that can be opened in browser.
Uses the sovereign orange/neon theme (from sovereign-assesmograph.html CSS variables).
Clean, responsive, works on mobile. No frameworks, vanilla HTML/CSS/JS.
"""

import os
import json
import tempfile
from pathlib import Path
from datetime import datetime

UI_DIR = Path.home() / ".config" / "sovereign-agent" / "ui"


def _ensure_dir():
    """Create UI output directory if it doesn't exist."""
    UI_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# Theme CSS (sovereign orange/neon aesthetic)
# ============================================================

THEME_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Orbitron:wght@400;700;900&display=swap');

:root {
    --orange: #ff8c00;
    --neon-orange: #ffa500;
    --deep-orange: #e65100;
    --cyan: #00dcff;
    --lime: #39ff64;
    --pink: #ff69b4;
    --gold: #ffc832;
    --red: #ff3333;
    --dark: #080810;
    --card: #0d0d1a;
    --border: #1a1a2e;
    --text: #c8dcff;
    --text-dim: #555569;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    background: var(--dark);
    color: var(--text);
    font-family: 'Share Tech Mono', monospace;
    min-height: 100vh;
    overflow-x: hidden;
    padding: 0;
}

body::before {
    content: '';
    position: fixed; inset: 0;
    background: repeating-linear-gradient(
        0deg, transparent, transparent 2px,
        rgba(0,0,0,0.06) 2px, rgba(0,0,0,0.06) 4px
    );
    pointer-events: none; z-index: 999;
}

.container {
    max-width: 960px;
    margin: 0 auto;
    padding: 40px 20px;
}

.header {
    text-align: center;
    padding: 40px 20px 30px;
}

.header h1 {
    font-family: 'Orbitron', sans-serif;
    font-size: clamp(1.4rem, 4vw, 2.5rem);
    font-weight: 900;
    color: var(--orange);
    text-shadow: 0 0 30px rgba(255,140,0,0.5), 0 0 60px rgba(255,140,0,0.15);
    letter-spacing: 0.08em;
    text-transform: uppercase;
}

.header .subtitle {
    color: var(--text-dim);
    font-size: 0.85rem;
    margin-top: 8px;
    letter-spacing: 0.15em;
}

.section {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 24px;
    margin-bottom: 20px;
}

.section h2 {
    font-family: 'Orbitron', sans-serif;
    font-size: 1rem;
    color: var(--orange);
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin-bottom: 16px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border);
}

.section p, .section li {
    line-height: 1.7;
    color: var(--text);
}

.section ul {
    list-style: none;
    padding: 0;
}

.section ul li {
    padding: 6px 0;
    border-bottom: 1px solid rgba(26, 26, 46, 0.5);
}

.section ul li::before {
    content: '> ';
    color: var(--orange);
    font-weight: bold;
}

.status-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
    gap: 16px;
}

.status-card {
    background: rgba(13, 13, 26, 0.8);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 16px;
}

.status-card .label {
    font-size: 0.75rem;
    color: var(--text-dim);
    text-transform: uppercase;
    letter-spacing: 0.1em;
}

.status-card .value {
    font-size: 1.4rem;
    font-weight: bold;
    color: var(--neon-orange);
    margin-top: 4px;
}

.status-card .value.ok { color: var(--lime); }
.status-card .value.warn { color: var(--gold); }
.status-card .value.error { color: var(--red); }

table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 12px;
}

th {
    text-align: left;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--orange);
    padding: 8px;
    border-bottom: 2px solid var(--border);
}

td {
    padding: 8px;
    border-bottom: 1px solid rgba(26, 26, 46, 0.5);
    color: var(--text);
}

tr:hover td {
    background: rgba(255, 140, 0, 0.03);
}

.btn {
    display: inline-block;
    padding: 10px 24px;
    background: transparent;
    border: 1px solid var(--orange);
    color: var(--orange);
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.9rem;
    cursor: pointer;
    border-radius: 4px;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    transition: all 0.2s;
}

.btn:hover {
    background: var(--orange);
    color: var(--dark);
    box-shadow: 0 0 20px rgba(255, 140, 0, 0.3);
}

.btn-primary {
    background: var(--orange);
    color: var(--dark);
}

.btn-primary:hover {
    background: var(--neon-orange);
    box-shadow: 0 0 25px rgba(255, 165, 0, 0.4);
}

input, textarea, select {
    width: 100%;
    padding: 10px 12px;
    background: var(--dark);
    border: 1px solid var(--border);
    color: var(--text);
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.9rem;
    border-radius: 4px;
    margin-top: 6px;
}

input:focus, textarea:focus, select:focus {
    outline: none;
    border-color: var(--orange);
    box-shadow: 0 0 10px rgba(255, 140, 0, 0.15);
}

label {
    display: block;
    font-size: 0.8rem;
    color: var(--text-dim);
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin-bottom: 4px;
    margin-top: 16px;
}

label:first-child {
    margin-top: 0;
}

.form-group {
    margin-bottom: 16px;
}

.footer {
    text-align: center;
    padding: 30px 20px;
    color: var(--text-dim);
    font-size: 0.75rem;
    letter-spacing: 0.15em;
}

@media (max-width: 600px) {
    .container { padding: 20px 12px; }
    .section { padding: 16px; }
    .status-grid { grid-template-columns: 1fr; }
}
"""


# ============================================================
# HTML generators
# ============================================================

def _wrap_html(title, body_html, extra_css="", extra_js=""):
    """Wrap content in a full HTML document with the sovereign theme."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} -- SOVEREIGN AGENT</title>
<style>
{THEME_CSS}
{extra_css}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>{title}</h1>
        <div class="subtitle">SOVEREIGN AGENT // {timestamp}</div>
    </div>
{body_html}
    <div class="footer">SOVEREIGN AGENT &mdash; ZERO-CONFIG AUTONOMOUS AI</div>
</div>
{f'<script>{extra_js}</script>' if extra_js else ''}
</body>
</html>"""


def create_dashboard(title, sections):
    """Create a dashboard HTML page.

    Args:
        title: page title
        sections: list of dicts, each with:
            - title: section heading
            - type: "text", "list", "table", "status_grid", "html"
            - content: depends on type
              - text: string
              - list: list of strings
              - table: {"headers": [...], "rows": [[...]]}
              - status_grid: [{"label": ..., "value": ..., "status": "ok"|"warn"|"error"}]
              - html: raw HTML string

    Returns:
        dict with path to the HTML file
    """
    _ensure_dir()

    body_parts = []
    for section in sections:
        sec_title = section.get("title", "")
        sec_type = section.get("type", "text")
        content = section.get("content", "")

        html = f'    <div class="section">\n'
        if sec_title:
            html += f'        <h2>{sec_title}</h2>\n'

        if sec_type == "text":
            html += f'        <p>{content}</p>\n'

        elif sec_type == "list":
            html += '        <ul>\n'
            items = content if isinstance(content, list) else [content]
            for item in items:
                html += f'            <li>{item}</li>\n'
            html += '        </ul>\n'

        elif sec_type == "table":
            headers = content.get("headers", []) if isinstance(content, dict) else []
            rows = content.get("rows", []) if isinstance(content, dict) else []
            html += '        <table>\n'
            if headers:
                html += '            <thead><tr>\n'
                for h in headers:
                    html += f'                <th>{h}</th>\n'
                html += '            </tr></thead>\n'
            html += '            <tbody>\n'
            for row in rows:
                html += '            <tr>\n'
                for cell in row:
                    html += f'                <td>{cell}</td>\n'
                html += '            </tr>\n'
            html += '            </tbody>\n'
            html += '        </table>\n'

        elif sec_type == "status_grid":
            cards = content if isinstance(content, list) else []
            html += '        <div class="status-grid">\n'
            for card in cards:
                status_class = card.get("status", "")
                html += f'            <div class="status-card">\n'
                html += f'                <div class="label">{card.get("label", "")}</div>\n'
                html += f'                <div class="value {status_class}">{card.get("value", "")}</div>\n'
                html += f'            </div>\n'
            html += '        </div>\n'

        elif sec_type == "html":
            html += f'        {content}\n'

        html += '    </div>\n'
        body_parts.append(html)

    body_html = "\n".join(body_parts)
    full_html = _wrap_html(title, body_html)

    # Write to file
    safe_title = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in title.lower())
    filename = f"{safe_title}.html"
    filepath = UI_DIR / filename

    with open(filepath, "w") as f:
        f.write(full_html)

    return {"path": str(filepath), "filename": filename}


def create_form(title, fields, action_url=None, method="POST"):
    """Create an HTML form page.

    Args:
        title: page/form title
        fields: list of dicts, each with:
            - name: field name
            - label: display label
            - type: "text", "textarea", "number", "email", "password", "select"
            - options: list of strings (for select type)
            - required: bool
            - placeholder: string
            - default: default value
        action_url: URL to POST to (default: javascript alert with form data)
        method: HTTP method (default POST)

    Returns:
        dict with path to the HTML file
    """
    _ensure_dir()

    form_fields = []
    for field in fields:
        fname = field.get("name", "field")
        flabel = field.get("label", fname)
        ftype = field.get("type", "text")
        freq = field.get("required", False)
        fplaceholder = field.get("placeholder", "")
        fdefault = field.get("default", "")
        req_attr = ' required' if freq else ''

        html = f'        <div class="form-group">\n'
        html += f'            <label for="{fname}">{flabel}</label>\n'

        if ftype == "textarea":
            html += f'            <textarea id="{fname}" name="{fname}" rows="4" placeholder="{fplaceholder}"{req_attr}>{fdefault}</textarea>\n'
        elif ftype == "select":
            options = field.get("options", [])
            html += f'            <select id="{fname}" name="{fname}"{req_attr}>\n'
            for opt in options:
                selected = ' selected' if opt == fdefault else ''
                html += f'                <option value="{opt}"{selected}>{opt}</option>\n'
            html += f'            </select>\n'
        else:
            html += f'            <input type="{ftype}" id="{fname}" name="{fname}" value="{fdefault}" placeholder="{fplaceholder}"{req_attr}>\n'

        html += '        </div>\n'
        form_fields.append(html)

    fields_html = "\n".join(form_fields)

    if action_url:
        form_action = f'action="{action_url}" method="{method}"'
        submit_js = ""
    else:
        form_action = 'onsubmit="return handleSubmit(event)"'
        submit_js = """
function handleSubmit(e) {
    e.preventDefault();
    const form = e.target;
    const data = {};
    new FormData(form).forEach((v, k) => { data[k] = v; });
    const pre = document.getElementById('result');
    pre.textContent = JSON.stringify(data, null, 2);
    pre.style.display = 'block';
    return false;
}
"""

    body_html = f"""
    <div class="section">
        <h2>{title}</h2>
        <form {form_action}>
{fields_html}
            <div class="form-group" style="margin-top: 24px;">
                <button type="submit" class="btn btn-primary">Submit</button>
            </div>
        </form>
        <pre id="result" style="display:none; margin-top:20px; padding:16px; background:var(--dark); border:1px solid var(--border); border-radius:4px; color:var(--lime); white-space:pre-wrap;"></pre>
    </div>
"""

    full_html = _wrap_html(title, body_html, extra_js=submit_js)

    safe_title = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in title.lower())
    filename = f"{safe_title}_form.html"
    filepath = UI_DIR / filename

    with open(filepath, "w") as f:
        f.write(full_html)

    return {"path": str(filepath), "filename": filename}


def create_ui(ui_type, title, data):
    """Unified UI creation entry point for the agent tool.

    Args:
        ui_type: "dashboard" or "form"
        title: page title
        data: JSON data — sections list for dashboard, fields list for form

    Returns:
        dict with path and status
    """
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            return {"success": False, "error": "Invalid JSON data"}

    if ui_type == "dashboard":
        result = create_dashboard(title, data)
        return {"success": True, **result}
    elif ui_type == "form":
        result = create_form(title, data)
        return {"success": True, **result}
    else:
        return {"success": False, "error": f"Unknown UI type: {ui_type}. Use 'dashboard' or 'form'."}


if __name__ == "__main__":
    print("Sovereign Agent -- UI Generator")
    print(f"UI output dir: {UI_DIR}")
    print()

    # Demo: create a test dashboard
    result = create_dashboard("Test Dashboard", [
        {
            "title": "Status",
            "type": "status_grid",
            "content": [
                {"label": "Agent", "value": "ONLINE", "status": "ok"},
                {"label": "Model", "value": "LOADING", "status": "warn"},
                {"label": "Health", "value": "3 CHECKS", "status": "ok"},
            ]
        },
        {
            "title": "Recent Activity",
            "type": "list",
            "content": ["Started agent", "Loaded 3 tools", "Connected to model"]
        },
    ])
    print(f"Dashboard created: {result['path']}")
