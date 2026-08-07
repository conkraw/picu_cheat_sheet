"""
PICU Cheat Sheet Builder
========================

A single-file Streamlit app for building visual, one-page clinical guides in a
consistent PICU teaching style.

Core features
-------------
- Free-text, reorderable sections
- Content templates: troubleshooting, formula review, management approach,
  disease review, rounds guide, diagnosis review, and blank
- Multiple visual themes
- Section-level graphics (PNG/JPG/WebP), captions, colors, and column spans
- JSON import/export for AI-assisted drafting
- GitHub archive save/load/delete using the GitHub Contents API
- Styled PDF export using ReportLab

Install
-------
pip install streamlit reportlab pillow requests

Run
---
streamlit run picu_cheat_sheet_builder.py

Optional .streamlit/secrets.toml
--------------------------------
[github]
token = "github_pat_..."
repo = "OWNER/REPOSITORY"
branch = "main"
base_path = "picu_cheat_sheets"
"""

from __future__ import annotations

import base64
import copy
import hashlib
import html
import io
import json
import re
import textwrap
import uuid
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional, Sequence, Tuple
from xml.sax.saxutils import escape as xml_escape

import requests
import streamlit as st
import streamlit.components.v1 as components
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, letter, landscape, portrait
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    Image as RLImage,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


APP_VERSION = "1.0.0"
SCHEMA_VERSION = 1


# -----------------------------------------------------------------------------
# Visual themes
# -----------------------------------------------------------------------------

THEMES: Dict[str, Dict[str, Any]] = {
    "Classic PICU": {
        "navy": "#082E5C",
        "title_text": "#FFFFFF",
        "page_bg": "#F7FAFC",
        "card_bg": "#FFFFFF",
        "text": "#172033",
        "muted": "#526277",
        "border": "#A8BED3",
        "palette": [
            "#0B57A4",  # blue
            "#20834A",  # green
            "#6C3CA3",  # purple
            "#C23A32",  # red
            "#C68A00",  # gold
            "#087C86",  # teal
        ],
        "footer_bg": "#082E5C",
        "footer_text": "#FFFFFF",
    },
    "Troubleshooting Blue + Red": {
        "navy": "#0B315D",
        "title_text": "#FFFFFF",
        "page_bg": "#FBFCFE",
        "card_bg": "#FFFFFF",
        "text": "#1A2433",
        "muted": "#5D6B7D",
        "border": "#B5C3D2",
        "palette": ["#175DA8", "#D24A43", "#2C7F6B", "#7D4AA8", "#D59017", "#3F6B8F"],
        "footer_bg": "#EAF1F8",
        "footer_text": "#17324E",
    },
    "Calm Teal": {
        "navy": "#0C4650",
        "title_text": "#FFFFFF",
        "page_bg": "#F4FAFA",
        "card_bg": "#FFFFFF",
        "text": "#183137",
        "muted": "#557278",
        "border": "#A8C9CC",
        "palette": ["#0E7781", "#3B8F5B", "#406FA8", "#8A5AA6", "#B87916", "#B84D4A"],
        "footer_bg": "#0C4650",
        "footer_text": "#FFFFFF",
    },
    "Warm Teaching": {
        "navy": "#183A5A",
        "title_text": "#FFFFFF",
        "page_bg": "#FFF9F1",
        "card_bg": "#FFFFFF",
        "text": "#2A2A2A",
        "muted": "#665F57",
        "border": "#D8C7B1",
        "palette": ["#2D6C9F", "#4F8A55", "#7D5AA6", "#C54F42", "#C68B18", "#21818A"],
        "footer_bg": "#E9DCCB",
        "footer_text": "#314252",
    },
    "High Contrast Print": {
        "navy": "#111111",
        "title_text": "#FFFFFF",
        "page_bg": "#FFFFFF",
        "card_bg": "#FFFFFF",
        "text": "#111111",
        "muted": "#444444",
        "border": "#222222",
        "palette": ["#111111", "#3C3C3C", "#575757", "#707070", "#898989", "#A0A0A0"],
        "footer_bg": "#111111",
        "footer_text": "#FFFFFF",
    },
}


SECTION_KINDS = {
    "Teaching card": "card",
    "Checklist": "checklist",
    "Formula / definition": "formula",
    "Step / algorithm": "step",
    "Warning / pitfall": "warning",
    "Clinical pearl": "pearl",
    "Bottom line banner": "bottom_line",
}
KIND_LABELS = {value: key for key, value in SECTION_KINDS.items()}

SPAN_OPTIONS = {
    "1 column": 1,
    "2 columns": 2,
    "Full width": 3,
}
SPAN_LABELS = {value: key for key, value in SPAN_OPTIONS.items()}

GRAPHIC_POSITIONS = ["Right", "Left", "Top", "Bottom", "Full width"]


# -----------------------------------------------------------------------------
# Content templates
# -----------------------------------------------------------------------------


def section(
    title: str,
    body: str = "",
    *,
    kind: str = "card",
    span: int = 1,
    accent_index: int = 0,
    pearl: str = "",
) -> Dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "title": title,
        "body": body,
        "kind": kind,
        "span": span,
        "accent_index": accent_index,
        "custom_accent": "",
        "pearl": pearl,
        "graphic_b64": "",
        "graphic_name": "",
        "graphic_mime": "",
        "graphic_caption": "",
        "graphic_position": "Right",
    }


