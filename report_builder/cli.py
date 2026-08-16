"""
Command line entry point.

    python -m report_builder build sales.csv --config report.json --out report.xlsx
    python -m report_builder demo

Exit codes are distinct so a scheduled run can tell the cases apart:
`0` the report was written, `1` the input or the configuration could not be used,
`2` the report was written but some values had to be excluded (only with
`--fail-on-excluded`).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console

from .aggregate import build_all
from .config import ConfigError, ReportConfig
from .console import render_preview, render_run
from .image import export_png
from .quality import inspect
from .reading import ReadError, read_table
from .workbook import write_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="report-builder",
        description="Turn a CSV, Excel or JSON file into a formatted Excel report with "
                    "native charts, driven by a configuration file.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("build", help="build a report")
    run.add_argument("input", type=Path, help="source .csv, .xlsx or .json file")
    run.add_argument("--config", type=Path, required=True, help="report configuration (JSON)")
    run.add_argument("--out", type=Path, help="output .xlsx (default: <input>.report.xlsx)")
    run.add_argument("--sheet", help="worksheet name, for multi-sheet workbooks")
    run.add_argument("--no-preview", action="store_true", help="skip the section previews")
    run.add_argument("--export-png", type=Path, help="save the console output as a PNG")
    run.add_argument("--width", type=int, help="force the output width in characters")
    run.add_argument(
        "--fail-on-excluded",
        action="store_true",
        help="exit with code 2 if any value had to be excluded, for scheduled runs",
    )

    show = sub.add_parser(
        "demo",
        help="build a report from the bundled sample data and show what it produced",
    )
    show.add_argument("--samples", type=Path, default=Path("samples"),
                      help="folder holding the sample files (default: samples)")
    show.add_argument("--out", type=Path,
                      help="keep the generated workbook at this path instead of discarding it")
    show.add_argument("--export-png", type=Path, help="save the console output as a PNG")
    show.add_argument("--width", type=int, default=112, help="output width (default: 112)")
    return parser


def _generate(source: Path, config_path: Path, out: Path, console: Console,
              sheet: str | None = None):
    """Read, inspect, aggregate and write. Returns (dataset, sections) or None."""
    try:
        config = ReportConfig.load(config_path)
    except ConfigError as exc:
        console.print(f"[red]Cannot use the configuration:[/red] {exc}")
        return None

    try:
        table = read_table(source, sheet=sheet)
    except ReadError as exc:
        console.print(f"[red]Cannot read the source:[/red] {exc}")
        return None

    try:
        dataset = inspect(table, config)
    except ValueError as exc:
        console.print(f"[red]Configuration does not match the source:[/red] {exc}")
        return None

    sections = build_all(dataset, config)

    try:
        write_report(out, config, dataset, sections, source.name)
    except (OSError, ValueError) as exc:
        console.print(f"[red]Cannot write the workbook:[/red] {exc}")
        return None

    return config, dataset, sections


def run_build(args) -> int:
    exporting = bool(args.export_png)
    width = args.width or (112 if exporting else None)
    console = Console(record=exporting, width=width)

    if not args.input.exists():
        console.print(f"[red]File not found:[/red] {args.input}")
        return 1
    if not args.config.exists():
        console.print(f"[red]Configuration not found:[/red] {args.config}")
        return 1

    out = args.out or args.input.with_name(args.input.stem + ".report.xlsx")
    produced = _generate(args.input, args.config, out, console, sheet=args.sheet)
    if produced is None:
        return 1
    config, dataset, sections = produced

    render_run(config.title, args.input.name, dataset, sections, console)
    if not args.no_preview:
        console.print()
        render_preview(sections, console)

    console.print(f"\n[bold green]Report:[/bold green] {out}")

    if args.export_png:
        _save_png(console, args.export_png)

    if args.fail_on_excluded and dataset.flagged:
        console.print(
            f"[{'#5FA8FF'}]{len(dataset.flagged)} row(s) had a value that could not be "
            "used — see the Data sheet.[/]"
        )
        return 2
    return 0


def run_demo(args) -> int:
    import tempfile

    console = Console(record=bool(args.export_png), width=args.width)
    source = args.samples / "sample_sales.csv"
    config_path = args.samples / "sample_report.json"

    if not source.exists() or not config_path.exists():
        console.print(
            f"[red]Sample files not found in {args.samples}.[/red]\n"
            "Generate them first: python samples/make_samples.py"
        )
        return 1

    with tempfile.TemporaryDirectory() as scratch:
        out = args.out or Path(scratch) / "demo-report.xlsx"
        produced = _generate(source, config_path, out, console)
        if produced is None:
            return 1
        config, dataset, sections = produced

        console.print()
        render_run(config.title, source.name, dataset, sections, console)
        console.print()
        render_preview(sections, console)

        if args.out:
            console.print(f"[bold green]Workbook:[/bold green] {out}")
        else:
            console.print(
                "[dim]The workbook was written to a temporary folder and discarded. "
                "Pass --out to keep it.[/dim]"
            )

    if args.export_png:
        _save_png(console, args.export_png)
    return 0


def _save_png(console: Console, path: Path) -> None:
    try:
        export_png(console, path)
        console.print(f"[bold green]Image:[/bold green]  {path}")
    except (OSError, ValueError, ImportError) as exc:
        # The image is a convenience; failing to draw it must not fail a run
        # whose workbook was written.
        console.print(f"[yellow]Could not write the PNG:[/yellow] {exc}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "demo":
        return run_demo(args)
    return run_build(args)


if __name__ == "__main__":
    sys.exit(main())
