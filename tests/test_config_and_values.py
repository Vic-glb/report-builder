"""Tests for the configuration loader and value parsing."""
import json
from datetime import date
from decimal import Decimal

import pytest

from report_builder.config import ConfigError, ReportConfig, _grouper_column
from report_builder.values import parse_date, parse_number


def config(spec: dict) -> ReportConfig:
    return ReportConfig.from_dict(spec)


MINIMAL = {
    "sections": [{
        "name": "S", "group_by": ["region"],
        "aggregations": [{"column": "amount", "function": "sum", "label": "Total"}],
    }]
}


# ----------------------------------------------------------------- configuration


def test_a_minimal_configuration_loads():
    loaded = config(MINIMAL)

    assert len(loaded.sections) == 1
    assert loaded.sections[0].aggregations[0].label == "Total"


def test_a_configuration_without_sections_is_refused():
    with pytest.raises(ConfigError, match="at least one section"):
        config({"title": "x"})


def test_a_section_without_group_by_is_refused():
    with pytest.raises(ConfigError, match="group_by"):
        config({"sections": [{"name": "S", "aggregations": [
            {"column": "a", "function": "sum"}]}]})


def test_an_unknown_function_names_the_valid_ones():
    with pytest.raises(ConfigError, match="count_distinct"):
        config({"sections": [{"name": "S", "group_by": ["r"], "aggregations": [
            {"column": "a", "function": "median"}]}]})


def test_an_unknown_column_type_is_refused():
    spec = dict(MINIMAL, columns={"amount": {"type": "money"}})
    with pytest.raises(ConfigError, match="unknown type"):
        config(spec)


def test_an_unknown_chart_type_is_refused():
    spec = {"sections": [{
        "name": "S", "group_by": ["r"],
        "aggregations": [{"column": "a", "function": "sum", "label": "T"}],
        "chart": {"type": "radar", "values": ["T"]},
    }]}
    with pytest.raises(ConfigError, match="unknown chart type"):
        config(spec)


def test_a_chart_plotting_a_figure_the_section_does_not_compute_is_refused():
    # This is the mistake that would otherwise produce a silently empty chart.
    spec = {"sections": [{
        "name": "S", "group_by": ["r"],
        "aggregations": [{"column": "a", "function": "sum", "label": "Total"}],
        "chart": {"type": "column", "values": ["Profit"]},
    }]}
    with pytest.raises(ConfigError, match="does not compute"):
        config(spec)


def test_a_pie_chart_cannot_plot_two_series():
    spec = {"sections": [{
        "name": "S", "group_by": ["r"],
        "aggregations": [
            {"column": "a", "function": "sum", "label": "A"},
            {"column": "b", "function": "sum", "label": "B"},
        ],
        "chart": {"type": "pie", "values": ["A", "B"]},
    }]}
    with pytest.raises(ConfigError, match="pie chart"):
        config(spec)


def test_two_aggregations_cannot_share_a_label():
    spec = {"sections": [{
        "name": "S", "group_by": ["r"],
        "aggregations": [
            {"column": "a", "function": "sum", "label": "Total"},
            {"column": "b", "function": "sum", "label": "Total"},
        ],
    }]}
    with pytest.raises(ConfigError, match="share the label"):
        config(spec)


def test_sort_by_must_name_a_figure_of_the_section():
    spec = {"sections": [{
        "name": "S", "group_by": ["r"], "sort_by": "Nope",
        "aggregations": [{"column": "a", "function": "sum", "label": "Total"}],
    }]}
    with pytest.raises(ConfigError, match="sort_by"):
        config(spec)


def test_an_unknown_grouper_is_refused():
    spec = {"sections": [{
        "name": "S", "group_by": ["fortnight(order_date)"],
        "aggregations": [{"column": "a", "function": "sum", "label": "T"}],
    }]}
    with pytest.raises(ConfigError, match="unknown grouping"):
        config(spec)


def test_broken_json_names_the_file(tmp_path):
    path = tmp_path / "c.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(ConfigError, match="not valid JSON"):
        ReportConfig.load(path)


def test_columns_used_lists_every_column_the_report_reads():
    spec = {"sections": [
        {"name": "A", "group_by": ["month(order_date)"],
         "aggregations": [{"column": "net", "function": "sum", "label": "N"}]},
        {"name": "B", "group_by": ["region"],
         "aggregations": [{"column": "qty", "function": "sum", "label": "Q"}]},
    ]}
    assert config(spec).columns_used() == {"order_date", "net", "region", "qty"}


def test_grouper_syntax_is_parsed():
    assert _grouper_column("month(order_date)") == ("month", "order_date")
    assert _grouper_column("region") == (None, "region")


def test_the_bundled_sample_configuration_is_valid():
    loaded = ReportConfig.load(__import__("pathlib").Path("samples/sample_report.json"))

    assert len(loaded.sections) == 4
    assert [s.chart.type for s in loaded.sections if s.chart] == ["column", "bar", "pie"]


# ------------------------------------------------------------------------ values


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2026-01-05", date(2026, 1, 5)),
        ("05.01.2026", date(2026, 1, 5)),
        ("31.12.2026", date(2026, 12, 31)),
        ("12 kwietnia 2026", date(2026, 4, 12)),
    ],
)
def test_dates_are_parsed(raw, expected):
    assert parse_date(raw) == expected


@pytest.mark.parametrize("raw", ["", "do ustalenia", "brak", "32.13.2026"])
def test_unreadable_dates_return_none(raw):
    assert parse_date(raw) is None


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1 234,56", Decimal("1234.56")),
        ("1,234.56", Decimal("1234.56")),
        ("1.234,56", Decimal("1234.56")),
        ("2 500,00 zł", Decimal("2500.00")),
        ("(150,00)", Decimal("-150.00")),
    ],
)
def test_numbers_are_parsed(raw, expected):
    assert parse_number(raw) == expected


@pytest.mark.parametrize("raw", ["", "do ustalenia", "n/a"])
def test_unreadable_numbers_return_none(raw):
    assert parse_number(raw) is None
