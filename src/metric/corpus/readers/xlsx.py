"""XLSX reader.

A spreadsheet is the format most likely to hold the constraints that matter — the
intake sheets this project is replacing are spreadsheets — so the header rule is
applied strictly: the first row carrying values is the header, and every later row
becomes one block with that header prepended to each cell.

Locations are `sheet:Name!r4`, which is what a reviewer can navigate to.

Formulas are read as their cached values, not their source. A triple citing
`=B2*3` would quote something no reader of the sheet ever sees; a workbook saved
without cached values is refused rather than read as blanks.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from metric.corpus.blocks import RawBlock, row_text
from metric.corpus.readers.errors import UnreadableDocument


def read_xlsx(path: Path, *, doc_label: str = "") -> list[RawBlock]:
    workbook = _open(path)
    label = doc_label or path.stem

    blocks: list[RawBlock] = []
    empty_sheets: list[str] = []

    try:
        for sheet in workbook.worksheets:
            sheet_blocks = _sheet(sheet, label)
            if sheet_blocks:
                blocks.extend(sheet_blocks)
            else:
                empty_sheets.append(sheet.title)
    finally:
        workbook.close()

    if not blocks:
        raise UnreadableDocument(
            f"{path.name}: no readable rows in any sheet ({', '.join(empty_sheets)}). "
            "A workbook saved without cached formula values reads as blank; re-save it "
            "from Excel, or supply the values."
        )
    return blocks


def _sheet(sheet: Any, label: str) -> list[RawBlock]:
    rows = [
        (number, [_cell(value) for value in values])
        for number, values in enumerate(sheet.iter_rows(values_only=True), start=1)
    ]
    populated = [(number, cells) for number, cells in rows if any(c.strip() for c in cells)]
    if len(populated) < 2:
        return []

    _, header = populated[0]
    heading_path = (label, sheet.title)
    return [
        RawBlock(
            location=f"{label}:sheet:{sheet.title}!r{number}",
            kind="table",
            heading_path=heading_path,
            text=row_text(header, cells),
        )
        for number, cells in populated[1:]
    ]


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return " ".join(str(value).split())


def _open(path: Path) -> Any:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise UnreadableDocument(
            f"{path.name}: reading XLSX needs openpyxl. Install metric[xlsx]."
        ) from exc

    try:
        return load_workbook(filename=str(path), read_only=True, data_only=True)
    except Exception as exc:
        raise UnreadableDocument(f"{path.name}: could not be opened as XLSX ({exc}).") from exc
