"""Tests for the quality verdicts and the aggregation, including exclusion rules."""
from decimal import Decimal

import pytest

from report_builder.aggregate import build_section
from report_builder.config import ReportConfig
from report_builder.quality import Verdict, inspect
from report_builder.reading import Table


def table(rows: list[dict]) -> Table:
    columns = list(rows[0]) if rows else []
    return Table(columns=columns, rows=rows,
                 source_lines=list(range(2, 2 + len(rows))))


def config(spec: dict) -> ReportConfig:
    return ReportConfig.from_dict(spec)


BASE = {
    "columns": {
        "d": {"type": "date"},
        "amount": {"type": "number"},
        "qty": {"type": "number", "min": 1, "max": 100},
    },
    "sections": [{
        "name": "By month", "group_by": ["month(d)"],
        "aggregations": [{"column": "amount", "function": "sum", "label": "Total"}],
    }],
}


# ---------------------------------------------------------------------- quality


def test_a_readable_value_is_ok():
    dataset = inspect(table([{"d": "2026-01-05", "amount": "100,00", "qty": "2"}]), config(BASE))
    assert dataset.rows[0].cell("amount").verdict is Verdict.OK
    assert dataset.rows[0].status == "ok"


def test_an_unreadable_number_is_flagged_with_its_original_text():
    dataset = inspect(table([{"d": "2026-01-05", "amount": "do ustalenia", "qty": "2"}]), config(BASE))
    cell = dataset.rows[0].cell("amount")

    assert cell.verdict is Verdict.NOT_A_NUMBER
    assert cell.value is None, "an unreadable value must not carry a number"
    assert "do ustalenia" in cell.note


def test_a_value_above_the_maximum_is_flagged_but_keeps_its_value():
    dataset = inspect(table([{"d": "2026-01-05", "amount": "10", "qty": "9999"}]), config(BASE))
    cell = dataset.rows[0].cell("qty")

    assert cell.verdict is Verdict.OUT_OF_RANGE
    assert cell.value == Decimal("9999"), "the value is kept so a human can see it"
    assert not cell.usable


def test_an_empty_value_is_flagged():
    dataset = inspect(table([{"d": "", "amount": "10", "qty": "1"}]), config(BASE))
    assert dataset.rows[0].cell("d").verdict is Verdict.EMPTY


def test_a_configuration_naming_an_absent_column_stops_the_run():
    spec = dict(BASE, sections=[{
        "name": "S", "group_by": ["nope"],
        "aggregations": [{"column": "amount", "function": "sum", "label": "T"}],
    }])
    with pytest.raises(ValueError, match="does not have"):
        inspect(table([{"d": "2026-01-05", "amount": "1", "qty": "1"}]), config(spec))


def test_the_error_lists_the_columns_that_do_exist():
    spec = dict(BASE, sections=[{
        "name": "S", "group_by": ["nope"],
        "aggregations": [{"column": "amount", "function": "sum", "label": "T"}],
    }])
    with pytest.raises(ValueError, match="amount"):
        inspect(table([{"d": "x", "amount": "1", "qty": "1"}]), config(spec))


# ------------------------------------------------------------------ aggregation


def build(rows, spec=None):
    cfg = config(spec or BASE)
    dataset = inspect(table(rows), cfg)
    return build_section(dataset, cfg.sections[0], cfg), dataset


def test_rows_are_grouped_by_month():
    result, _ = build([
        {"d": "2026-01-05", "amount": "100", "qty": "1"},
        {"d": "2026-01-20", "amount": "50", "qty": "1"},
        {"d": "2026-02-02", "amount": "70", "qty": "1"},
    ])

    assert [row.keys[0] for row in result.rows] == ["2026-01", "2026-02"]
    assert result.rows[0].figures[0].value == Decimal("150")


def test_an_unusable_amount_is_excluded_and_counted_never_treated_as_zero():
    result, _ = build([
        {"d": "2026-01-05", "amount": "100", "qty": "1"},
        {"d": "2026-01-06", "amount": "do ustalenia", "qty": "1"},
    ])
    figure = result.rows[0].figures[0]

    assert figure.value == Decimal("100"), "the bad row must not add 0 to the total"
    assert figure.rows_used == 1
    assert figure.rows_excluded == 1
    assert not figure.complete


def test_a_row_with_no_usable_grouping_value_is_left_out_and_explained():
    result, _ = build([
        {"d": "2026-01-05", "amount": "100", "qty": "1"},
        {"d": "", "amount": "50", "qty": "1"},
    ])

    assert result.rows_without_key == 1
    assert any("d:" in note for note in result.key_notes)
    assert result.rows[0].figures[0].value == Decimal("100")


