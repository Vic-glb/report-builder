"""
Native Excel charts.

These are real chart objects, built by openpyxl and bound to cell ranges on a
visible worksheet — not pictures. Opening the workbook and editing a number in
the section table moves the chart, which is the whole reason for choosing native
charts over rendered images.

The appearance is whatever openpyxl and the spreadsheet application produce. No
attempt is made to restyle it: a chart that looks hand-designed but cannot be
edited would be the exact kind of false front this tool avoids.
"""
from __future__ import annotations

from openpyxl.chart import BarChart, LineChart, PieChart, Reference

from .config import ChartSpec


def build_chart(spec: ChartSpec, sheet, first_row: int, last_row: int,
                key_columns: int, value_columns: dict[str, int]):
    """Create a chart bound to a range on `sheet`.

    Args:
        spec: What the configuration asked for.
        sheet: The worksheet holding the section table.
        first_row: 1-based row of the table header.
        last_row: 1-based row of the last data row.
        key_columns: How many leading columns hold the group keys.
        value_columns: Figure label to its 1-based column index.

    Returns:
        An openpyxl chart, or None when the section has no rows to plot.
    """
    if last_row <= first_row:
        return None

    chart = _new(spec.type)
    chart.title = spec.title or None
    chart.height = spec.height
    chart.width = spec.width

    # Categories are the first key column. A section grouped by two keys still
    # plots against the first one; the table beside the chart carries the rest.
    categories = Reference(sheet, min_col=1, min_row=first_row + 1, max_row=last_row)

    plotted = 0
    for label in spec.values:
        column = value_columns.get(label)
        if column is None:
            continue
        data = Reference(sheet, min_col=column, min_row=first_row, max_row=last_row)
        # from_rows=False with titles_from_data reads the header cell as the
        # series name, which is what puts a readable legend on the chart.
        chart.add_data(data, titles_from_data=True)
        plotted += 1

    if not plotted:
        return None

    chart.set_categories(categories)

    if isinstance(chart, BarChart):
        chart.type = "bar" if spec.type == "bar" else "col"
        chart.gapWidth = 60
    if isinstance(chart, PieChart):
        # A pie with one series only; the legend carries the category names.
        chart.dataLabels = None

    return chart


def _new(kind: str):
    if kind in ("bar", "column"):
        chart = BarChart()
        chart.type = "bar" if kind == "bar" else "col"
        return chart
    if kind == "line":
        return LineChart()
    return PieChart()
