from __future__ import annotations

from io import BytesIO
from decimal import Decimal
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak


def euro(v) -> str:
    d = Decimal(str(v)).quantize(Decimal("0.01"))
    return f"EUR {d:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def build_quote_pdf(quote: dict) -> bytes:
    out = BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=18*mm, rightMargin=18*mm, topMargin=18*mm, bottomMargin=18*mm)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="SmallMuted", parent=styles["BodyText"], fontSize=8, leading=10, textColor=colors.HexColor("#555555")))
    story = []
    story.append(Paragraph("DOZENDEV - PROPOSTA", styles["Title"]))
    story.append(Paragraph(f"{quote['quote_number']} - versione {quote['version']}", styles["SmallMuted"]))
    story.append(Spacer(1, 6*mm))
    story.append(Paragraph(quote["project_name"], styles["Heading1"]))
    story.append(Paragraph(f"Cliente: {quote['customer']['business_name']}", styles["BodyText"]))
    story.append(Paragraph(f"Validita: {quote['valid_until']}", styles["SmallMuted"]))
    story.append(Spacer(1, 5*mm))
    story.append(Paragraph("La proposta", styles["Heading2"]))
    story.append(Paragraph(quote["narrative"], styles["BodyText"]))
    story.append(Spacer(1, 6*mm))
    data = [["Voce", "Qta", "Unitario", "Totale"]]
    for i in quote["items"]:
        data.append([i["name"], str(i["quantity"]), euro(i["unit_price"]), euro(i["total"])])
    t = quote["totals"]
    data.extend([
        ["", "", "Subtotale", euro(t["subtotal"])],
        ["", "", "Sconto", f"- {euro(t['discount'])}"],
        ["", "", "Totale + IVA", euro(t["net_total"])],
        ["", "", f"Totale IVA {t['vat_rate']}% inclusa", euro(t["gross_total"])],
    ])
    table = Table(data, colWidths=[86*mm, 18*mm, 32*mm, 32*mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#EEEEEE")),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("ALIGN", (1,1), (-1,-1), "RIGHT"),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("GRID", (0,0), (-1,-5), 0.25, colors.HexColor("#CCCCCC")),
        ("LINEABOVE", (2,-4), (-1,-4), 0.5, colors.black),
        ("FONTNAME", (2,-2), (-1,-2), "Helvetica-Bold"),
        ("FONTNAME", (2,-1), (-1,-1), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("TOPPADDING", (0,0), (-1,-1), 5),
    ]))
    story.append(table)
    story.append(Spacer(1, 6*mm))
    if quote.get("delivery_weeks"):
        story.append(Paragraph(f"Tempistiche indicative: {quote['delivery_weeks']}", styles["BodyText"]))
    if quote.get("notes"):
        story.append(Paragraph("Note", styles["Heading2"]))
        story.append(Paragraph(quote["notes"], styles["BodyText"]))
    story.append(PageBreak())
    story.append(Paragraph("Dettaglio scope", styles["Heading1"]))
    for i in quote["items"]:
        story.append(Paragraph(i["name"], styles["Heading3"]))
        story.append(Paragraph(i["description"], styles["BodyText"]))
        story.append(Spacer(1, 3*mm))
    if quote.get("acceptance_criteria"):
        story.append(Paragraph("Criteri di accettazione", styles["Heading2"]))
        for x in quote["acceptance_criteria"]:
            story.append(Paragraph(f"- {x}", styles["BodyText"]))
    if quote.get("exclusions"):
        story.append(Paragraph("Esclusioni", styles["Heading2"]))
        for x in quote["exclusions"]:
            story.append(Paragraph(f"- {x}", styles["BodyText"]))
    story.append(Spacer(1, 8*mm))
    story.append(Paragraph("Questo PDF e una rappresentazione della versione registrata nel Quote Engine. In caso di approvazione, la versione viene congelata e utilizzata per generare l'Allegato A del contratto.", styles["SmallMuted"]))
    doc.build(story)
    return out.getvalue()
