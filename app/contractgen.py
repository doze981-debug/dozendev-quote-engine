from __future__ import annotations

import json
import os
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether

from .contract_handoff import build_contract_handoff


def _safe(v) -> str:
    return escape(str(v or "-"))


def build_contract_pack(quote: dict, master_path: str | Path) -> dict:
    master = json.loads(Path(master_path).read_text(encoding="utf-8"))
    handoff = build_contract_handoff(quote)
    c = quote["customer"]
    variables = {
        "cliente_ragione_sociale": c.get("business_name") or "-",
        "cliente_piva_cf": c.get("vat_number") or c.get("tax_code") or "-",
        "cliente_sede": c.get("address") or "-",
        "cliente_referente": c.get("contact_name") or "-",
        "cliente_email": c.get("email") or "-",
        "cliente_pec": c.get("pec") or "-",
        "dozendev_dati": os.getenv("DOZENDEV_LEGAL_DETAILS", "[CONFIGURARE DOZENDEV_LEGAL_DETAILS]"),
        "dozendev_pec": os.getenv("DOZENDEV_PEC", "[CONFIGURARE DOZENDEV_PEC]"),
        "data": quote.get("approved_at") or quote.get("created_at"),
        "foro": os.getenv("DOZENDEV_FORUM", "[CONFIGURARE DOZENDEV_FORUM]"),
    }
    flags = handoff["contract_flags"]
    required_attachments = ["Allegato A - Scope e condizioni economiche"]
    if flags.get("requires_dpa"):
        required_attachments.append("DPA art. 28 GDPR")
    if flags.get("requires_ai_addendum"):
        required_attachments.append("Addendum AI")
    if flags.get("requires_sla"):
        required_attachments.append("SLA / piano di manutenzione")
    if flags.get("requires_third_party_schedule"):
        required_attachments.append("Elenco servizi/licenze di terze parti")
    if flags.get("requires_newsletter_tracking_annex"):
        required_attachments.append("Specifiche newsletter/tracking")
    missing_configuration = [k for k,v in variables.items() if isinstance(v,str) and v.startswith("[CONFIGURARE")]
    return {
        "quote_id": quote["quote_id"],
        "quote_number": quote["quote_number"],
        "quote_version": quote["version"],
        "master": {"documento": master["documento"], "versione": master["versione"], "data_revisione": master["data_revisione"], "ambito": master["ambito"]},
        "variables": variables,
        "clauses": master["clausole"],
        "annex_a": handoff["annex_a"],
        "contract_flags": flags,
        "required_attachments": required_attachments,
        "missing_configuration": missing_configuration,
        "ready_for_signature": not missing_configuration,
        "signature_requirements": {
            "general_signature": True,
            "separate_1341_1342_signature": True,
            "provider_audit_trail": True,
        },
    }


def build_contract_pdf(pack: dict) -> bytes:
    out = BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=17*mm, rightMargin=17*mm, topMargin=16*mm, bottomMargin=17*mm)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Clause", parent=styles["BodyText"], fontSize=8.7, leading=11.2, spaceAfter=4))
    styles.add(ParagraphStyle(name="Meta", parent=styles["BodyText"], fontSize=8, leading=10, textColor=colors.HexColor("#555555")))
    story = [Paragraph("CONTRATTO MASTER DOZENDEV", styles["Title"]), Paragraph(_safe(pack["master"]["documento"]), styles["Meta"]), Spacer(1, 4*mm)]
    v = pack["variables"]
    meta = [
        ["Cliente", v["cliente_ragione_sociale"]], ["P.IVA / C.F.", v["cliente_piva_cf"]], ["Sede", v["cliente_sede"]],
        ["Referente", v["cliente_referente"]], ["Email / PEC", f"{v['cliente_email']} / {v['cliente_pec']}"], ["DozenDev", v["dozendev_dati"]],
        ["PEC DozenDev", v["dozendev_pec"]], ["Data", v["data"]], ["Foro", v["foro"]],
    ]
    t = Table([[_safe(a), _safe(b)] for a,b in meta], colWidths=[36*mm, 130*mm])
    t.setStyle(TableStyle([("FONTNAME",(0,0),(0,-1),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),8.5),("VALIGN",(0,0),(-1,-1),"TOP"),("BOTTOMPADDING",(0,0),(-1,-1),3)]))
    story += [t, Spacer(1, 5*mm)]
    for clause in pack["clauses"]:
        story.append(KeepTogether([Paragraph(_safe(clause["titolo"]), styles["Heading3"]), Paragraph(_safe(clause["testo"]).replace("\n", "<br/>"), styles["Clause"])]))
    story += [PageBreak(), Paragraph("ALLEGATO A - SCOPE E CONDIZIONI ECONOMICHE", styles["Title"]), Paragraph(f"Fonte: {_safe(pack['annex_a']['source_quote'])}", styles["Meta"]), Spacer(1,4*mm)]
    cell = ParagraphStyle(name="TableCell", parent=styles["BodyText"], fontSize=7.2, leading=8.8)
    cell_bold = ParagraphStyle(name="TableCellBold", parent=cell, fontName="Helvetica-Bold")
    data = [[Paragraph("Voce", cell_bold), Paragraph("Descrizione", cell_bold), Paragraph("Qta", cell_bold), Paragraph("Totale", cell_bold)]]
    for i in pack["annex_a"]["scope"]:
        data.append([Paragraph(_safe(i["name"]), cell), Paragraph(_safe(i["description"]), cell), Paragraph(_safe(i["quantity"]), cell), Paragraph(f"EUR {_safe(i['total'])}", cell)])
    tab = Table(data, colWidths=[40*mm, 83*mm, 13*mm, 30*mm], repeatRows=1)
    tab.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#eeeeee")),("GRID",(0,0),(-1,-1),0.25,colors.HexColor("#cccccc")),("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),4),("RIGHTPADDING",(0,0),(-1,-1),4),("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4)]))
    story.append(tab)
    econ = pack["annex_a"]["economic_conditions"]
    story += [Spacer(1,4*mm), Paragraph(f"Corrispettivo netto: EUR {_safe(econ['net_total'])} + IVA", styles["Heading3"])]
    if pack["annex_a"].get("acceptance_criteria"):
        story.append(Paragraph("Criteri di accettazione", styles["Heading3"]))
        for x in pack["annex_a"]["acceptance_criteria"]: story.append(Paragraph(f"- {_safe(x)}", styles["Clause"]))
    if pack["annex_a"].get("exclusions"):
        story.append(Paragraph("Esclusioni", styles["Heading3"]))
        for x in pack["annex_a"]["exclusions"]: story.append(Paragraph(f"- {_safe(x)}", styles["Clause"]))
    story += [Spacer(1,5*mm), Paragraph("Allegati richiesti dal progetto", styles["Heading3"])]
    for a in pack["required_attachments"]: story.append(Paragraph(f"- {_safe(a)}", styles["Clause"]))
    story += [Spacer(1,8*mm), Paragraph("SOTTOSCRIZIONE", styles["Heading2"]), Paragraph("Il flusso di firma deve raccogliere separatamente (1) la sottoscrizione generale e (2) la specifica approvazione delle clausole richiamate dall'art. 30 ai sensi degli artt. 1341 e 1342 c.c., conservando le evidenze del provider di firma.", styles["Clause"])]
    doc.build(story)
    return out.getvalue()