TEMPLATE_LIBRARY: Dict[str, Dict[str, Any]] = {
    "Troubleshooting guide": {
        "subtitle": "Confirm the problem, identify the cause, intervene, and reassess",
        "sections": [
            section("Confirm the problem", "- Verify the measurement\n- Review the trend\n- Correlate with the bedside examination", kind="checklist", span=1, accent_index=0),
            section("1. Patient", "What patient factors could explain the finding?", kind="step", span=1, accent_index=0),
            section("2. Circuit / device", "Check position, patency, connections, leaks, and equipment function.", kind="step", span=1, accent_index=1),
            section("3. Settings / treatment", "Review the current support, recent changes, and whether the intervention matches the physiology.", kind="step", span=1, accent_index=2),
            section("4. Disease / physiology", "Consider worsening disease, a new process, or a non-primary-system cause.", kind="step", span=1, accent_index=3),
            section("Immediate management", "- Treat reversible causes first\n- Adjust support gradually\n- Avoid changing multiple variables at once", kind="checklist", span=2, accent_index=0),
            section("Reassessment", "Define what will be rechecked, when it will be rechecked, and what constitutes improvement or escalation.", kind="step", span=1, accent_index=2),
            section("Do not miss", "List dangerous mimics, iatrogenic causes, and non-primary-system contributors.", kind="warning", span=2, accent_index=3),
            section("Target guidance", "State the target range and note when an individualized target is appropriate.", kind="formula", span=1, accent_index=4),
            section("Bottom line", "Always reassess the patient as a whole. Trend the response rather than relying on a single number.", kind="bottom_line", span=3, accent_index=0),
        ],
    },
    "Formula review": {
        "subtitle": "What the number means, how it is calculated, and how to use it clinically",
        "sections": [
            section("1. What is it?", "Define the variable in one or two bedside-focused sentences.", span=1, accent_index=0),
            section("2. Where is it measured?", "Clarify the ideal measurement and what is commonly used in practice.", span=1, accent_index=5),
            section("3. Normal / target", "Give the usual range, important caveats, and why trends matter.", kind="formula", span=1, accent_index=2),
            section("4. Formula", "Write the formula here.\n\nDefine every variable and unit.", kind="formula", span=1, accent_index=4),
            section("Low value", "Organize causes into clinically useful categories.", span=1, accent_index=3),
            section("High value", "Explain when a high value is reassuring and when it is not.", span=1, accent_index=2),
            section("Worked example", "Show a brief calculation and then interpret it clinically.", kind="formula", span=2, accent_index=0),
            section("Bedside checklist", "- Measurement quality\n- Related vital signs\n- Hemoglobin / oxygen content\n- Perfusion / output\n- Metabolic demand", kind="checklist", span=1, accent_index=5),
            section("Bottom line", "Never interpret a calculated value in isolation. Pair it with the examination, trends, and the clinical context.", kind="bottom_line", span=3, accent_index=0),
        ],
    },
    "Approach to management": {
        "subtitle": "A stepwise bedside approach: stabilize, identify the physiology, treat, and reassess",
        "sections": [
            section("When to use this approach", "Define the patient population, trigger, or clinical scenario.", span=1, accent_index=0),
            section("Red flags / contraindications", "List findings that require immediate escalation or a different pathway.", kind="warning", span=2, accent_index=3),
            section("Step 1 - Stabilize", "What must happen immediately? Include monitoring and safety actions.", kind="step", span=1, accent_index=0),
            section("Step 2 - Define the problem", "Separate oxygenation, ventilation, perfusion, neurologic, or other physiologic problems.", kind="step", span=1, accent_index=1),
            section("Step 3 - Choose the intervention", "Match the intervention to the dominant physiology.", kind="step", span=1, accent_index=2),
            section("Step 4 - Titrate", "Describe what to adjust first, how much, and what variables should be held constant.", kind="step", span=1, accent_index=4),
            section("Step 5 - Monitor response", "State the bedside signs, laboratory data, and timing of reassessment.", kind="checklist", span=1, accent_index=5),
            section("When to escalate", "Define failure criteria and the next level of support.", kind="warning", span=1, accent_index=3),
            section("Common pitfalls", "List frequent errors, delayed actions, and false reassurance.", kind="pearl", span=2, accent_index=4),
            section("Bottom line", "Match the treatment to the physiology, define success before starting, and escalate before the patient is exhausted.", kind="bottom_line", span=3, accent_index=0),
        ],
    },
    "Disease review": {
        "subtitle": "Recognition, physiology, evaluation, management, and bedside teaching points",
        "sections": [
            section("What is it?", "Brief definition and why it matters in the PICU.", span=1, accent_index=0),
            section("Core physiology", "Explain the mechanism in clinically useful language.", span=2, accent_index=2),
            section("How it presents", "- Symptoms\n- Examination findings\n- Typical trajectory", kind="checklist", span=1, accent_index=1),
            section("Diagnosis", "State how the diagnosis is made and important limitations.", span=1, accent_index=0),
            section("Differential diagnosis", "Organize mimics into memorable categories.", span=1, accent_index=4),
            section("Initial evaluation", "List the studies that change immediate management.", kind="checklist", span=1, accent_index=5),
            section("Management", "Prioritize stabilization, disease-specific treatment, and supportive care.", span=2, accent_index=2),
            section("Escalation / ICU triggers", "Define when support should increase or consultation is needed.", kind="warning", span=1, accent_index=3),
            section("Pitfalls and pearls", "Highlight common misconceptions and one or two memorable teaching points.", kind="pearl", span=2, accent_index=4),
            section("Bottom line", "Write the single message a learner should remember on rounds tomorrow.", kind="bottom_line", span=3, accent_index=0),
        ],
    },
    "Diagnosis review": {
        "subtitle": "How to recognize it, confirm it, distinguish mimics, and act",
        "sections": [
            section("Clinical trigger", "What finding or pattern should make the learner consider this diagnosis?", span=1, accent_index=0),
            section("Key diagnostic features", "List the features that increase or decrease the likelihood.", kind="checklist", span=2, accent_index=1),
            section("Immediate threats", "What must be recognized or treated before the diagnosis is fully confirmed?", kind="warning", span=1, accent_index=3),
            section("Diagnostic approach", "Provide a practical sequence: bedside assessment, initial studies, confirmatory testing.", kind="step", span=2, accent_index=0),
            section("Important mimics", "Group the differential into clinically useful categories.", span=1, accent_index=4),
            section("How to interpret the tests", "Explain false positives, false negatives, and the role of pretest probability.", kind="formula", span=2, accent_index=2),
            section("First actions after diagnosis", "State isolation, consultation, treatment, and monitoring priorities.", kind="checklist", span=1, accent_index=5),
            section("Bottom line", "Recognize the pattern, address immediate threats, and use testing to refine - not replace - clinical judgment.", kind="bottom_line", span=3, accent_index=0),
        ],
    },
    "Rounds guide": {
        "subtitle": "What every learner should report, interpret, and decide at the bedside",
        "sections": [
            section("Why is the patient receiving this therapy?", "List the major indications or goals.", kind="checklist", span=1, accent_index=0),
            section("Know the current support", "Summarize the mode, dose, settings, or major treatment variables.", span=1, accent_index=1),
            section("What to report on rounds", "Create a concise table-like list of the essential variables and what each means.", kind="checklist", span=2, accent_index=0),
            section("What does the trend show?", "Interpret changes over time rather than reporting isolated values.", span=1, accent_index=2),
            section("Questions to answer before rounds", "- Why is support still needed?\n- Is the patient improving?\n- Is the current target appropriate?\n- Can anything be weaned today?", kind="checklist", span=1, accent_index=4),
            section("If an alarm or sudden change occurs", "Use a short safety mnemonic or prioritized troubleshooting sequence.", kind="warning", span=1, accent_index=3),
            section("Example presentation", "Write a model one-paragraph bedside presentation.", span=2, accent_index=5),
            section("Bottom line", "Do not simply report settings or numbers - interpret what they mean and state the next step.", kind="bottom_line", span=3, accent_index=0),
        ],
    },
    "Blank canvas": {
        "subtitle": "Build a custom clinical teaching guide",
        "sections": [
            section("Section 1", "Add your teaching content here.", span=1, accent_index=0),
            section("Section 2", "Add your teaching content here.", span=1, accent_index=1),
            section("Bottom line", "What should the learner remember?", kind="bottom_line", span=3, accent_index=0),
        ],
    },
}


# -----------------------------------------------------------------------------
# Document helpers
# -----------------------------------------------------------------------------


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_document(template_name: str = "Troubleshooting guide") -> Dict[str, Any]:
    template = TEMPLATE_LIBRARY[template_name]
    now = utc_now_iso()
    return {
        "schema_version": SCHEMA_VERSION,
        "app_version": APP_VERSION,
        "archive_id": uuid.uuid4().hex[:12],
        "github_filename": "",
        "title": "PICU Clinical Cheat Sheet",
        "subtitle": template["subtitle"],
        "author": "",
        "template_name": template_name,
        "theme_name": "Classic PICU",
        "orientation": "Landscape",
        "paper_size": "Letter",
        "show_numbers": True,
        "show_footer": True,
        "footer_text": "Clinical education guide - use clinical judgment and local policies.",
        "created_at": now,
        "updated_at": now,
        "sections": copy.deepcopy(template["sections"]),
    }


