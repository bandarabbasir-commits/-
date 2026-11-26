import csv
import io
from typing import Any, Sequence
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from app.utils.jalali import format_jalali_label, utc_now
from app.utils.persian import sanitize_spreadsheet_cell, to_persian_digits


def _set_paragraph_rtl(paragraph) -> None:
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    pPr = paragraph._p.get_or_add_pPr()
    bidi = OxmlElement("w:bidi")
    bidi.set(qn("w:val"), "1")
    pPr.append(bidi)


def _set_run_rtl(run, size_pt: int = 10, bold: bool = False, color: RGBColor | None = None) -> None:
    run.font.name = "Vazirmatn"
    run.font.size = Pt(size_pt)
    run.bold = bold
    if color:
        run.font.color.rgb = color
    rPr = run._r.get_or_add_rPr()
    rFonts = OxmlElement("w:rFonts")
    rFonts.set(qn("w:ascii"), "Vazirmatn")
    rFonts.set(qn("w:hAnsi"), "Vazirmatn")
    rFonts.set(qn("w:cs"), "Vazirmatn")
    rPr.append(rFonts)
    rtl = OxmlElement("w:rtl")
    rtl.set(qn("w:val"), "1")
    rPr.append(rtl)


def _set_table_rtl(table) -> None:
    tblPr = table._tbl.tblPr
    bidiVisual = OxmlElement("w:bidiVisual")
    tblPr.append(bidiVisual)


def build_rtl_docx(title: str, subtitle: str, headers: list[str], rows: Sequence[Sequence[Any]]) -> bytes:
    doc = Document()

    # Configure Normal style RTL
    style = doc.styles["Normal"]
    style.font.name = "Vazirmatn"
    style.font.size = Pt(10)

    h_p = doc.add_paragraph()
    _set_paragraph_rtl(h_p)
    h_run = h_p.add_run(title)
    _set_run_rtl(h_run, size_pt=15, bold=True, color=RGBColor(0x0F, 0x76, 0x6E))

    sub_p = doc.add_paragraph()
    _set_paragraph_rtl(sub_p)
    sub_run = sub_p.add_run(f"{subtitle} | تاریخ تهیه: {format_jalali_label(utc_now())}")
    _set_run_rtl(sub_run, size_pt=9, color=RGBColor(0x47, 0x55, 0x69))

    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Table Grid"
    _set_table_rtl(table)

    # Header row
    hdr_cells = table.rows[0].cells
    for idx, h_text in enumerate(headers):
        cell = hdr_cells[idx]
        p = cell.paragraphs[0]
        _set_paragraph_rtl(p)
        run = p.add_run(str(h_text))
        _set_run_rtl(run, size_pt=10, bold=True, color=RGBColor(0x0F, 0x17, 0x2A))
        tcPr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), "E2F3F1")
        tcPr.append(shd)

    for r_idx, row in enumerate(rows):
        row_cells = table.rows[r_idx + 1].cells
        for c_idx, val in enumerate(row):
            p = row_cells[c_idx].paragraphs[0]
            _set_paragraph_rtl(p)
            text_val = to_persian_digits(val) if isinstance(val, (int, float)) else str(val or "—")
            run = p.add_run(text_val)
            _set_run_rtl(run, size_pt=9, color=RGBColor(0x0F, 0x17, 0x2A))

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def build_rtl_xlsx(
    sheet_title: str,
    headers: list[str],
    rows: Sequence[Sequence[Any]],
    numeric_cols: set[int] | None = None,
) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_title[:31]
    ws.views.sheetView[0].rightToLeft = True

    header_fill = PatternFill(start_color="0F766E", end_color="0F766E", fill_type="solid")
    header_font = Font(name="Vazirmatn", size=11, bold=True, color="FFFFFF")
    cell_font = Font(name="Vazirmatn", size=10, color="0F172A")
    rtl_align = Alignment(horizontal="right", vertical="center", wrap_text=True)

    ws.append([sanitize_spreadsheet_cell(h) for h in headers])
    for col_idx in range(1, len(headers) + 1):
        c = ws.cell(row=1, column=col_idx)
        c.fill = header_fill
        c.font = header_font
        c.alignment = rtl_align

    numeric_cols = numeric_cols or set()
    for row in rows:
        out_row = []
        for idx, val in enumerate(row):
            if idx in numeric_cols and isinstance(val, (int, float)):
                out_row.append(val)
            else:
                out_row.append(sanitize_spreadsheet_cell("" if val is None else str(val)))
        ws.append(out_row)

    for row_cells in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=1, max_col=len(headers)):
        for cell in row_cells:
            cell.font = cell_font
            cell.alignment = rtl_align

    for col in ws.columns:
        col_letter = col[0].column_letter
        ws.column_dimensions[col_letter].width = 24

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_utf8_bom_csv(headers: list[str], rows: Sequence[Sequence[Any]]) -> bytes:
    text_buf = io.StringIO()
    writer = csv.writer(text_buf)
    writer.writerow([sanitize_spreadsheet_cell(h) for h in headers])
    for row in rows:
        writer.writerow([
            val if isinstance(val, (int, float)) else sanitize_spreadsheet_cell("" if val is None else str(val))
            for val in row
        ])
    # UTF-8 BOM for proper Persian display in Excel / desktop viewers
    return ("\ufeff" + text_buf.getvalue()).encode("utf-8")