def test_a_group_with_no_usable_value_reports_none_not_zero():
    # The distinction matters: 0 is a measurement, None is an absence.
    result, _ = build([{"d": "2026-01-05", "amount": "do ustalenia", "qty": "1"}])
    figure = result.rows[0].figures[0]

    assert figure.value is None
    assert figure.rows_used == 0


def test_exclusion_is_per_figure_not_per_row():
    # The amount is unusable, but the row still has a usable quantity, so a
    # figure over quantity must still count it.
    spec = dict(BASE, sections=[{
        "name": "S", "group_by": ["month(d)"],
        "aggregations": [
            {"column": "amount", "function": "sum", "label": "Amount"},
            {"column": "qty", "function": "sum", "label": "Quantity"},
        ],
    }])
    result, _ = build([
        {"d": "2026-01-05", "amount": "do ustalenia", "qty": "4"},
        {"d": "2026-01-06", "amount": "100", "qty": "2"},
    ], spec)

    amount, quantity = result.rows[0].figures
    assert amount.value == Decimal("100") and amount.rows_excluded == 1
    assert quantity.value == Decimal("6") and quantity.rows_excluded == 0


@pytest.mark.parametrize(
    "function,expected",
    [("sum", Decimal("300")), ("mean", Decimal("150.00")),
     ("min", Decimal("100")), ("max", Decimal("200")), ("count", 2)],
)
def test_each_function(function, expected):
    spec = dict(BASE, sections=[{
        "name": "S", "group_by": ["month(d)"],
        "aggregations": [{"column": "amount", "function": function, "label": "F"}],
    }])
    result, _ = build([
        {"d": "2026-01-05", "amount": "100", "qty": "1"},
        {"d": "2026-01-06", "amount": "200", "qty": "1"},
    ], spec)

    assert result.rows[0].figures[0].value == expected


def test_count_distinct_counts_unique_values():
    spec = {
        "columns": {"d": {"type": "date"}},
        "sections": [{
            "name": "S", "group_by": ["month(d)"],
            "aggregations": [{"column": "who", "function": "count_distinct", "label": "People"}],
        }],
    }
    result, _ = build([
        {"d": "2026-01-05", "who": "A"},
        {"d": "2026-01-06", "who": "A"},
        {"d": "2026-01-07", "who": "B"},
    ], spec)

    assert result.rows[0].figures[0].value == 2


@pytest.mark.parametrize(
    "grouper,expected",
    [("year", "2026"), ("quarter", "2026-Q1"), ("month", "2026-02"), ("day", "2026-02-11")],
)
def test_date_groupers(grouper, expected):
    spec = dict(BASE, sections=[{
        "name": "S", "group_by": [f"{grouper}(d)"],
        "aggregations": [{"column": "amount", "function": "sum", "label": "T"}],
    }])
    result, _ = build([{"d": "2026-02-11", "amount": "10", "qty": "1"}], spec)

    assert result.rows[0].keys[0] == expected


def test_sorting_puts_the_largest_first_and_unknowns_last():
    spec = dict(BASE, sections=[{
        "name": "S", "group_by": ["month(d)"], "sort_by": "Total",
        "aggregations": [{"column": "amount", "function": "sum", "label": "Total"}],
    }])
    result, _ = build([
        {"d": "2026-01-05", "amount": "10", "qty": "1"},
        {"d": "2026-02-05", "amount": "90", "qty": "1"},
        {"d": "2026-03-05", "amount": "brak", "qty": "1"},
    ], spec)

    assert [row.keys[0] for row in result.rows] == ["2026-02", "2026-01", "2026-03"]
    assert result.rows[-1].figures[0].value is None


def test_top_keeps_only_the_first_groups():
    spec = dict(BASE, sections=[{
        "name": "S", "group_by": ["month(d)"], "sort_by": "Total", "top": 2,
        "aggregations": [{"column": "amount", "function": "sum", "label": "Total"}],
    }])
    result, _ = build([
        {"d": f"2026-0{month}-05", "amount": str(month * 10), "qty": "1"}
        for month in range(1, 5)
    ], spec)

    assert len(result.rows) == 2
    assert [row.keys[0] for row in result.rows] == ["2026-04", "2026-03"]


def test_two_grouping_keys_produce_a_compound_group():
    spec = dict(BASE, sections=[{
        "name": "S", "group_by": ["region", "channel"],
        "aggregations": [{"column": "amount", "function": "sum", "label": "T"}],
    }])
    result, _ = build([
        {"region": "A", "channel": "web", "amount": "10", "d": "2026-01-01", "qty": "1"},
        {"region": "A", "channel": "web", "amount": "5", "d": "2026-01-01", "qty": "1"},
        {"region": "A", "channel": "shop", "amount": "7", "d": "2026-01-01", "qty": "1"},
    ], spec)

    assert len(result.rows) == 2
    assert result.rows[0].keys == ["A", "shop"]
