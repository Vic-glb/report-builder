"""
The report configuration.

Nothing about a particular dataset is hard-coded anywhere in this tool. What the
report contains — which columns are dates or numbers, how rows are grouped, which
figures are computed, which charts are drawn — comes from a JSON file. Pointing
the tool at a different CSV means writing a different configuration, not editing
code.

A configuration mistake stops the run with a message naming the offending key.
That is deliberate: a typo in a column name belongs to the operator, and silently
producing a report with an empty section would hide it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

#: Aggregations a section can ask for.
FUNCTIONS = ("sum", "mean", "min", "max", "count", "count_distinct")

#: Chart types, mapped to their openpyxl class in `charts.py`.
CHART_TYPES = ("bar", "column", "line", "pie")

#: Derived grouping keys, written as `function(column)` in `group_by`.
GROUPERS = ("year", "quarter", "month", "week", "day")


class ConfigError(ValueError):
    """Raised when the configuration cannot be used as written."""


@dataclass
class ColumnSpec:
    """How one source column should be read and what counts as a usable value."""

    name: str
    #: "text", "date" or "number". Anything not declared is treated as text.
    type: str = "text"
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    #: When true, an empty value makes the row unusable for metrics on this column.
    required: bool = False


@dataclass
class Aggregation:
    """One figure computed over a group of rows."""

    column: str
    function: str
    label: str

    @property
    def needs_numbers(self) -> bool:
        return self.function in ("sum", "mean", "min", "max")


@dataclass
class ChartSpec:
    """A native Excel chart drawn from a section's own table."""

    type: str
    #: Labels of the aggregations to plot. Must exist in the same section.
    values: list[str]
    title: str = ""
    #: Chart height and width in centimetres, as openpyxl expects them.
    height: float = 8.0
    width: float = 16.0


@dataclass
class Section:
    """One block of the report: a grouped table, and optionally a chart."""

    name: str
    group_by: list[str]
    aggregations: list[Aggregation]
    chart: ChartSpec | None = None
    #: Sort the table by this aggregation label, descending. Empty keeps group order.
    sort_by: str = ""
    #: Keep only the first N rows after sorting. 0 keeps everything.
    top: int = 0

    def label_of(self, index: int) -> str:
        return self.aggregations[index].label


@dataclass
class ReportConfig:
    """A whole report definition."""

    title: str = "Report"
    columns: dict[str, ColumnSpec] = field(default_factory=dict)
    sections: list[Section] = field(default_factory=list)
    #: True reads 05/01/2026 as 5 January. Polish and European convention.
    dayfirst: bool = True
    #: Number format applied to aggregated figures in the workbook.
    number_format: str = "#,##0.00"
    date_format: str = "yyyy-mm-dd"

    def column(self, name: str) -> ColumnSpec:
        return self.columns.get(name, ColumnSpec(name=name))

    def columns_used(self) -> set[str]:
        """Every source column the report actually reads."""
        used: set[str] = set()
        for section in self.sections:
            for key in section.group_by:
                used.add(_grouper_column(key)[1])
            for aggregation in section.aggregations:
                used.add(aggregation.column)
        return used

    @classmethod
    def load(cls, path: Path) -> "ReportConfig":
        """Read and validate a configuration file.

        Raises:
            ConfigError: If the file is not valid JSON, or declares an unknown
                type, function, chart or grouper, or a chart plotting a figure
                the section does not compute.
        """
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{path.name} is not valid JSON: {exc}") from exc
        except OSError as exc:
            raise ConfigError(f"{path.name} could not be read: {exc}") from exc
        return cls.from_dict(raw, source=path.name)

    @classmethod
    def from_dict(cls, raw: dict, source: str = "configuration") -> "ReportConfig":
        if not isinstance(raw, dict):
            raise ConfigError(f"{source}: expected an object at the top level")

        columns: dict[str, ColumnSpec] = {}
        for name, spec in (raw.get("columns") or {}).items():
            if not isinstance(spec, dict):
                raise ConfigError(f'column "{name}": expected an object')
            declared = spec.get("type", "text")
            if declared not in ("text", "date", "number"):
                raise ConfigError(
                    f'column "{name}": unknown type "{declared}". '
                    'Expected "text", "date" or "number".'
                )
            columns[name] = ColumnSpec(
                name=name,
                type=declared,
                minimum=_decimal(spec.get("min"), f'column "{name}": min'),
                maximum=_decimal(spec.get("max"), f'column "{name}": max'),
                required=bool(spec.get("required", False)),
            )

        sections_raw = raw.get("sections")
        if not sections_raw:
            raise ConfigError(f"{source}: at least one section is required")

        sections = [_section(entry, index) for index, entry in enumerate(sections_raw, start=1)]

        return cls(
            title=raw.get("title", "Report"),
            columns=columns,
            sections=sections,
            dayfirst=bool(raw.get("dayfirst", True)),
            number_format=raw.get("number_format", "#,##0.00"),
            date_format=raw.get("date_format", "yyyy-mm-dd"),
        )


