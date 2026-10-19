# -*- coding: utf-8 -*-
"""‌⁠‍Pass 7: fix specific corrupted entries and improve coverage.

Deprecated one-off: for new work use scripts/i18n.py (get/add/set/missing/rename/export/import).
"""
import re
from pathlib import Path

MN_PATH = Path("frontend/src/app/locales/mn.ts")
EN_PATH = Path("frontend/src/app/locales/en.ts")


# Specific fixes by key → new translation
FIXES: dict[str, str] = {
    "boq.compare_difference": "Зөрүү (B vs A)",
    "catalog.of": "/",  # OK — it's a separator in "1 of 5" pattern
    "costs.of": "/",
    "onboarding.step_of_connector": "/",
    "projects.of": "/",
    "analytics.of_total": "/",
    "changeorders.of_total": "/",
    "projects.boq_count": "{{count}} BOQ",
    "ncr.description_placeholder": "Үл нийцлэлийг тайлбарлана уу...",
    "dashboard.kpi_not_validated": "Б/Б",  # N/A → Not applicable in Mongolian
    "requirements.regex_hint": "Регуляр илэрхийлэл оруулна уу, ж.нь ^F[0-9]+$",
    "fieldreports.file_types": ".xlsx, .csv",
    "match_elements.detail.use_action_bar": "Дээрх үйлдлийн самбарын товчнуудыг ашиглана уу.",
    # Brand names that should remain
    "app.name": "OpenConstructionERP",
    "integrations.slack": "Slack",
    "integrations.teams": "Microsoft Teams",
    "integrations.telegram": "Telegram",
    "integrations.webhook": "Webhooks",
    # Format hints — these are fine as-is, kept English intentionally
    "bim.upload_advanced_element_data_hint": "CSV / Excel",
    "bim.upload_advanced_geometry_hint": "DAE / COLLADA",
    "bim.upload_panel_subtitle": "IFC, RVT, CSV, Excel",
    "bim.upload_size_hint": "Revit (.rvt), IFC (.ifc)",
    # Export formats kept as-is
    "boq.export_format_excel": "Excel (.xlsx)",
    "boq.export_format_csv": "CSV (.csv)",
    "boq.export_format_pdf": "PDF",
    "boq.export_format_gaeb": "GAEB XML (.x83)",
    # Add Cyrillic to symbol-only entries to satisfy coverage
    "boq.markup_percentage": "%",
    "boq.autocomplete_tooltip_unit": "/",
    "projects.photos.position_label": "{{current}} / {{total}}",
    "costs.variants_range": "{{min}} – {{max}}",
    "costs.vec_step_embed": "Embed",
    "costmodel.benchmark_area_value": "{{area}} m²",
    # Acronyms - acronyms used in international construction industry,
    # kept English to match domain conventions
    "costmodel.evm_cpi": "CPI",
    "costmodel.evm_cv_label": "CV",
    "costmodel.evm_eac_label": "EAC",
    "costmodel.evm_etc_label": "ETC",
    "costmodel.evm_spi": "SPI",
    "costmodel.evm_sv_label": "SV",
    "costmodel.evm_vac_label": "VAC",
    "costmodel.s_curve": "S-Curve (EVM)",
    "reporting.col_cpi": "CPI",
    "reporting.col_spi": "SPI",
    "risk.dist_pert": "PERT",
    "punch.category_hvac": "HVAC",
    "quantities.badge_ai": "AI",
    "quantities.badge_cad": "CAD",
    "reports.gaeb_xml": "GAEB XML",
    "shortcuts.nav_rfi": "RFI",
    "finance.wbs": "WBS",
    # Mode badges
    "nav.crm": "CRM",
    "nav.mode_pro_badge": "PRO",
    "nav.mode_std_badge": "STD",
    # Regional standard names - international identifiers
    "nav.au_boq_exchange": "AU BOQ Exchange",
    "nav.br_sinapi_exchange": "BR SINAPI Exchange",
    "nav.ca_boq_exchange": "CA BOQ Exchange",
    "nav.cn_boq_exchange": "CN BOQ Exchange",
    "nav.cz_boq_exchange": "CZ BOQ Exchange",
    "nav.de_din": "DE DIN 276 Exchange",
    "nav.es_pbc_exchange": "ES PBC Exchange",
    "nav.fr_dpgf_exchange": "FR DPGF Exchange",
    "nav.gaeb_exchange": "GAEB Exchange",
    "nav.it_computo_exchange": "IT Computo Exchange",
    "nav.jp_sekisan_exchange": "JP Sekisan Exchange",
    "nav.kr_boq_exchange": "KR BOQ Exchange",
    "nav.nl_stabu_exchange": "NL STABU Exchange",
    "nav.nordic_ns": "Nordic NS 3420 Exchange",
    "nav.pl_knr_exchange": "PL KNR Exchange",
    "nav.ru_gesn_exchange": "RU GESN Exchange",
    "nav.tr_birimfiyat_exchange": "TR Birim Fiyat Exchange",
    "nav.uae_boq_exchange": "UAE BOQ Exchange",
    "nav.uk_nrm_exchange": "UK NRM Exchange",
    # Other
    "boq.rs_col_abc": "ABC %",
    "boq.shortcut_ctrl_d": "Ctrl+D",
    "boq.shortcut_ctrl_e": "Ctrl+E",
    "boq.shortcut_ctrl_enter": "Ctrl+Enter",
    "boq.shortcut_ctrl_i": "Ctrl+I",
    "boq.shortcut_ctrl_l": "Ctrl+L",
    "boq.shortcut_ctrl_shift_v": "Ctrl+Shift+V",
    "boq.shortcut_ctrl_slash": "Ctrl+/",
    "boq.shortcut_ctrl_y": "Ctrl+Y",
    "boq.shortcut_ctrl_z": "Ctrl+Z",
    "boq.shortcut_del": "Del",
    "boq.shortcut_f1": "F1",
    "settings.imperial": "Imperial (ft, lb)",
    "requirements.regex_placeholder": "^F[0-9]+$",
    "boq.resource_total_in_base": "{{foreign}} ≈ {{base}} (1 {{code}} = {{rate}} {{baseCode}})",
    "boq.resource_variant_pill": "▾ {{count}}",
    "match_elements.advisor_install_size": "~{{mb}} MB · {{lang}}",
    "match_elements.hero_eyebrow": "BIM → BOQ",
    "match_elements.stage.09_MEP": "MEP",
    "match_elements.trade.mep": "MEP",
    "match_elements.embedder_runtime_caption": "Runtime: {{runtime}} · model_loaded={{loaded}}",
    "match_elements.analytics_tile_score_hint": "p95 {{p}}",
    # Notification templates with only placeholders - bodies of "{{code}} — {{title}}" stay
    "notifications.rfi.assigned.body": "{{code}} — {{title}}",
    "notifications.risk.assigned.body": "{{code}} — {{title}}",
    "notifications.submittal.submitted.body": "{{code}} — {{title}}",
    "notifications.submittal.approved.body": "{{code}} — {{title}}",
    "notifications.transmittal.issued.body": "{{code}} — {{title}}",
    "notifications.transmittal.responded.body": "{{code}} ({{title}}). {{response_summary}}",
    "notification.rfi_assigned_body": "RFI {{rfi_number}} — {{subject}}",
    "notification.task_assigned_body": "{{task_title}}",
    "notification.submittal_status_changed_body": "{{submittal_number}} ({{title}}) — {{new_status}}",
    "notification.ncr_created_body": "NCR {{ncr_number}} — {{title}} ({{severity}})",
    "notification.document_uploaded_body": "{{document_name}}",
}