def normalize_section(raw: Dict[str, Any], index: int = 0) -> Dict[str, Any]:
    item = section(
        str(raw.get("title", f"Section {index + 1}")),
        str(raw.get("body", "")),
        kind=str(raw.get("kind", "card")),
        span=int(raw.get("span", 1) or 1),
        accent_index=int(raw.get("accent_index", index % 6) or 0),
        pearl=str(raw.get("pearl", "")),
    )
    item.update({k: v for k, v in raw.items() if k in item})
    item["id"] = str(raw.get("id") or uuid.uuid4())
    item["span"] = min(3, max(1, int(item.get("span", 1))))
    item["accent_index"] = max(0, int(item.get("accent_index", 0)))
    if item.get("graphic_position") not in GRAPHIC_POSITIONS:
        item["graphic_position"] = "Right"
    if item.get("kind") not in KIND_LABELS:
        item["kind"] = "card"
    return item


def normalize_document(raw: Dict[str, Any]) -> Dict[str, Any]:
    base = new_document(str(raw.get("template_name", "Blank canvas")) if str(raw.get("template_name", "")) in TEMPLATE_LIBRARY else "Blank canvas")
    allowed = set(base.keys())
    base.update({k: v for k, v in raw.items() if k in allowed and k != "sections"})
    base["schema_version"] = SCHEMA_VERSION
    base["app_version"] = APP_VERSION
    base["archive_id"] = str(raw.get("archive_id") or uuid.uuid4().hex[:12])
    base["sections"] = [normalize_section(x, i) for i, x in enumerate(raw.get("sections", [])) if isinstance(x, dict)]
    if not base["sections"]:
        base["sections"] = copy.deepcopy(TEMPLATE_LIBRARY["Blank canvas"]["sections"])
    if base.get("theme_name") not in THEMES:
        base["theme_name"] = "Classic PICU"
    if base.get("orientation") not in {"Landscape", "Portrait"}:
        base["orientation"] = "Landscape"
    if base.get("paper_size") not in {"Letter", "A4"}:
        base["paper_size"] = "Letter"
    base["updated_at"] = utc_now_iso()
    return base


def apply_template(doc: Dict[str, Any], template_name: str, preserve_title: bool = True) -> Dict[str, Any]:
    template = TEMPLATE_LIBRARY[template_name]
    updated = copy.deepcopy(doc)
    updated["template_name"] = template_name
    updated["subtitle"] = template["subtitle"]
    updated["sections"] = copy.deepcopy(template["sections"])
    updated["updated_at"] = utc_now_iso()
    if not preserve_title:
        updated["title"] = "PICU Clinical Cheat Sheet"
    return updated


def document_json_bytes(doc: Dict[str, Any]) -> bytes:
    payload = copy.deepcopy(doc)
    payload["updated_at"] = utc_now_iso()
    return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")


def slugify(value: str, max_length: int = 70) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return (value or "cheat-sheet")[:max_length].rstrip("-")


def current_filename(doc: Dict[str, Any], extension: str) -> str:
    return f"{slugify(str(doc.get('title', 'picu-cheat-sheet')))}.{extension.lstrip('.')}"


def data_uri(mime: str, b64_data: str) -> str:
    return f"data:{mime or 'image/png'};base64,{b64_data}"


def accent_for(section_data: Dict[str, Any], theme: Dict[str, Any]) -> str:
    custom = str(section_data.get("custom_accent", "")).strip()
    if re.fullmatch(r"#[0-9A-Fa-f]{6}", custom):
        return custom
    palette = theme["palette"]
    return palette[int(section_data.get("accent_index", 0)) % len(palette)]


def contrasting_text(hex_color: str) -> str:
    value = hex_color.lstrip("#")
    if len(value) != 6:
        return "#FFFFFF"
    r, g, b = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return "#111111" if luminance > 0.66 else "#FFFFFF"


# -----------------------------------------------------------------------------
# HTML preview
# -----------------------------------------------------------------------------


def preview_body_html(text: str) -> str:
    blocks: List[str] = []
    bullet_items: List[str] = []

    def flush_bullets() -> None:
        nonlocal bullet_items
        if bullet_items:
            blocks.append("<ul>" + "".join(f"<li>{item}</li>" for item in bullet_items) + "</ul>")
            bullet_items = []

    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            flush_bullets()
            blocks.append("<div class='space'></div>")
            continue
        escaped = html.escape(line)
        escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
        if line.startswith(("- ", "* ", "• ")):
            bullet_items.append(escaped[2:].strip())
        else:
            flush_bullets()
            blocks.append(f"<p>{escaped}</p>")
    flush_bullets()
    return "".join(blocks)


def build_preview_html(doc: Dict[str, Any]) -> str:
    theme = THEMES[doc["theme_name"]]
    orientation = doc.get("orientation", "Landscape")
    aspect = "11 / 8.5" if orientation == "Landscape" else "8.5 / 11"
    sections_html: List[str] = []

    for idx, sec in enumerate(doc["sections"], start=1):
        accent = accent_for(sec, theme)
        kind = sec.get("kind", "card")
        span = min(3, max(1, int(sec.get("span", 1))))
        number_html = f"<span class='badge'>{idx}</span>" if doc.get("show_numbers", True) and kind != "bottom_line" else ""
        image_html = ""
        if sec.get("graphic_b64"):
            image_html = (
                f"<figure><img src='{data_uri(sec.get('graphic_mime', 'image/png'), sec['graphic_b64'])}'/>"
                + (f"<figcaption>{html.escape(str(sec.get('graphic_caption', '')))}</figcaption>" if sec.get("graphic_caption") else "")
                + "</figure>"
            )
        body_html = preview_body_html(str(sec.get("body", "")))
        pearl_html = f"<div class='pearl'>{html.escape(str(sec.get('pearl', '')))}</div>" if sec.get("pearl") else ""
        position = str(sec.get("graphic_position", "Right")).lower().replace(" ", "-")
        classes = f"card kind-{kind} graphic-{position}"
        if kind == "bottom_line":
            sections_html.append(
                f"<section class='{classes}' style='grid-column: span {span}; --accent:{accent};'>"
                f"<div class='bottom-inner'><strong>{html.escape(str(sec.get('title', 'Bottom line')))}</strong>"
                f"<span>{body_html}</span></div></section>"
            )
        else:
            sections_html.append(
                f"<section class='{classes}' style='grid-column: span {span}; --accent:{accent};'>"
                f"<header>{number_html}<span>{html.escape(str(sec.get('title', 'Untitled')))}</span></header>"
                f"<div class='card-content'><div class='text'>{body_html}{pearl_html}</div>{image_html}</div>"
                f"</section>"
            )

    footer_html = ""
    if doc.get("show_footer", True):
        footer_html = f"<footer>{html.escape(str(doc.get('footer_text', '')))}</footer>"

    return f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<style>
