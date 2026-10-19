"""Local copy of the accounts in the template layout, one workbook per year.

Rebuilt from scratch on every run; your edits live in the Google Sheet."""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.worksheet.datavalidation import DataValidation

from .accounts import (
    TO_UPDATE, XLSX_LAST_ROW, YEAR_SUMMARY, Tab, month_layout, month_links, to_update_table, trip_layout,
    year_summary_cells,
)
from .config import Config

MONTH_WIDTHS = {"A": 12, "B": 34, "C": 16, "D": 12, "E": 14, "F": 22, "H": 18, "I": 14, "K": 16,
                "L": 14, "N": 12, "O": 30, "P": 12, "Q": 22, "S": 12, "T": 14}
TRIP_WIDTHS = {"A": 12, "B": 30, "C": 14, "D": 12, "E": 14, "F": 20, "H": 12, "I": 28, "J": 14,
               "K": 14, "L": 14, "M": 18, "O": 24, "P": 12, "Q": 12, "R": 26, "S": 14, "T": 18}


def write_accounts_xlsx(out_dir: Path, tabs_by_year: dict[int, list[Tab]], config: Config) -> list[Path]:
    paths = []
    for year, tabs in tabs_by_year.items():
        wb = Workbook()
        wb.remove(wb.active)
        months = [t.title for t in tabs if t.kind == "month"]
        trips = [t.title for t in tabs if t.kind == "trip"]
        links = month_links(months, config.trips, set(trips))
        _fill_to_update(wb.create_sheet(TO_UPDATE), tabs)
        for tab in tabs:
            ws = wb.create_sheet(tab.title)
            if tab.kind == "month":
                _fill_month(ws, tab, config, links[tab.title])
            else:
                _fill_trip(ws, tab, config)
        summary = wb.create_sheet(YEAR_SUMMARY)
        for cell, value in year_summary_cells(months, trips).items():
            summary[cell] = value
        summary.column_dimensions["A"].width = 18
        summary.column_dimensions["B"].width = 14

        path = out_dir / (config.google.spreadsheet.replace("{year}", str(year)) + ".xlsx")
        path.parent.mkdir(parents=True, exist_ok=True)
        wb.save(path)
        paths.append(path)
    return paths


def _fill_to_update(ws, tabs: list[Tab]) -> None:
    for row in to_update_table(tabs):
        ws.append(row)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row in ws.iter_rows(min_row=2):
        row[0].number_format = "dd/mm/yyyy"
        row[1].number_format = "+#,##0.00;-#,##0.00"
    for col, w in {"A": 12, "B": 12, "C": 26, "D": 56, "E": 26, "F": 26, "G": 16}.items():
        ws.column_dimensions[col].width = w
    ws.column_dimensions["H"].hidden = True
    ws.freeze_panes = "A2"


def _rows(ws, tab: Tab, kind: str, cols: str, date_col: str, amount_col: str) -> None:
    for i, r in enumerate((r for r in tab.rows if r.kind == kind), start=tab.first_row):
        for col, v in zip(cols, r.values()):
            ws[f"{col}{i}"] = v
        ws[f"{date_col}{i}"].number_format = "dd/mm/yyyy"
        ws[f"{amount_col}{i}"].number_format = "#,##0.00"


def _dropdowns(ws, config: Config, first_row: int, pairs: list[tuple[str, list[str]]]) -> None:
    for col, values in pairs:
        dv = DataValidation(type="list", formula1='"' + ",".join(values) + '"', allow_blank=True)
        dv.add(f"{col}{first_row}:{col}{XLSX_LAST_ROW}")
        ws.add_data_validation(dv)


def _fill_month(ws, tab: Tab, config: Config, links: dict) -> None:
    for cell, value in {**month_layout(config, open_ended=False), **links}.items():
        ws[cell] = value
    for cell in ("A1", "N1"):
        ws[cell].font = Font(bold=True, size=12)
    _rows(ws, tab, "spend", "ABCDEFG", "A", "D")
    _rows(ws, tab, "earn", "NOPQR", "N", "P")
    for col in ("I", "L", "T"):
        for row in range(tab.first_row, tab.first_row + len(config.categories) + 2):
            ws[f"{col}{row}"].number_format = "#,##0.00"
    _dropdowns(ws, config, tab.first_row, [("C", config.categories), ("E", config.importance)])
    for col, w in MONTH_WIDTHS.items():
        ws.column_dimensions[col].width = w
    ws.column_dimensions["G"].hidden = True
    ws.column_dimensions["R"].hidden = True
    ws.freeze_panes = "A3"


def _fill_trip(ws, tab: Tab, config: Config) -> None:
    for cell, value in trip_layout(tab.trip, config, open_ended=False).items():
        ws[cell] = value
    ws["A1"].font = Font(bold=True, size=14)
    _rows(ws, tab, "spend", "ABCDEFG", "A", "D")
    for row in range(4, 14):
        ws[f"P{row}"].number_format = "#,##0.00"
    if tab.trip.currency:
        ws["P6"].number_format = "0.00000"
    pairs = [("C", config.categories), ("E", config.importance)]
    if tab.trip.currency:
        pairs += [("J", config.categories), ("L", config.importance)]
    _dropdowns(ws, config, tab.first_row, pairs)
    for col, w in TRIP_WIDTHS.items():
        ws.column_dimensions[col].width = w
    ws.column_dimensions["G"].hidden = True
    ws.freeze_panes = "A4"