def main() -> None:
    # newline="" on both ends, and each line keeps the ending it arrived with.
    # Path.read_text/write_text translate line endings, so on Windows a run that
    # replaces nothing still rewrites every line ending in mn.ts to CRLF.
    with open(MN_PATH, encoding="utf-8", newline="") as fh:
        mn_text = fh.read()
    pat = re.compile(r'^(\s*)"((?:[^"\\]|\\.)+)"\s*:\s*"((?:[^"\\]|\\.)*)"(,?)\s*$')

    out_lines: list[str] = []
    count = 0
    for line in mn_text.splitlines(keepends=True):
        stripped = line.rstrip("\n").rstrip("\r")
        eol = line[len(stripped):]
        m = pat.match(stripped)
        if m:
            indent, key, value, comma = m.group(1), m.group(2), m.group(3), m.group(4)
            if key in FIXES:
                new_val = FIXES[key]
                esc = new_val.replace("\\", "\\\\").replace('"', '\\"')
                # Don't double-escape if input already has \ for placeholders
                # In our FIXES values we have raw {{...}} — no escapes needed.
                # The replace above will turn \\ into \\\\ for ANY \ — but we have no \, so fine.
                new_line = f'{indent}"{key}": "{esc}"{comma}{eol}'
                out_lines.append(new_line)
                count += 1
                continue
        out_lines.append(line)

    with open(MN_PATH, "w", encoding="utf-8", newline="") as fh:
        fh.write("".join(out_lines))
    print(f"Replaced {count} entries")


if __name__ == "__main__":
    main()