* {{ box-sizing: border-box; }}
body {{ margin: 0; padding: 18px; background: #E7EDF3; font-family: Arial, Helvetica, sans-serif; color: {theme['text']}; }}
.page {{ width: 100%; max-width: 1180px; margin: 0 auto; aspect-ratio: {aspect}; min-height: 720px; background: {theme['page_bg']}; box-shadow: 0 8px 28px rgba(20,40,60,.18); display: flex; flex-direction: column; overflow: hidden; }}
.title {{ background: {theme['navy']}; color: {theme['title_text']}; padding: 18px 24px 14px; text-align: center; }}
.title h1 {{ margin: 0; font-size: 33px; line-height: 1.05; letter-spacing: .2px; }}
.title h2 {{ margin: 5px 0 0; font-size: 16px; font-weight: 600; font-style: italic; opacity: .95; }}
.grid {{ flex: 1; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 9px; padding: 11px; align-content: start; }}
.card {{ border: 1.5px solid {theme['border']}; border-radius: 10px; background: {theme['card_bg']}; overflow: hidden; min-height: 105px; box-shadow: 0 1px 2px rgba(0,0,0,.04); }}
.card header {{ min-height: 35px; padding: 7px 10px; color: white; background: var(--accent); font-size: 16px; font-weight: 800; display: flex; align-items: center; gap: 8px; }}
.badge {{ width: 24px; height: 24px; border-radius: 50%; background: rgba(255,255,255,.95); color: var(--accent); display: inline-flex; align-items: center; justify-content: center; font-size: 14px; flex: 0 0 auto; }}
.card-content {{ display: flex; gap: 9px; padding: 9px 11px 10px; align-items: center; }}
.card-content .text {{ flex: 1 1 62%; min-width: 0; }}
p {{ margin: 0 0 5px; font-size: 13px; line-height: 1.23; }}
ul {{ margin: 2px 0 4px 18px; padding: 0; }}
li {{ margin: 0 0 3px; font-size: 13px; line-height: 1.2; }}
.space {{ height: 3px; }}
figure {{ margin: 0; flex: 0 0 31%; text-align: center; }}
figure img {{ max-width: 100%; max-height: 125px; object-fit: contain; }}
figcaption {{ font-size: 9px; color: {theme['muted']}; margin-top: 2px; }}
.graphic-left .card-content {{ flex-direction: row-reverse; }}
.graphic-top .card-content {{ flex-direction: column-reverse; align-items: stretch; }}
.graphic-bottom .card-content {{ flex-direction: column; align-items: stretch; }}
.graphic-top figure, .graphic-bottom figure, .graphic-full-width figure {{ flex-basis: auto; }}
.graphic-top figure img, .graphic-bottom figure img, .graphic-full-width figure img {{ max-height: 155px; }}
.kind-warning {{ border-color: var(--accent); }}
.kind-warning .card-content {{ background: color-mix(in srgb, var(--accent) 7%, white); }}
.kind-formula .card-content {{ background: color-mix(in srgb, var(--accent) 6%, white); }}
.kind-formula p {{ font-size: 14px; font-weight: 600; }}
.kind-pearl .pearl, .pearl {{ margin-top: 7px; padding: 6px 8px; border-left: 4px solid var(--accent); background: #F3F7FA; font-size: 11px; font-weight: 700; }}
.kind-bottom_line {{ color: white; border-color: {theme['navy']}; background: {theme['navy']}; min-height: 48px; }}
.bottom-inner {{ height: 100%; padding: 11px 16px; display: flex; gap: 12px; align-items: center; justify-content: center; text-align: center; }}
.bottom-inner strong {{ color: #FFD54A; font-size: 16px; text-transform: uppercase; white-space: nowrap; }}
.bottom-inner span p {{ color: white; font-size: 13px; margin: 0; }}
footer {{ background: {theme['footer_bg']}; color: {theme['footer_text']}; padding: 6px 12px; font-size: 9px; text-align: center; }}
@media (max-width: 760px) {{
  .page {{ aspect-ratio: auto; min-height: 900px; }}
  .grid {{ grid-template-columns: 1fr; }}
  .card {{ grid-column: span 1 !important; }}
}}
</style>
</head>
<body>
<div class="page">
  <div class="title"><h1>{html.escape(str(doc.get('title', '')))}</h1><h2>{html.escape(str(doc.get('subtitle', '')))}</h2></div>
  <main class="grid">{''.join(sections_html)}</main>
  {footer_html}
</div>
</body>
</html>
"""


# -----------------------------------------------------------------------------
# PDF generation
# -----------------------------------------------------------------------------


def hex_color(value: str, fallback: str = "#000000") -> colors.Color:
    try:
        return colors.HexColor(value)
    except Exception:
        return colors.HexColor(fallback)


def prepare_inline_markup(text: str) -> str:
    escaped = xml_escape(str(text or ""))
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(
        r"\b(SpO|PaO|FiO|ScvO|SvO|ETCO|pCO|PaCO|HCO)(2|3)\b",
        r"\1<sub>\2</sub>",
        escaped,
    )
    escaped = escaped.replace("->", "&rarr;")
    return escaped


def body_flowables(text: str, style: ParagraphStyle, bullet_style: ParagraphStyle) -> List[Any]:
    flows: List[Any] = []
    pending_blank = False
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            pending_blank = True
            continue
        if pending_blank and flows:
            flows.append(Spacer(1, 2.5))
        pending_blank = False
        if line.startswith(("- ", "* ", "• ")):
            flows.append(Paragraph(prepare_inline_markup(line[2:].strip()), bullet_style, bulletText="•"))
        else:
            flows.append(Paragraph(prepare_inline_markup(line), style))
            flows.append(Spacer(1, 1.2))
    if not flows:
        flows.append(Paragraph(" ", style))
    return flows


def image_flowable(sec: Dict[str, Any], max_width: float, max_height: float) -> Optional[RLImage]:
    b64_value = str(sec.get("graphic_b64", ""))
    if not b64_value:
        return None
    try:
        raw = base64.b64decode(b64_value)
        pil = PILImage.open(io.BytesIO(raw))
        width_px, height_px = pil.size
        if width_px <= 0 or height_px <= 0:
            return None
        scale = min(max_width / width_px, max_height / height_px)
        width = max(20, width_px * scale)
        height = max(20, height_px * scale)
        return RLImage(io.BytesIO(raw), width=width, height=height)
    except Exception:
        return None


def make_card(sec: Dict[str, Any], idx: int, width: float, theme: Dict[str, Any], show_numbers: bool) -> Table:
    accent_hex = accent_for(sec, theme)
    accent = hex_color(accent_hex)
    card_bg = hex_color(theme["card_bg"], "#FFFFFF")
    text_color = hex_color(theme["text"], "#111111")
    muted = hex_color(theme["muted"], "#555555")
    border = hex_color(theme["border"], "#AAAAAA")
    navy = hex_color(theme["navy"], "#082E5C")
    kind = sec.get("kind", "card")

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "card_title",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9.0,
        leading=10.3,
        textColor=colors.white,
        alignment=TA_LEFT,
        spaceAfter=0,
    )
    body_size = 7.4 if width < 250 else 7.8
    if kind == "formula":
        body_size += 0.6
    body_style = ParagraphStyle(
        "card_body",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=body_size,
        leading=body_size + 1.7,
        textColor=text_color,
        spaceAfter=0,
    )
    bullet_style = ParagraphStyle(
        "card_bullet",
        parent=body_style,
        leftIndent=8,
        firstLineIndent=-5,
        bulletIndent=0,
        spaceAfter=0.5,
    )
    caption_style = ParagraphStyle(
        "caption",
        parent=body_style,
        fontSize=6.2,
        leading=7.1,
        textColor=muted,
        alignment=TA_CENTER,
    )
    pearl_style = ParagraphStyle(
        "pearl",
        parent=body_style,
        fontName="Helvetica-Bold",
        fontSize=6.9,
        leading=8.1,
        textColor=text_color,
        borderColor=accent,
        borderWidth=0.7,
        borderPadding=4,
        backColor=hex_color("#F2F6F9"),
        spaceBefore=3,
    )

    if kind == "bottom_line":
        label = prepare_inline_markup(str(sec.get("title", "Bottom line")).upper())
        body = prepare_inline_markup(str(sec.get("body", "")))
        bottom_style = ParagraphStyle(
            "bottom_line",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9.2,
            leading=11,
            textColor=colors.white,
            alignment=TA_CENTER,
        )
        content = Paragraph(f"<font color='#FFD54A'>{label}:</font> {body}", bottom_style)
        table = Table([[content]], colWidths=[width], hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), navy),
                    ("BOX", (0, 0), (-1, -1), 1.2, navy),
                    ("LEFTPADDING", (0, 0), (-1, -1), 9),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )
        return table

    raw_title = str(sec.get("title", "Untitled"))
    number_prefix = ""
    if show_numbers and not re.match(r"^\s*\d+[\.\)]?\s", raw_title):
        number_prefix = f"{idx}. "
    header = Paragraph(
        f"<font color='#FFFFFF'><b>{prepare_inline_markup(number_prefix + raw_title)}</b></font>",
        title_style,
    )

    body_items = body_flowables(str(sec.get("body", "")), body_style, bullet_style)
    if sec.get("pearl"):
        body_items.append(Paragraph(prepare_inline_markup(str(sec.get("pearl", ""))), pearl_style))

    max_image_w = min(120, width * 0.34)
    image = image_flowable(sec, max_image_w, 95)
    caption = Paragraph(prepare_inline_markup(str(sec.get("graphic_caption", ""))), caption_style) if sec.get("graphic_caption") else None
    image_group: List[Any] = []
    if image:
        image_group.append(image)
        if caption:
            image_group.extend([Spacer(1, 2), caption])

    position = sec.get("graphic_position", "Right")
    if image_group and position in {"Right", "Left"}:
        image_table = Table([[image_group]], colWidths=[max_image_w], hAlign="CENTER")
        text_width = max(60, width - max_image_w - 18)
        text_table = Table([[body_items]], colWidths=[text_width])
        if position == "Left":
            content_table = Table([[image_table, text_table]], colWidths=[max_image_w, text_width])
        else:
            content_table = Table([[text_table, image_table]], colWidths=[text_width, max_image_w])
        content_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
        content: Any = content_table
    elif image_group and position in {"Top", "Full width"}:
        content = image_group + [Spacer(1, 3)] + body_items
    elif image_group and position == "Bottom":
        content = body_items + [Spacer(1, 3)] + image_group
    else:
        content = body_items

    body_bg = card_bg
    if kind in {"warning", "formula", "pearl"}:
        # A light tint without requiring alpha support.
        body_bg = colors.Color(
            min(1, card_bg.red * 0.92 + accent.red * 0.08),
            min(1, card_bg.green * 0.92 + accent.green * 0.08),
            min(1, card_bg.blue * 0.92 + accent.blue * 0.08),
        )

    card = Table([[header], [content]], colWidths=[width], hAlign="LEFT")
    card.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, 0), accent),
                ("BACKGROUND", (0, 1), (0, 1), body_bg),
                ("BOX", (0, 0), (-1, -1), 0.9, accent if kind == "warning" else border),
                ("LEFTPADDING", (0, 0), (0, 0), 7),
                ("RIGHTPADDING", (0, 0), (0, 0), 7),
                ("TOPPADDING", (0, 0), (0, 0), 5),
                ("BOTTOMPADDING", (0, 0), (0, 0), 5),
                ("LEFTPADDING", (0, 1), (0, 1), 7),
                ("RIGHTPADDING", (0, 1), (0, 1), 7),
                ("TOPPADDING", (0, 1), (0, 1), 6),
                ("BOTTOMPADDING", (0, 1), (0, 1), 6),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return card


def pack_section_rows(sections: Sequence[Dict[str, Any]], total_columns: int = 3) -> List[List[Tuple[int, Dict[str, Any]]]]:
    rows: List[List[Tuple[int, Dict[str, Any]]]] = []
    current: List[Tuple[int, Dict[str, Any]]] = []
    used = 0
    for idx, sec in enumerate(sections, start=1):
        span = min(total_columns, max(1, int(sec.get("span", 1))))
        if current and used + span > total_columns:
            rows.append(current)
            current = []
            used = 0
        current.append((idx, sec))
        used += span
        if used == total_columns:
            rows.append(current)
            current = []
            used = 0
    if current:
        rows.append(current)
    return rows


def page_dimensions(doc: Dict[str, Any]) -> Tuple[float, float]:
    base = letter if doc.get("paper_size", "Letter") == "Letter" else A4
    return landscape(base) if doc.get("orientation", "Landscape") == "Landscape" else portrait(base)


def build_pdf(doc: Dict[str, Any]) -> bytes:
    buffer = io.BytesIO()
    page_size = page_dimensions(doc)
    page_w, page_h = page_size
    theme = THEMES[doc["theme_name"]]
    navy = hex_color(theme["navy"], "#082E5C")
    title_text = hex_color(theme["title_text"], "#FFFFFF")
    page_bg = hex_color(theme["page_bg"], "#FFFFFF")
    footer_bg = hex_color(theme["footer_bg"], "#082E5C")
    footer_text = hex_color(theme["footer_text"], "#FFFFFF")

    margin = 18
    doc_template = SimpleDocTemplate(
        buffer,
        pagesize=page_size,
        rightMargin=margin,
        leftMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
        title=str(doc.get("title", "PICU Clinical Cheat Sheet")),
        author=str(doc.get("author", "")),
        subject="PICU clinical education cheat sheet",
        pageCompression=1,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "sheet_title",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=22 if doc.get("orientation") == "Landscape" else 18,
        leading=24,
        textColor=title_text,
        alignment=TA_CENTER,
        spaceAfter=0,
    )
    subtitle_style = ParagraphStyle(
        "sheet_subtitle",
        parent=styles["Normal"],
        fontName="Helvetica-BoldOblique",
        fontSize=9.5,
        leading=11,
        textColor=title_text,
        alignment=TA_CENTER,
        spaceAfter=0,
    )
    footer_style = ParagraphStyle(
        "footer",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=6.5,
        leading=7.5,
        textColor=footer_text,
        alignment=TA_CENTER,
    )

    story: List[Any] = []
    title_block = Table(
        [[Paragraph(prepare_inline_markup(str(doc.get("title", ""))), title_style)], [Paragraph(prepare_inline_markup(str(doc.get("subtitle", ""))), subtitle_style)]],
        colWidths=[page_w - 2 * margin],
    )
    title_block.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), navy),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (0, 0), 9),
                ("BOTTOMPADDING", (0, 0), (0, 0), 2),
                ("TOPPADDING", (0, 1), (0, 1), 0),
                ("BOTTOMPADDING", (0, 1), (0, 1), 8),
            ]
        )
    )
    story.append(title_block)
    story.append(Spacer(1, 7))

    content_width = page_w - 2 * margin
    gap = 7
    col_width = (content_width - 2 * gap) / 3
    rows = pack_section_rows(doc["sections"])

    for row_number, row in enumerate(rows):
        cells: List[Any] = [""] * 3
        spans: List[Tuple[int, int, int, int]] = []
        cursor = 0
        for idx, sec in row:
            span = min(3, max(1, int(sec.get("span", 1))))
            card_width = col_width * span + gap * (span - 1)
            cells[cursor] = make_card(sec, idx, card_width, theme, bool(doc.get("show_numbers", True)))
            if span > 1:
                spans.append((cursor, 0, cursor + span - 1, 0))
            cursor += span
        row_table = Table([cells], colWidths=[col_width, col_width, col_width], hAlign="LEFT", splitByRow=1)
        commands: List[Tuple[Any, ...]] = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), gap),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]
        for x1, y1, x2, y2 in spans:
            commands.append(("SPAN", (x1, y1), (x2, y2)))
        row_table.setStyle(TableStyle(commands))
        story.append(row_table)
        if row_number < len(rows) - 1:
            story.append(Spacer(1, 6))

    if doc.get("show_footer", True):
        story.append(Spacer(1, 7))
        footer = Table([[Paragraph(prepare_inline_markup(str(doc.get("footer_text", ""))), footer_style)]], colWidths=[content_width])
        footer.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), footer_bg),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(footer)

    def draw_page_background(canvas: Any, built_doc: Any) -> None:
        canvas.saveState()
        canvas.setFillColor(page_bg)
        canvas.rect(0, 0, page_w, page_h, stroke=0, fill=1)
        canvas.setFillColor(hex_color(theme["muted"], "#666666"))
        canvas.setFont("Helvetica", 5.8)
        canvas.drawRightString(page_w - margin, 6, f"Page {built_doc.page}")
        canvas.restoreState()

    doc_template.build(story, onFirstPage=draw_page_background, onLaterPages=draw_page_background)
    return buffer.getvalue()


# -----------------------------------------------------------------------------
# GitHub archive
# -----------------------------------------------------------------------------


def github_config() -> Tuple[Optional[Dict[str, str]], Optional[str]]:
    try:
        cfg = st.secrets.get("github", {})
    except Exception:
        cfg = {}
    token = str(cfg.get("token", "")).strip()
    repo = str(cfg.get("repo", "")).strip()
    branch = str(cfg.get("branch", "main")).strip() or "main"
    base_path = str(cfg.get("base_path", "picu_cheat_sheets")).strip().strip("/") or "picu_cheat_sheets"
    if not token or not repo or "/" not in repo:
        return None, "GitHub is not configured. Add token and repo under [github] in .streamlit/secrets.toml."
    return {"token": token, "repo": repo, "branch": branch, "base_path": base_path}, None


def github_headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def github_api_url(repo: str, path: str) -> str:
    safe_path = str(PurePosixPath(path))
    return f"https://api.github.com/repos/{repo}/contents/{safe_path}"


def save_document_to_github(doc: Dict[str, Any]) -> str:
    cfg, error = github_config()
    if error or not cfg:
        raise RuntimeError(error or "GitHub configuration missing.")

    filename = str(doc.get("github_filename", "")).strip()
    if not filename:
        filename = f"{doc['archive_id']}_{slugify(str(doc.get('title', 'cheat-sheet')))}.json"
        doc["github_filename"] = filename
    path = f"{cfg['base_path']}/{filename}"
    url = github_api_url(cfg["repo"], path)
    headers = github_headers(cfg["token"])

    sha = None
    existing = requests.get(url, headers=headers, params={"ref": cfg["branch"]}, timeout=20)
    if existing.status_code == 200:
        sha = existing.json().get("sha")
    elif existing.status_code != 404:
        raise RuntimeError(f"GitHub lookup failed ({existing.status_code}): {existing.text[:300]}")

    doc["updated_at"] = utc_now_iso()
    payload: Dict[str, Any] = {
        "message": f"Save PICU cheat sheet: {doc.get('title', 'Untitled')}",
        "content": base64.b64encode(document_json_bytes(doc)).decode("ascii"),
        "branch": cfg["branch"],
    }
    if sha:
        payload["sha"] = sha
    response = requests.put(url, headers=headers, json=payload, timeout=30)
    if response.status_code not in {200, 201}:
        raise RuntimeError(f"GitHub save failed ({response.status_code}): {response.text[:500]}")
    return path


@st.cache_data(ttl=30, show_spinner=False)
def list_github_documents(cache_key: str = "") -> List[Dict[str, Any]]:
    del cache_key
    cfg, error = github_config()
    if error or not cfg:
        return []
    url = github_api_url(cfg["repo"], cfg["base_path"])
    response = requests.get(url, headers=github_headers(cfg["token"]), params={"ref": cfg["branch"]}, timeout=20)
    if response.status_code == 404:
        return []
    if response.status_code != 200:
        raise RuntimeError(f"GitHub list failed ({response.status_code}): {response.text[:300]}")
    items = response.json()
    return sorted(
        [x for x in items if x.get("type") == "file" and str(x.get("name", "")).endswith(".json")],
        key=lambda x: str(x.get("name", "")),
    )


def load_document_from_github(filename: str) -> Dict[str, Any]:
    cfg, error = github_config()
    if error or not cfg:
        raise RuntimeError(error or "GitHub configuration missing.")
    path = f"{cfg['base_path']}/{filename}"
    response = requests.get(github_api_url(cfg["repo"], path), headers=github_headers(cfg["token"]), params={"ref": cfg["branch"]}, timeout=20)
    if response.status_code != 200:
        raise RuntimeError(f"GitHub load failed ({response.status_code}): {response.text[:300]}")
    encoded = response.json().get("content", "").replace("\n", "")
    return normalize_document(json.loads(base64.b64decode(encoded).decode("utf-8")))


def delete_document_from_github(filename: str) -> None:
    cfg, error = github_config()
    if error or not cfg:
        raise RuntimeError(error or "GitHub configuration missing.")
    path = f"{cfg['base_path']}/{filename}"
    url = github_api_url(cfg["repo"], path)
    headers = github_headers(cfg["token"])
    existing = requests.get(url, headers=headers, params={"ref": cfg["branch"]}, timeout=20)
    if existing.status_code != 200:
        raise RuntimeError(f"GitHub lookup failed ({existing.status_code}): {existing.text[:300]}")
    sha = existing.json().get("sha")
    response = requests.delete(
        url,
        headers=headers,
        json={"message": f"Delete PICU cheat sheet: {filename}", "sha": sha, "branch": cfg["branch"]},
        timeout=20,
    )
    if response.status_code != 200:
        raise RuntimeError(f"GitHub delete failed ({response.status_code}): {response.text[:300]}")


# -----------------------------------------------------------------------------
# AI JSON prompt
# -----------------------------------------------------------------------------


def ai_prompt(doc: Dict[str, Any]) -> str:
    skeleton = {
        "schema_version": SCHEMA_VERSION,
        "title": "TITLE",
        "subtitle": "SUBTITLE",
        "template_name": doc.get("template_name", "Blank canvas"),
        "theme_name": doc.get("theme_name", "Classic PICU"),
        "orientation": "Landscape",
        "paper_size": "Letter",
        "show_numbers": True,
        "show_footer": True,
        "footer_text": "Clinical education guide - use clinical judgment and local policies.",
        "sections": [
            {
                "title": "SECTION TITLE",
                "body": "Use short paragraphs and bullet lines beginning with - ",
                "kind": "card",
                "span": 1,
                "accent_index": 0,
                "pearl": "Optional concise pearl",
                "graphic_caption": "Optional suggested graphic description",
                "graphic_position": "Right",
            }
        ],
    }
    return textwrap.dedent(
        f"""
        Create a PICU clinical cheat sheet as valid JSON only. Do not use markdown code fences.

        Topic: [INSERT TOPIC]
        Audience: residents and fellows
        Selected content pattern: {doc.get('template_name')}

        Writing style:
        - Bedside focused, concise, and clinically interpretive.
        - Use short bullets rather than dense prose.
        - Organize causes into useful physiologic or troubleshooting categories.
        - Include practical reassessment and escalation guidance.
        - End with one memorable bottom-line section.
        - Do not invent patient-specific recommendations or local policies.

        Allowed section kind values:
        card, checklist, formula, step, warning, pearl, bottom_line

        Allowed span values:
        1 = one column, 2 = two columns, 3 = full width

        Return a JSON object shaped like this example:
        {json.dumps(skeleton, indent=2)}

        Do not include image data. A graphic_caption may describe a suggested visual that I can upload later.
        """
    ).strip()


# -----------------------------------------------------------------------------
# Streamlit interface
# -----------------------------------------------------------------------------


def init_state() -> None:
    if "cheat_doc" not in st.session_state:
        st.session_state.cheat_doc = new_document("Troubleshooting guide")
    if "github_refresh" not in st.session_state:
        st.session_state.github_refresh = uuid.uuid4().hex


def set_document(doc: Dict[str, Any]) -> None:
    # Streamlit widgets with fixed keys otherwise retain values from the prior
    # document after a JSON/GitHub load. Clear transient widget state so the
    # newly loaded document becomes the source of truth on the next rerun.
    normalized = normalize_document(doc)
    preserved = {
        "cheat_doc": normalized,
        "github_refresh": st.session_state.get("github_refresh", uuid.uuid4().hex),
    }
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.session_state.update(preserved)


def move_section(doc: Dict[str, Any], index: int, direction: int) -> None:
    destination = index + direction
    if 0 <= destination < len(doc["sections"]):
        doc["sections"][index], doc["sections"][destination] = doc["sections"][destination], doc["sections"][index]
        doc["updated_at"] = utc_now_iso()


def render_section_editor(doc: Dict[str, Any], index: int) -> None:
    sec = doc["sections"][index]
    sec_id = sec["id"]
    kind_label = KIND_LABELS.get(sec.get("kind", "card"), "Teaching card")

    with st.expander(f"{index + 1}. {sec.get('title', 'Untitled section')}  -  {kind_label}", expanded=index == 0):
        top_cols = st.columns([1.1, 1.1, 1.1, 0.55, 0.55, 0.55])
        sec["kind"] = SECTION_KINDS[top_cols[0].selectbox("Section style", list(SECTION_KINDS), index=list(SECTION_KINDS).index(kind_label), key=f"kind_{sec_id}")]
        current_span_label = SPAN_LABELS.get(int(sec.get("span", 1)), "1 column")
        sec["span"] = SPAN_OPTIONS[top_cols[1].selectbox("Width", list(SPAN_OPTIONS), index=list(SPAN_OPTIONS).index(current_span_label), key=f"span_{sec_id}")]
        theme = THEMES[doc["theme_name"]]
        color_options = [f"Color {i + 1}" for i in range(len(theme["palette"]))]
        current_color = min(len(color_options) - 1, int(sec.get("accent_index", 0)) % len(color_options))
        sec["accent_index"] = color_options.index(top_cols[2].selectbox("Accent", color_options, index=current_color, key=f"accent_{sec_id}"))

        if top_cols[3].button("Up", key=f"up_{sec_id}", disabled=index == 0, use_container_width=True):
            move_section(doc, index, -1)
            st.rerun()
        if top_cols[4].button("Down", key=f"down_{sec_id}", disabled=index == len(doc["sections"]) - 1, use_container_width=True):
            move_section(doc, index, 1)
            st.rerun()
        if top_cols[5].button("Delete", key=f"delete_{sec_id}", type="secondary", use_container_width=True):
            doc["sections"].pop(index)
            doc["updated_at"] = utc_now_iso()
            st.rerun()

        sec["title"] = st.text_input("Section title", value=str(sec.get("title", "")), key=f"title_{sec_id}")
        sec["body"] = st.text_area(
            "Content",
            value=str(sec.get("body", "")),
            height=180,
            key=f"body_{sec_id}",
            help="Use one idea per line. Begin bullet lines with '- '. Use **bold** for emphasis.",
        )
        sec["pearl"] = st.text_input("Optional pearl / callout", value=str(sec.get("pearl", "")), key=f"pearl_{sec_id}")

        with st.expander("Graphic options", expanded=bool(sec.get("graphic_b64"))):
            graphic_cols = st.columns([1.3, 1, 1])
            upload = graphic_cols[0].file_uploader(
                "Upload a suggested graphic",
                type=["png", "jpg", "jpeg", "webp"],
                key=f"graphic_upload_{sec_id}",
            )
            if upload is not None:
                raw = upload.getvalue()
                digest = hashlib.sha256(raw).hexdigest()
                if digest != sec.get("graphic_hash"):
                    try:
                        img = PILImage.open(io.BytesIO(raw))
                        img.verify()
                        sec["graphic_b64"] = base64.b64encode(raw).decode("ascii")
                        sec["graphic_name"] = upload.name
                        sec["graphic_mime"] = upload.type or "image/png"
                        sec["graphic_hash"] = digest
                    except Exception as exc:
                        st.error(f"That file could not be read as an image: {exc}")
            sec["graphic_position"] = graphic_cols[1].selectbox(
                "Placement",
                GRAPHIC_POSITIONS,
                index=GRAPHIC_POSITIONS.index(sec.get("graphic_position", "Right")) if sec.get("graphic_position", "Right") in GRAPHIC_POSITIONS else 0,
                key=f"graphic_position_{sec_id}",
            )
            if graphic_cols[2].button("Remove graphic", key=f"remove_graphic_{sec_id}", disabled=not bool(sec.get("graphic_b64")), use_container_width=True):
                for field in ["graphic_b64", "graphic_name", "graphic_mime", "graphic_caption", "graphic_hash"]:
                    sec[field] = ""
                st.rerun()
            sec["graphic_caption"] = st.text_input(
                "Graphic caption or AI suggestion",
                value=str(sec.get("graphic_caption", "")),
                key=f"graphic_caption_{sec_id}",
                help="This can also hold a suggested visual description until you upload the final graphic.",
            )
            if sec.get("graphic_b64"):
                st.image(base64.b64decode(sec["graphic_b64"]), caption=sec.get("graphic_name", "Uploaded graphic"), width=240)

        with st.expander("Advanced color", expanded=False):
            sec["custom_accent"] = st.text_input(
                "Custom accent hex (optional)",
                value=str(sec.get("custom_accent", "")),
                placeholder="#0B57A4",
                key=f"custom_accent_{sec_id}",
            )


def main() -> None:
    st.set_page_config(page_title="PICU Cheat Sheet Builder", page_icon="🩺", layout="wide")
    init_state()
    doc = st.session_state.cheat_doc

    st.markdown(
        """
        <style>
        .block-container {padding-top: 1.2rem; padding-bottom: 3rem; max-width: 1500px;}
        div[data-testid="stMetric"] {background:#f5f8fb; border:1px solid #dbe5ee; padding:8px 12px; border-radius:10px;}
        .small-note {font-size:.86rem; color:#5d6b7d;}
        </style>
        """,
        unsafe_allow_html=True,
    )

    header_left, header_right = st.columns([4, 1.1])
    with header_left:
        st.title("PICU Cheat Sheet Builder")
        st.caption("Build concise, visual clinical guides; draft with AI through JSON; archive in GitHub; export a polished PDF.")
    with header_right:
        st.metric("Sections", len(doc["sections"]))

    build_tab, preview_tab, archive_tab, ai_tab = st.tabs(["Build", "Preview + export", "GitHub archive", "JSON + AI"])

    with build_tab:
        settings_col, editor_col = st.columns([0.9, 2.25], gap="large")

        with settings_col:
            st.subheader("Guide settings")
            doc["title"] = st.text_input("Title", value=str(doc.get("title", "")), key="doc_title")
            doc["subtitle"] = st.text_area("Subtitle", value=str(doc.get("subtitle", "")), height=88, key="doc_subtitle")
            doc["author"] = st.text_input("Author / program (optional)", value=str(doc.get("author", "")), key="doc_author")

            selected_template = st.selectbox(
                "Content pattern",
                list(TEMPLATE_LIBRARY),
                index=list(TEMPLATE_LIBRARY).index(doc.get("template_name", "Blank canvas")) if doc.get("template_name") in TEMPLATE_LIBRARY else 0,
                help="Applying a pattern replaces the current sections.",
            )
            preserve_title = st.checkbox("Keep current title when applying", value=True)
            if st.button("Apply content pattern", use_container_width=True):
                set_document(apply_template(doc, selected_template, preserve_title=preserve_title))
                st.rerun()

            doc["theme_name"] = st.selectbox(
                "Visual theme",
                list(THEMES),
                index=list(THEMES).index(doc.get("theme_name", "Classic PICU")),
                key="theme_name",
            )
            page_cols = st.columns(2)
            doc["orientation"] = page_cols[0].selectbox("Orientation", ["Landscape", "Portrait"], index=0 if doc.get("orientation") == "Landscape" else 1)
            doc["paper_size"] = page_cols[1].selectbox("Paper", ["Letter", "A4"], index=0 if doc.get("paper_size") == "Letter" else 1)
            doc["show_numbers"] = st.checkbox("Number sections", value=bool(doc.get("show_numbers", True)))
            doc["show_footer"] = st.checkbox("Show footer disclaimer", value=bool(doc.get("show_footer", True)))
            if doc["show_footer"]:
                doc["footer_text"] = st.text_area("Footer text", value=str(doc.get("footer_text", "")), height=82)

            st.divider()
            if st.button("Add section", type="primary", use_container_width=True):
                doc["sections"].append(section("New section", "", accent_index=len(doc["sections"]) % 6))
                doc["updated_at"] = utc_now_iso()
                st.rerun()
            if st.button("Duplicate last section", use_container_width=True, disabled=not doc["sections"]):
                clone = copy.deepcopy(doc["sections"][-1])
                clone["id"] = str(uuid.uuid4())
                clone["title"] = f"{clone.get('title', 'Section')} - copy"
                doc["sections"].append(clone)
                st.rerun()
            if st.button("Start a new blank guide", use_container_width=True):
                set_document(new_document("Blank canvas"))
                st.rerun()

            st.info("For the cleanest one-page result, keep each card concise. Longer guides will automatically continue onto additional PDF pages.")

        with editor_col:
            st.subheader("Sections")
            if not doc["sections"]:
                st.warning("This guide has no sections yet.")
            for index in range(len(doc["sections"])):
                render_section_editor(doc, index)

    with preview_tab:
        doc["updated_at"] = utc_now_iso()
        preview_html = build_preview_html(doc)
        components.html(preview_html, height=900, scrolling=True)

        st.subheader("Download finalized files")
        download_cols = st.columns(3)
        try:
            pdf_bytes = build_pdf(doc)
            download_cols[0].download_button(
                "Download PDF",
                data=pdf_bytes,
                file_name=current_filename(doc, "pdf"),
                mime="application/pdf",
                type="primary",
                use_container_width=True,
            )
        except Exception as exc:
            download_cols[0].error(f"PDF generation failed: {exc}")
        download_cols[1].download_button(
            "Download JSON",
            data=document_json_bytes(doc),
            file_name=current_filename(doc, "json"),
            mime="application/json",
            use_container_width=True,
        )
        download_cols[2].button("Refresh preview", use_container_width=True)
        st.caption("The on-screen preview is responsive. The PDF uses a fixed 3-column clinical handout layout and may paginate when content is long.")

    with archive_tab:
        cfg, cfg_error = github_config()
        if cfg_error:
            st.warning(cfg_error)
            st.code(
                '[github]\ntoken = "github_pat_..."\nrepo = "OWNER/REPOSITORY"\nbranch = "main"\nbase_path = "picu_cheat_sheets"',
                language="toml",
            )
        else:
            st.success(f"Connected archive: {cfg['repo']} / {cfg['base_path']} ({cfg['branch']})")
            action_cols = st.columns([1, 1, 2])
            if action_cols[0].button("Save to GitHub", type="primary", use_container_width=True):
                try:
                    with st.spinner("Saving..."):
                        path = save_document_to_github(doc)
                    st.session_state.github_refresh = uuid.uuid4().hex
                    list_github_documents.clear()
                    st.success(f"Saved: {path}")
                except Exception as exc:
                    st.error(str(exc))
            if action_cols[1].button("Refresh archive", use_container_width=True):
                st.session_state.github_refresh = uuid.uuid4().hex
                list_github_documents.clear()
                st.rerun()

            try:
                archived = list_github_documents(st.session_state.github_refresh)
            except Exception as exc:
                st.error(str(exc))
                archived = []

            if not archived:
                st.info("No archived cheat sheets were found in the configured folder.")
            else:
                names = [x["name"] for x in archived]
                selected_name = st.selectbox("Archived JSON", names)
                archive_actions = st.columns([1, 1, 1.5])
                if archive_actions[0].button("Load selected", use_container_width=True):
                    try:
                        with st.spinner("Loading..."):
                            loaded = load_document_from_github(selected_name)
                        set_document(loaded)
                        st.success("Loaded into the editor.")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
                confirm_delete = archive_actions[2].checkbox("Confirm permanent delete")
                if archive_actions[1].button("Delete selected", use_container_width=True, disabled=not confirm_delete):
                    try:
                        delete_document_from_github(selected_name)
                        list_github_documents.clear()
                        st.session_state.github_refresh = uuid.uuid4().hex
                        st.success("Deleted from GitHub.")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))

    with ai_tab:
        import_col, prompt_col = st.columns([1, 1.15], gap="large")
        with import_col:
            st.subheader("Import an AI-generated JSON")
            uploaded_json = st.file_uploader("Upload JSON", type=["json"], key="json_import")
            if uploaded_json is not None:
                try:
                    candidate = json.loads(uploaded_json.getvalue().decode("utf-8-sig"))
                    normalized = normalize_document(candidate)
                    st.success(f"Valid JSON detected: {len(normalized['sections'])} sections")
                    if st.button("Load this JSON into the builder", type="primary", use_container_width=True):
                        set_document(normalized)
                        st.rerun()
                except Exception as exc:
                    st.error(f"The JSON could not be loaded: {exc}")

            st.subheader("Current JSON")
            st.download_button(
                "Download current JSON",
                data=document_json_bytes(doc),
                file_name=current_filename(doc, "json"),
                mime="application/json",
                use_container_width=True,
            )
            with st.expander("View current JSON"):
                st.json(json.loads(document_json_bytes(doc).decode("utf-8")))

        with prompt_col:
            st.subheader("Copy-ready AI drafting prompt")
            st.caption("Paste this into an AI tool, replace the topic, and upload the returned JSON here.")
            st.code(ai_prompt(doc), language="text")
            st.caption("Images are intentionally not embedded by AI. Use each section's graphic caption as a visual suggestion, then upload the final graphic in the builder.")

    st.session_state.cheat_doc = doc


if __name__ == "__main__":
    main()
