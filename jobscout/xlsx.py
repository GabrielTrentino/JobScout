"""Planilha .xlsx mínima, só com a biblioteca padrão: abas, cabeçalho em negrito, filtro e primeira linha fixa."""

from __future__ import annotations

import io
import re
import zipfile
from typing import Any, Sequence
from xml.sax.saxutils import escape

# Caracteres de controle que o XML não aceita (sobram de PDFs e de páginas copiadas).
INVALID_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
SHEET_NAME_INVALID = re.compile(r"[\[\]:*?/\\]")
MAX_CELL = 32767
MAX_WIDTH = 60

Sheet = tuple[str, Sequence[str], Sequence[Sequence[Any]]]


def column(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    name = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        name = chr(65 + rest) + name
    return name


def sheet_name(name: str, used: set[str]) -> str:
    base = SHEET_NAME_INVALID.sub(" ", name).strip()[:31] or "Planilha"
    candidate, counter = base, 2
    while candidate.lower() in used:
        suffix = f" ({counter})"
        candidate = base[: 31 - len(suffix)] + suffix
        counter += 1
    used.add(candidate.lower())
    return candidate


def repr_sheet(name: str) -> str:
    """Nome da aba como aparece numa fórmula: entre aspas simples, com aspas internas dobradas."""
    return "'" + name.replace("'", "''") + "'"


def _cell(ref: str, value: Any, style: int = 0) -> str:
    style_attr = f' s="{style}"' if style else ""
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return f'<c r="{ref}" t="b"{style_attr}><v>{int(value)}</v></c>'
    if isinstance(value, (int, float)):
        return f'<c r="{ref}"{style_attr}><v>{value}</v></c>'
    text = INVALID_XML.sub("", str(value))[:MAX_CELL]
    return f'<c r="{ref}" t="inlineStr"{style_attr}><is><t xml:space="preserve">{escape(text)}</t></is></c>'


def _width(values: list[Any]) -> int:
    longest = max((len(line) for value in values for line in str(value if value is not None else "").splitlines() or [""]), default=0)
    return max(8, min(MAX_WIDTH, longest + 2))


def _sheet_xml(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    last = column(max(len(headers), 1) - 1)
    widths = [_width([header] + [row[i] if i < len(row) else "" for row in rows[:500]]) for i, header in enumerate(headers)]
    cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{width}" customWidth="1"/>' for i, width in enumerate(widths))
    lines = ['<row r="1">' + "".join(_cell(f"{column(i)}1", header, 1) for i, header in enumerate(headers)) + "</row>"]
    for number, row in enumerate(rows, start=2):
        cells = "".join(_cell(f"{column(i)}{number}", value) for i, value in enumerate(row))
        lines.append(f'<row r="{number}">{cells}</row>')
    end = len(rows) + 1
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        + (f"<cols>{cols}</cols>" if cols else "")
        + f'<sheetData>{"".join(lines)}</sheetData>'
        + f'<autoFilter ref="A1:{last}{end}"/>'
        + "</worksheet>"
    )


STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FFE9EDF2"/><bgColor indexed="64"/></patternFill></fill></fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/></cellXfs>'
    "</styleSheet>"
)


def build(sheets: Sequence[Sheet]) -> bytes:
    """sheets: (nome da aba, cabeçalhos, linhas). Devolve o arquivo .xlsx."""
    if not sheets:
        raise ValueError("Escolha pelo menos uma aba.")
    used: set[str] = set()
    names = [sheet_name(name, used) for name, _, _ in sheets]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        overrides = "".join(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for i in range(1, len(sheets) + 1)
        )
        archive.writestr("[Content_Types].xml", (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            f"{overrides}</Types>"
        ))
        archive.writestr("_rels/.rels", (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>"
        ))
        quote = {'"': "&quot;"}
        sheet_tags = "".join(
            f'<sheet name="{escape(name, quote)}" sheetId="{i}" r:id="rId{i}"/>' for i, name in enumerate(names, start=1)
        )
        # O Excel guarda o intervalo do filtro também como nome definido; sem ele, reclama ao abrir.
        defined = "".join(
            f'<definedName name="_xlnm._FilterDatabase" localSheetId="{i}" hidden="1">'
            f"{escape(repr_sheet(name))}!$A$1:${column(max(len(headers), 1) - 1)}${len(rows) + 1}</definedName>"
            for i, (name, (_, headers, rows)) in enumerate(zip(names, sheets))
        )
        archive.writestr("xl/workbook.xml", (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f"<sheets>{sheet_tags}</sheets><definedNames>{defined}</definedNames></workbook>"
        ))
        rels = "".join(
            f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
            for i in range(1, len(sheets) + 1)
        )
        styles_id = len(sheets) + 1
        archive.writestr("xl/_rels/workbook.xml.rels", (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'{rels}<Relationship Id="rId{styles_id}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            "</Relationships>"
        ))
        archive.writestr("xl/styles.xml", STYLES)
        for i, (_, headers, rows) in enumerate(sheets, start=1):
            archive.writestr(f"xl/worksheets/sheet{i}.xml", _sheet_xml(headers, rows))
    return buffer.getvalue()
