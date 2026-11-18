"""
Turning a spreadsheet into passages a retriever can use.

A table is not prose. Splitting it on a token budget — what every other
format here does — produces chunks that start mid-row and lose the
header, so a passage reads `| 120 | USD |` with no hint of what the 120
measures. Neither the embedding model nor a reader can recover that.

So a table is chunked by *row*, and every chunk repeats the column names
it belongs to:

    Sheet: Prices
    | Product | Price | Unit |
    | --- | --- | --- |
    | Widget A | 120 | USD |

One row per chunk is deliberate. The acceptance criterion is "searching
a word in a cell returns that row", not "a block containing it": a
retriever that answers a price question with forty neighbouring rows is
not usable.

The row cap is the other half of that decision. A 5 MB sheet can hold
tens of thousands of rows, and each one costs an embedding call, so the
default stops at `TABULAR_MAX_ROWS` and says so in the log rather than
quietly queueing an hour of inference.
"""

import io
import logging
import math
import os
from datetime import date

import pandas as pd
from openpyxl import load_workbook

from ..filetypes import CSV_MIME


logger = logging.getLogger(__name__)


# How many rows one file may contribute. Raising this multiplies the
# embedding cost one-for-one, which is why it is an environment knob and
# not a constant buried in the loop.
MAX_ROWS = int(os.getenv("TABULAR_MAX_ROWS", "2000"))

# A wide sheet is usually a formatting accident (a stray value in column
# XFD). The first 40 columns are what a person reads.
MAX_COLUMNS = 40

# Per-cell and per-row budgets, in characters. One row has to stay
# inside a single embedding window; e5 truncates at 512 tokens, and
# 1200 characters is comfortably below that while still holding a full
# row of a normal table.
MAX_CELL_CHARS = 200
MAX_ROW_CHARS = 1200


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _cell_text(value):
    """
    One cell as the string a person would read.

    Spreadsheets store `120` as a float, so the naive conversion renders
    a price column as `120.0` and a phone number as `9.12e+09`. Both are
    wrong in a passage that is supposed to be quotable.
    """

    if value is None:
        return ""

    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return ""

        if value.is_integer():
            return str(int(value))

    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"

    if isinstance(value, date):
        return value.isoformat()

    return str(value).strip()


def _truncate(text, limit):
    if len(text) <= limit:
        return text

    return text[: limit - 1].rstrip() + "…"


def _normalize_header(values):
    """
    Column names that survive being repeated in every chunk.

    Blank headers get a positional name and duplicates get a suffix,
    because `| Price | Price |` in a passage tells the reader nothing
    about which column the number came from.
    """

    header = []
    seen = {}

    for index, value in enumerate(values):
        name = _cell_text(value) or f"Column {index + 1}"
        name = _truncate(name, MAX_CELL_CHARS)

        if name in seen:
            seen[name] += 1
            name = f"{name} ({seen[name]})"
        else:
            seen[name] = 1

        header.append(name)

    return header


def _looks_like_header(values):
    """
    True when the first non-empty row is labels rather than data.

    A price list exported without headers starts with numbers, and
    swallowing its first row as a header would silently drop a record.
    """

    texts = [_cell_text(value) for value in values]
    texts = [text for text in texts if text]

    if not texts:
        return False

    return not any(
        _is_number(value)
        for value in values
        if value is not None
    )


def _row_line(cells):
    return "| " + " | ".join(cells) + " |"


def _render_block(sheet, header, values):
    cells = [
        _truncate(_cell_text(value), MAX_CELL_CHARS)
        for value in values[: len(header)]
    ]

    # Keep the table rectangular: a short row must not shift the meaning
    # of the columns after it.
    cells.extend([""] * (len(header) - len(cells)))

    lines = []

    if sheet:
        lines.append(f"Sheet: {sheet}")

    lines.append(_row_line(header))
    lines.append(_row_line(["---"] * len(header)))
    lines.append(_row_line(cells))

    return _truncate("\n".join(lines), MAX_ROW_CHARS)


def _rows_from_sheet(sheet):
    blocks = []
    header = None

    for raw in sheet.iter_rows(values_only=True):
        values = list(raw[:MAX_COLUMNS])

        if not any(_cell_text(value) for value in values):
            continue

        if header is None:
            if _looks_like_header(values):
                header = _normalize_header(values)
                continue

            header = [
                f"Column {index + 1}"
                for index in range(len(values))
            ]

        blocks.append(_render_block(sheet.title, header, values))

        if len(blocks) >= MAX_ROWS:
            break

    return blocks


def _rows_from_workbook(file):
    file.seek(0)

    # `read_only` streams the sheet instead of materialising a workbook,
    # and `data_only` returns the cached result of a formula instead of
    # the string "=B2*C2" — which is what a price column needs.
    workbook = load_workbook(file, read_only=True, data_only=True)

    blocks = []

    try:
        for sheet in workbook.worksheets:
            blocks.extend(_rows_from_sheet(sheet))

            if len(blocks) >= MAX_ROWS:
                break
    finally:
        workbook.close()

    return blocks


def _rows_from_csv(file):
    file.seek(0)
    raw = file.read()

    # Decoded here rather than handed to pandas as bytes. The upload
    # already proved the file is UTF-8; doing it in one place means the
    # parser always receives text, and a Django storage handle (which is
    # not a `BytesIO`) cannot trip pandas' binary/text detection — that
    # mismatch surfaced as `TypeError: a bytes-like object is required`
    # inside the worker, after the upload had been accepted.
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(
            "The CSV is not valid UTF-8. Re-export it as UTF-8."
        ) from exc

    try:
        # `sep=None` with the python engine sniffs the delimiter, so a
        # semicolon-separated export from a European Excel opens as
        # columns instead of one long column. `dtype=str` keeps leading
        # zeros and long identifiers intact; `keep_default_na=False`
        # keeps an empty cell empty instead of NaN.
        frame = pd.read_csv(
            io.StringIO(text),
            sep=None,
            engine="python",
            dtype=str,
            keep_default_na=False,
            nrows=MAX_ROWS + 1,
        )
    except pd.errors.ParserError:
        # Sniffing failed (a single-column file, for instance). A comma
        # is the format's own default, so fall back to it rather than
        # refusing a file that a spreadsheet would open fine.
        frame = pd.read_csv(
            io.StringIO(text),
            dtype=str,
            keep_default_na=False,
            nrows=MAX_ROWS + 1,
        )

    header = _normalize_header(list(frame.columns))

    return [
        _render_block(None, header, list(row))
        for row in frame.itertuples(index=False, name=None)
    ]


def extract_tabular_rows(file, file_type):
    """
    Every row of a spreadsheet or CSV as one self-contained passage.

    Returns a list of chunk contents, ready to be written to
    `DocumentChunk` without going through the token chunker.
    """

    if file_type == CSV_MIME:
        rows = _rows_from_csv(file)
    else:
        rows = _rows_from_workbook(file)

    if len(rows) > MAX_ROWS:
        logger.warning(
            "Table truncated at %s rows; the file holds more.",
            MAX_ROWS,
        )

        rows = rows[:MAX_ROWS]

    return rows
