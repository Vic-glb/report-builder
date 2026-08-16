"""
Grouping and aggregation.

A section produces a small table: one row per group, one column per figure. Rows
whose values the figure could not use are left out of that figure and counted, so
the report can say "this total is built from 118 of 124 rows" instead of quietly
presenting a smaller number as if it were complete.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .config import Aggregation, ReportConfig, Section, _grouper_column
from .quality import Dataset, Row


@dataclass
class Figure:
    """One computed value, and how much of the data it rests on."""

    label: str
    value: Decimal | int | None
    rows_used: int
    rows_excluded: int

    @property
    def complete(self) -> bool:
        return self.rows_excluded == 0


@dataclass
class GroupRow:
    """One line of a section's table."""

    keys: list[str]
    figures: list[Figure]


@dataclass
class SectionResult:
    """A section's table, ready to be written to a sheet."""

    section: Section
    key_labels: list[str]
    rows: list[GroupRow] = field(default_factory=list)
    #: Rows dropped because a grouping key could not be read.
    rows_without_key: int = 0
    #: Reasons for those, so the summary can explain them.
    key_notes: list[str] = field(default_factory=list)

    @property
    def excluded_total(self) -> int:
        return sum(f.rows_excluded for row in self.rows for f in row.figures)

    def figure_labels(self) -> list[str]:
        return [a.label for a in self.section.aggregations]


def build_section(dataset: Dataset, section: Section, config: ReportConfig) -> SectionResult:
    """Group the rows and compute every figure of one section."""
    key_labels = [_key_label(key) for key in section.group_by]
    result = SectionResult(section=section, key_labels=key_labels)

    groups: dict[tuple[str, ...], list[Row]] = {}
    reasons: set[str] = set()

    for row in dataset.rows:
        key = _key_for(row, section.group_by, config)
        if key is None:
            result.rows_without_key += 1
            for spec in section.group_by:
                _, column = _grouper_column(spec)
                cell = row.cell(column)
                if not cell.usable:
                    reasons.add(f"{column}: {cell.note or cell.verdict.value}")
            continue
        groups.setdefault(key, []).append(row)

    result.key_notes = sorted(reasons)

    for key, rows in groups.items():
        figures = [_compute(aggregation, rows) for aggregation in section.aggregations]
        result.rows.append(GroupRow(keys=list(key), figures=figures))

    _sort(result, section)
    if section.top:
        result.rows = result.rows[:section.top]
    return result


def _sort(result: SectionResult, section: Section) -> None:
    if section.sort_by:
        index = [a.label for a in section.aggregations].index(section.sort_by)
        # None sorts last: a group whose figure could not be computed should not
        # be presented as the smallest.
        result.rows.sort(
            key=lambda row: (row.figures[index].value is None,
                             -(row.figures[index].value or 0)),
        )
    else:
        result.rows.sort(key=lambda row: row.keys)


def _key_for(row: Row, group_by: list[str], config: ReportConfig) -> tuple[str, ...] | None:
    """Build a row's group key, or None when a key value is unusable."""
    parts: list[str] = []
    for spec in group_by:
        grouper, column = _grouper_column(spec)
        cell = row.cell(column)
        if not cell.usable:
            return None
        if grouper is None:
            parts.append(str(cell.value))
            continue
        if not isinstance(cell.value, date):
            return None
        parts.append(_bucket(cell.value, grouper))
    return tuple(parts)


def _bucket(value: date, grouper: str) -> str:
    """Turn a date into a group label. Labels sort chronologically as text."""
    if grouper == "year":
        return f"{value.year}"
    if grouper == "quarter":
        return f"{value.year}-Q{(value.month - 1) // 3 + 1}"
    if grouper == "month":
        return f"{value.year}-{value.month:02d}"
    if grouper == "week":
        iso = value.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    return value.isoformat()


def _key_label(spec: str) -> str:
    grouper, column = _grouper_column(spec)
    return f"{column} ({grouper})" if grouper else column


def _compute(aggregation: Aggregation, rows: list[Row]) -> Figure:
    """Compute one figure over a group, excluding the values it cannot use."""
    usable = [row for row in rows if row.cell(aggregation.column).usable]
    excluded = len(rows) - len(usable)

    if aggregation.function == "count":
        return Figure(aggregation.label, len(usable), len(usable), excluded)

    if aggregation.function == "count_distinct":
        distinct = {str(row.cell(aggregation.column).value) for row in usable}
        return Figure(aggregation.label, len(distinct), len(usable), excluded)

    numbers = [row.cell(aggregation.column).value for row in usable]
    numbers = [n for n in numbers if isinstance(n, Decimal)]
    excluded += len(usable) - len(numbers)

    if not numbers:
        # No value at all: the figure is unknown, and says so. Returning 0 here
        # would be indistinguishable from a genuine zero.
        return Figure(aggregation.label, None, 0, excluded)

    if aggregation.function == "sum":
        value = sum(numbers, Decimal(0))
    elif aggregation.function == "mean":
        value = (sum(numbers, Decimal(0)) / len(numbers)).quantize(Decimal("0.01"))
    elif aggregation.function == "min":
        value = min(numbers)
    else:
        value = max(numbers)

    return Figure(aggregation.label, value, len(numbers), excluded)


def build_all(dataset: Dataset, config: ReportConfig) -> list[SectionResult]:
    return [build_section(dataset, section, config) for section in config.sections]
