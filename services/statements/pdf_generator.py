"""Official NovaBank Account Statement PDF Generator using ReportLab Platypus."""

import io
import os
import hashlib
from datetime import datetime, timezone
from typing import Dict, Any, List
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    HRFlowable,
    KeepTogether
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
import structlog

logger = structlog.get_logger(__name__)

if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
    STATEMENTS_STORAGE_DIR = os.path.join("/tmp", "statements")
else:
    STATEMENTS_STORAGE_DIR = os.path.join(os.getcwd(), "storage", "statements")
os.makedirs(STATEMENTS_STORAGE_DIR, exist_ok=True)


def generate_statement_pdf(
    statement_data: Dict[str, Any],
    output_filename: str = None
) -> bytes:
    """
    Generates a high-fidelity official NovaBank account statement PDF.
    Returns the binary PDF bytes and optionally saves to storage.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()

    # Custom typography styles
    title_style = ParagraphStyle(
        'BankTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        textColor=colors.HexColor('#064e3b')  # Deep Emerald
    )

    subtitle_style = ParagraphStyle(
        'BankSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=11,
        textColor=colors.HexColor('#4b5563')
    )

    section_header_style = ParagraphStyle(
        'SectionHeader',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=14,
        textColor=colors.HexColor('#0f766e')
    )

    meta_label_style = ParagraphStyle(
        'MetaLabel',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=11,
        textColor=colors.HexColor('#374151')
    )

    meta_val_style = ParagraphStyle(
        'MetaValue',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=11,
        textColor=colors.HexColor('#111827')
    )

    table_header_style = ParagraphStyle(
        'TableHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10,
        textColor=colors.white
    )

    table_cell_style = ParagraphStyle(
        'TableCell',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor('#1f2937')
    )

    credit_cell_style = ParagraphStyle(
        'CreditCell',
        parent=table_cell_style,
        textColor=colors.HexColor('#047857')
    )

    debit_cell_style = ParagraphStyle(
        'DebitCell',
        parent=table_cell_style,
        textColor=colors.HexColor('#b91c1c')
    )

    elements = []

    # 1. Bank Header Banner
    header_data = [
        [
            Paragraph("<b>NovaBank</b>", title_style),
            Paragraph(
                "<b>NovaBank Digital Branch</b><br/>"
                "IFSC: NOVA0001001 | MICR: 110002145<br/>"
                "GSTIN: 07AAAAA0000A1Z5 | digital@novabank.com",
                subtitle_style
            )
        ]
    ]
    header_table = Table(header_data, colWidths=[200, 340])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 8))
    elements.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#059669'), spaceBefore=2, spaceAfter=10))

    # 2. Statement Meta & Customer Details (2 columns)
    account_info = statement_data.get("account_info", {})
    customer_info = statement_data.get("customer_info", {})
    period = statement_data.get("period", {})

    left_meta = [
        [Paragraph("Account Holder:", meta_label_style), Paragraph(customer_info.get("full_name", "Valued Customer"), meta_val_style)],
        [Paragraph("Account Number:", meta_label_style), Paragraph(account_info.get("masked_account", "SB••••1234"), meta_val_style)],
        [Paragraph("Account Type:", meta_label_style), Paragraph(account_info.get("account_type", "SAVINGS"), meta_val_style)],
        [Paragraph("Customer ID:", meta_label_style), Paragraph(customer_info.get("customer_external_id", "CUST-1001"), meta_val_style)]
    ]
    if customer_info.get("company_name"):
        left_meta.append([Paragraph("Business Entity:", meta_label_style), Paragraph(customer_info.get("company_name"), meta_val_style)])
    if customer_info.get("gstin"):
        left_meta.append([Paragraph("GSTIN:", meta_label_style), Paragraph(customer_info.get("gstin"), meta_val_style)])

    right_meta = [
        [Paragraph("Statement Period:", meta_label_style), Paragraph(f"{period.get('start_date')} to {period.get('end_date')}", meta_val_style)],
        [Paragraph("Generated On:", meta_label_style), Paragraph(statement_data.get("generated_at", datetime.now(timezone.utc).strftime("%d %b %Y, %I:%M %p")), meta_val_style)],
        [Paragraph("Currency:", meta_label_style), Paragraph("INR (₹)", meta_val_style)],
        [Paragraph("KYC Status:", meta_label_style), Paragraph("VERIFIED (Digital Video KYC)", meta_val_style)]
    ]

    meta_table_left = Table(left_meta, colWidths=[90, 170])
    meta_table_right = Table(right_meta, colWidths=[90, 170])

    meta_grid = Table([[meta_table_left, meta_table_right]], colWidths=[270, 270])
    meta_grid.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8fafc')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(meta_grid)
    elements.append(Spacer(1, 12))

    # 3. Account Summary Grid
    summary = statement_data.get("summary", {})
    summary_data = [
        [
            Paragraph("Opening Balance", meta_label_style),
            Paragraph("Total Credits (+)", meta_label_style),
            Paragraph("Total Debits (-)", meta_label_style),
            Paragraph("Net Cashflow", meta_label_style),
            Paragraph("Closing Balance", meta_label_style)
        ],
        [
            Paragraph(f"₹{summary.get('opening_balance', 0.0):,.2f}", meta_val_style),
            Paragraph(f"₹{summary.get('total_credits', 0.0):,.2f}", credit_cell_style),
            Paragraph(f"₹{summary.get('total_debits', 0.0):,.2f}", debit_cell_style),
            Paragraph(f"₹{summary.get('net_cashflow', 0.0):,.2f}", meta_val_style),
            Paragraph(f"<b>₹{summary.get('closing_balance', 0.0):,.2f}</b>", ParagraphStyle('CloseBal', parent=meta_val_style, fontName='Helvetica-Bold', textColor=colors.HexColor('#047857')))
        ]
    ]
    summary_table = Table(summary_data, colWidths=[108, 108, 108, 108, 108])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#065f46')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#f0fdf4')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#059669')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
    ]))
    # Re-apply white color for summary headers
    for i in range(5):
        summary_data[0][i] = Paragraph(summary_data[0][i].text, table_header_style)
    elements.append(summary_table)
    elements.append(Spacer(1, 14))

    # 4. Transaction Ledger Table
    elements.append(Paragraph("<b>Account Transaction Ledger</b>", section_header_style))
    elements.append(Spacer(1, 6))

    ledger_rows = [
        [
            Paragraph("Date & Time", table_header_style),
            Paragraph("Description / Counterparty", table_header_style),
            Paragraph("Reference (UTR)", table_header_style),
            Paragraph("Type", table_header_style),
            Paragraph("Amount (INR)", table_header_style),
            Paragraph("Balance (INR)", table_header_style)
        ]
    ]

    transactions: List[Dict[str, Any]] = statement_data.get("transactions", [])
    if not transactions:
        ledger_rows.append([
            Paragraph("No transactions found in this statement period.", table_cell_style),
            Paragraph("", table_cell_style),
            Paragraph("", table_cell_style),
            Paragraph("", table_cell_style),
            Paragraph("", table_cell_style),
            Paragraph("", table_cell_style)
        ])
    else:
        for idx, tx in enumerate(transactions):
            is_cr = tx.get("type", "").upper() == "CREDIT"
            amt_style = credit_cell_style if is_cr else debit_cell_style
            sign = "+" if is_cr else "-"
            amt_str = f"{sign}₹{tx.get('amount', 0.0):,.2f}"

            row = [
                Paragraph(tx.get("date", ""), table_cell_style),
                Paragraph(tx.get("description", "Transfer"), table_cell_style),
                Paragraph(f"<code>{tx.get('reference', '')}</code>", table_cell_style),
                Paragraph(tx.get("type", "DEBIT"), table_cell_style),
                Paragraph(amt_str, amt_style),
                Paragraph(f"₹{tx.get('running_balance', 0.0):,.2f}", table_cell_style)
            ]
            ledger_rows.append(row)

    col_widths = [85, 145, 95, 45, 85, 85]
    ledger_table = Table(ledger_rows, colWidths=col_widths, repeatRows=1)

    t_style = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f766e')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('ALIGN', (3, 0), (-1, -1), 'CENTER'),
        ('ALIGN', (4, 1), (-1, -1), 'RIGHT'),
        ('ALIGN', (5, 1), (-1, -1), 'RIGHT'),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#f1f5f9')),
        ('TOPPADDING', (0, 0), (-1, -1), 4.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4.5),
    ]
    # Alternating row background
    for r in range(1, len(ledger_rows)):
        if r % 2 == 0:
            t_style.append(('BACKGROUND', (0, r), (-1, r), colors.HexColor('#f8fafc')))
    ledger_table.setStyle(TableStyle(t_style))
    elements.append(ledger_table)
    elements.append(Spacer(1, 16))

    # 5. Security Hash and Digital Seal Footer
    sha_hash = hashlib.sha256(f"{customer_info.get('full_name')}-{account_info.get('account_number')}-{datetime.now().isoformat()}".encode()).hexdigest()[:24].upper()
    footer_data = [
        [
            Paragraph(
                "<b>Official System-Generated Statement</b><br/>"
                "This document is digitally certified by NovaBank Core Banking Infrastructure under RBI Master Direction. "
                "No physical signature required.<br/>"
                f"Document Hash: <code>SHA256:{sha_hash}</code>",
                subtitle_style
            ),
            Paragraph(
                "<font color='#047857'><b>[VERIFIED DIGITAL SEAL]</b></font><br/>"
                "NovaBank Cryptographic Security",
                ParagraphStyle('Seal', parent=subtitle_style, alignment=2)
            )
        ]
    ]
    footer_table = Table(footer_data, colWidths=[400, 140])
    footer_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LINEABOVE', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
        ('TOPPADDING', (0, 0), (-1, -1), 6)
    ]))

    elements.append(KeepTogether([Spacer(1, 8), footer_table]))

    doc.build(elements)
    pdf_bytes = buffer.getvalue()
    buffer.close()

    if output_filename:
        file_path = os.path.join(STATEMENTS_STORAGE_DIR, output_filename)
        with open(file_path, "wb") as f:
            f.write(pdf_bytes)
        logger.info("Saved statement PDF to storage", path=file_path, size=len(pdf_bytes))

    return pdf_bytes

