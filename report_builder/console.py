"""
Terminal rendering.

The workbook is the deliverable; this is what the operator sees when the command
runs, and what a scheduled run leaves in its log. It states how many rows went
in, how many values could not be used and why, and what each section produced.
"""
from __future__ import annotations

from decimal import Decimal

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .aggregate import SectionResult
from .quality import Dataset

#: Blue rather than red: an unusable value is information, not an accusation.
FLAG = "#5FA8FF"


def render_run(config_title: str, source_name: str, dataset: Dataset,
               sections: list[SectionResult], console: Console) -> None:
    """Print the whole run: what was read, what was excluded, what was produced."""
    facts = Table.grid(padding=(0, 2))
    facts.add_column(style="bold")
    facts.add_column()
    facts.add_row("Report", config_title)
    facts.add_row("Source", source_name)
    facts.add_row("Rows read", str(dataset.total))
    flagged = len(dataset.flagged)
    facts.add_row(
        "Rows with a flagged value",
        Text(str(flagged), style=FLAG if flagged else "#3FB950"),
    )
    console.print(Panel(facts, title="Run", border_style="cyan", expand=False))

    tally = dataset.counts_by_verdict()
    if tally:
        console.print()
        excluded = Table(
            title="Excluded values",
            header_style="bold", border_style="grey37",
        )
        excluded.add_column("Reason", no_wrap=True)
        excluded.add_column("Values", justify="right", no_wrap=True)
        for reason, count in sorted(tally.items()):
            excluded.add_row(Text(reason, style=FLAG), str(count))
        console.print(excluded)
        console.print(
            "[dim]Excluded from the figures, never replaced or estimated. Every one of "
            "them is listed with its reason in the Data sheet.[/dim]"
        )

    console.print()
    overview = Table(title="Sections", header_style="bold", border_style="grey37")
    overview.add_column("Section", no_wrap=True)
    overview.add_column("Groups", justify="right", no_wrap=True)
    overview.add_column("Chart", no_wrap=True)
    overview.add_column("Values excluded", justify="right", no_wrap=True)
    overview.add_column("Why", overflow="fold")

    for result in sections:
        excluded_count = result.excluded_total + result.rows_without_key
        why = []
        if result.rows_without_key:
            why.append(f"{result.rows_without_key} row(s) had no usable grouping value")
        if result.excluded_total:
            why.append(f"{result.excluded_total} value(s) unusable across the figures")
        overview.add_row(
            result.section.name,
            str(len(result.rows)),
            result.section.chart.type if result.section.chart else Text("—", style="dim"),
            Text(str(excluded_count), style=FLAG if excluded_count else "#3FB950"),
            "; ".join(why),
        )
    console.print(overview)


def render_preview(sections: list[SectionResult], console: Console, rows: int = 6) -> None:
    """Show the first rows of each section's table, as they appear in the workbook."""
    for result in sections:
        if not result.rows:
            continue
        table = Table(
            title=result.section.name, header_style="bold", border_style="grey37",
        )
        for label in result.key_labels:
            table.add_column(label, no_wrap=True)
        for label in result.figure_labels():
            table.add_column(label, justify="right", no_wrap=True)

        for line in result.rows[:rows]:
            cells = list(line.keys)
            for figure in line.figures:
                if figure.value is None:
                    cells.append(Text("no usable value", style=FLAG))
                elif isinstance(figure.value, Decimal):
                    text = f"{figure.value:,.2f}".replace(",", " ")
                    cells.append(
                        Text(text + (" *" if figure.rows_excluded else ""),
                             style=FLAG if figure.rows_excluded else "")
                    )
                else:
                    cells.append(str(figure.value))
            table.add_row(*cells)

        console.print(table)
        hidden = len(result.rows) - min(len(result.rows), rows)
        if hidden:
            console.print(f"[dim]... and {hidden} more group(s) in the workbook.[/dim]")
        console.print()

    console.print("[dim]* the figure excludes at least one row; the workbook says which.[/dim]")