def _section(entry: dict, index: int) -> Section:
    where = f"section {index}"
    if not isinstance(entry, dict):
        raise ConfigError(f"{where}: expected an object")
    name = entry.get("name") or f"Section {index}"
    where = f'section "{name}"'

    group_by = entry.get("group_by") or []
    if not isinstance(group_by, list) or not group_by:
        raise ConfigError(f"{where}: group_by must be a non-empty list of column names")
    for key in group_by:
        grouper, _ = _grouper_column(key)
        if grouper and grouper not in GROUPERS:
            raise ConfigError(
                f'{where}: unknown grouping "{grouper}". '
                f"Expected one of {', '.join(GROUPERS)}, or a plain column name."
            )

    aggregations_raw = entry.get("aggregations") or []
    if not aggregations_raw:
        raise ConfigError(f"{where}: at least one aggregation is required")

    aggregations: list[Aggregation] = []
    seen: set[str] = set()
    for spec in aggregations_raw:
        if not isinstance(spec, dict):
            raise ConfigError(f"{where}: each aggregation must be an object")
        function = spec.get("function", "sum")
        if function not in FUNCTIONS:
            raise ConfigError(
                f'{where}: unknown function "{function}". Expected one of {", ".join(FUNCTIONS)}.'
            )
        column = spec.get("column")
        if not column:
            raise ConfigError(f"{where}: an aggregation is missing its column")
        label = spec.get("label") or f"{function} of {column}"
        if label in seen:
            raise ConfigError(f'{where}: two aggregations share the label "{label}"')
        seen.add(label)
        aggregations.append(Aggregation(column=column, function=function, label=label))

    chart = None
    chart_raw = entry.get("chart")
    if chart_raw:
        if not isinstance(chart_raw, dict):
            raise ConfigError(f"{where}: chart must be an object")
        chart_type = chart_raw.get("type", "column")
        if chart_type not in CHART_TYPES:
            raise ConfigError(
                f'{where}: unknown chart type "{chart_type}". '
                f"Expected one of {', '.join(CHART_TYPES)}."
            )
        values = chart_raw.get("values") or [aggregations[0].label]
        unknown = [v for v in values if v not in seen]
        if unknown:
            raise ConfigError(
                f'{where}: the chart plots {", ".join(repr(u) for u in unknown)}, '
                f"which this section does not compute. Available: {', '.join(sorted(seen))}."
            )
        if chart_type == "pie" and len(values) > 1:
            raise ConfigError(f"{where}: a pie chart can only plot one series")
        chart = ChartSpec(
            type=chart_type,
            values=list(values),
            title=chart_raw.get("title", name),
            height=float(chart_raw.get("height", 8.0)),
            width=float(chart_raw.get("width", 16.0)),
        )

    sort_by = entry.get("sort_by", "")
    if sort_by and sort_by not in seen:
        raise ConfigError(
            f'{where}: sort_by "{sort_by}" is not one of this section\'s figures '
            f"({', '.join(sorted(seen))})."
        )

    top = int(entry.get("top", 0) or 0)
    if top < 0:
        raise ConfigError(f"{where}: top cannot be negative")

    return Section(name=name, group_by=list(group_by), aggregations=aggregations,
                   chart=chart, sort_by=sort_by, top=top)


def _grouper_column(key: str) -> tuple[str | None, str]:
    """Split `month(order_date)` into `("month", "order_date")`.

    A plain column name returns `(None, name)`.
    """
    text = key.strip()
    if text.endswith(")") and "(" in text:
        grouper, _, rest = text.partition("(")
        return grouper.strip().lower(), rest[:-1].strip()
    return None, text


def _decimal(value, where: str) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception as exc:
        raise ConfigError(f"{where}: {value!r} is not a number") from exc
