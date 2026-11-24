"""XLSX export of the bill of materials (openpyxl)."""

from datetime import date
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .services.bom import Bom

DISCLAIMER = (
    "Цены ориентировочные, UAH с НДС, только материалы. Расчёт не заменяет проект "
    "сертифицированного специалиста. * — цена требует уточнения."
)
HEADERS = ("№", "Бренд", "Артикул", "Наименование", "Ед.", "Кол-во", "Цена, ₴", "Сумма, ₴")
WIDTHS = (6, 20, 24, 56, 6, 9, 14, 16)
MONEY = "#,##0.00"
BOLD = Font(bold=True)
FILL_HEAD = PatternFill("solid", fgColor="E2E8F0")
FILL_SECTION = PatternFill("solid", fgColor="DBEAFE")
THIN = Side(style="thin", color="94A3B8")


def build_xlsx(project_name: str, bom: Bom, today: date | None = None) -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Спецификация"
    for i, w in enumerate(WIDTHS, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    ws["A1"] = f"Спецификация: {project_name}"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = f"Дата: {(today or date.today()).isoformat()}  ·  Валюта: UAH, цены с НДС"
    row = 4
    for section in bom.sections:
        ws.cell(row=row, column=1, value=section.title).font = BOLD
        for c in range(1, 9):
            ws.cell(row=row, column=c).fill = FILL_SECTION
        row += 1
        for block in section.blocks:
            title = block.title + (" (по схеме, щит ещё не собран)" if block.estimated else "")
            ws.cell(row=row, column=1, value=title).font = Font(bold=True, italic=True)
            row += 1
            for c, h in enumerate(HEADERS, start=1):
                cell = ws.cell(row=row, column=c, value=h)
                cell.font = BOLD
                cell.fill = FILL_HEAD
                cell.border = Border(bottom=THIN)
                cell.alignment = Alignment(horizontal="center" if c != 4 else "left")
            row += 1
            for n, ln in enumerate(block.lines, start=1):
                mark = " *" if ln.needs_verification else ""
                values = (
                    n,
                    ln.brand,
                    f"{ln.sku}{mark}",
                    ln.name,
                    ln.unit,
                    ln.qty,
                    float(ln.unit_price),
                    float(ln.total),
                )
                for c, v in enumerate(values, start=1):
                    cell = ws.cell(row=row, column=c, value=v)
                    if c in (7, 8):
                        cell.number_format = MONEY
                row += 1
            ws.cell(row=row, column=4, value=f"Итого: {block.title}").font = BOLD
            total = ws.cell(row=row, column=8, value=float(block.total))
            total.font = BOLD
            total.number_format = MONEY
            row += 2
    # summary
    ws.cell(row=row, column=1, value="Итоги").font = Font(bold=True, size=12)
    row += 1
    for section in bom.sections:
        ws.cell(row=row, column=4, value=section.title)
        cell = ws.cell(row=row, column=8, value=float(section.total))
        cell.number_format = MONEY
        row += 1
    ws.cell(row=row, column=4, value="Всего, ₴").font = BOLD
    grand = ws.cell(row=row, column=8, value=float(bom.total))
    grand.font = BOLD
    grand.number_format = MONEY
    for c in range(4, 9):
        ws.cell(row=row, column=c).border = Border(top=THIN)
    row += 2
    for text in (DISCLAIMER, *(f"Нет в каталоге: {m}" for m in bom.missing)):
        ws.cell(row=row, column=1, value=text).font = Font(italic=True, color="475569")
        row += 1
    ws.freeze_panes = "A4"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
