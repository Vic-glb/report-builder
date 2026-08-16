"""
Value quality.

Every cell the report actually uses is parsed once, here, and gets a verdict:
usable, or unusable with a reason. Unusable values are **excluded** from the
figures that would have consumed them, and the reason is written into a status
column on the data sheet of the workbook.

They are never interpolated, never carried forward from the previous row, and
never replaced by zero. Those three habits all produce a report that looks
complete and is quietly wrong, which is the failure this module exists to
prevent.

Exclusion is decided per figure, not per row: a row whose amount is unreadable
can still be counted by a `count` over another column. Blanking the whole row
would throw away good data to punish one bad cell.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum

from .config import ColumnSpec, ReportConfig
from .reading import Table
from .values import clean, parse_date, parse_number


class Verdict(str, Enum):
    OK = "ok"
    EMPTY = "empty"
    NOT_A_NUMBER = "not a number"
    NOT_A_DATE = "not a date"
    OUT_OF_RANGE = "out of range"

    @property
    def usable(self) -> bool:
        return self is Verdict.OK


@dataclass(frozen=True)
class Cell:
    """One parsed value and what became of it."""

    raw: str
    verdict: Verdict
    value: Decimal | date | str | None = None
    note: str = ""

    @property
    def usable(self) -> bool:
        return self.verdict.usable


@dataclass
class Row:
    """One source row, with its used columns parsed."""

    line: int
    raw: dict[str, str]
    cells: dict[str, Cell] = field(default_factory=dict)

    def cell(self, column: str) -> Cell:
        return self.cells.get(column, Cell(raw=self.raw.get(column, ""), verdict=Verdict.OK,
                                           value=self.raw.get(column, "")))

    def problems(self) -> list[str]:
        """Human-readable list of what is wrong with this row, if anything."""
        return [
            f"{column}: {cell.note or cell.verdict.value}"
            for column, cell in sorted(self.cells.items())
            if not cell.usable
        ]

    @property
    def status(self) -> str:
        problems = self.problems()
        return "ok" if not problems else "; ".join(problems)


@dataclass
class Dataset:
    """Every source row, parsed, plus the counts a summary needs."""

    rows: list[Row] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    used_columns: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.rows)

    @property
    def flagged(self) -> list[Row]:
        return [row for row in self.rows if row.problems()]

    def usable_for(self, columns: list[str]) -> list[Row]:
        """Rows whose every listed column is usable."""
        return [row for row in self.rows if all(row.cell(c).usable for c in columns)]

    def counts_by_verdict(self) -> dict[str, int]:
        tally: dict[str, int] = {}
        for row in self.rows:
            for cell in row.cells.values():
                if not cell.usable:
                    tally[cell.verdict.value] = tally.get(cell.verdict.value, 0) + 1
        return tally


def inspect(table: Table, config: ReportConfig) -> Dataset:
    """Parse every column the report uses, and record a verdict for each cell.

    Raises:
        ValueError: If the configuration names a column the source does not have.
            Failing here rather than producing an empty section is deliberate:
            a mistyped column name is an operator error, not missing data.
    """
    needed = config.columns_used()
    missing = [name for name in sorted(needed) if name not in table.columns]
    if missing:
        available = ", ".join(table.columns)
        raise ValueError(
            f"the configuration uses column(s) {', '.join(repr(m) for m in missing)}, "
            f"which the source does not have. Available columns: {available}"
        )

    # Columns that a section reads, plus any column the configuration declared a
    # type or a range for. Declaring a constraint is a request to enforce it,
    # even on a column no figure happens to consume — the status column is where
    # the operator finds out their data breaks it.
    checked = sorted((needed | set(config.columns)) & set(table.columns))

    rows: list[Row] = []
    for record, line in zip(table.rows, table.source_lines):
        row = Row(line=line, raw=record)
        for name in checked:
            row.cells[name] = _judge(record.get(name, ""), config.column(name), config.dayfirst)
        rows.append(row)

    return Dataset(rows=rows, columns=list(table.columns), used_columns=checked,
                   notes=list(table.notes))


def _judge(raw: str, spec: ColumnSpec, dayfirst: bool) -> Cell:
    """Parse one value against its column specification."""
    text = clean(raw)

    if not text:
        if spec.required:
            return Cell(raw=raw, verdict=Verdict.EMPTY, note="required value is empty")
        return Cell(raw=raw, verdict=Verdict.EMPTY, note="value is empty")

    if spec.type == "number":
        number = parse_number(text)
        if number is None:
            return Cell(raw=raw, verdict=Verdict.NOT_A_NUMBER,
                        note=f'"{text}" is not a number')
        if spec.minimum is not None and number < spec.minimum:
            return Cell(raw=raw, verdict=Verdict.OUT_OF_RANGE, value=number,
                        note=f"{number} is below the allowed minimum {spec.minimum}")
        if spec.maximum is not None and number > spec.maximum:
            return Cell(raw=raw, verdict=Verdict.OUT_OF_RANGE, value=number,
                        note=f"{number} is above the allowed maximum {spec.maximum}")
        return Cell(raw=raw, verdict=Verdict.OK, value=number)

    if spec.type == "date":
        parsed = parse_date(text, dayfirst=dayfirst)
        if parsed is None:
            return Cell(raw=raw, verdict=Verdict.NOT_A_DATE, note=f'"{text}" is not a date')
        return Cell(raw=raw, verdict=Verdict.OK, value=parsed)

    return Cell(raw=raw, verdict=Verdict.OK, value=text)
