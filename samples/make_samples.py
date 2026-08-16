"""
Generate the sample data.

Everything here is invented: the customers, the sales representatives, the
regions, the product names, the dates and the amounts refer to no real business
or person.

The file is deliberately imperfect. Roughly one row in twelve carries a defect
the report has to handle without inventing anything: an unreadable amount, an
empty date, a quantity outside its allowed range, a date written in a different
format. The point of the sample is to show what the tool does with bad data, not
to show a clean run.

Run from the project root:

    python samples/make_samples.py
"""
import csv
import random
from datetime import date, timedelta
from pathlib import Path

SAMPLES = Path(__file__).parent

REGIONS = ["Mazowieckie", "Małopolskie", "Śląskie", "Pomorskie", "Dolnośląskie"]
CHANNELS = ["online", "sklep", "telefon"]
PRODUCTS = [
    ("Pakiet startowy", 450),
    ("Pakiet rozszerzony", 1200),
    ("Wdrożenie", 2500),
    ("Szkolenie", 800),
    ("Wsparcie miesięczne", 249),
]
REPS = ["A. Nowak", "B. Kowalska", "C. Zieliński", "D. Wiśniewska"]
CUSTOMERS = [f"Klient testowy {index:02d}" for index in range(1, 23)]

HEADER = [
    "order_id", "order_date", "region", "channel", "sales_rep",
    "customer", "product", "quantity", "unit_price", "net_amount",
]


def polish_amount(value: float) -> str:
    return f"{value:,.2f}".replace(",", " ").replace(".", ",")


def build_rows(seed: int = 20260816) -> list[list[str]]:
    """Build the rows, with deliberate defects at fixed positions."""
    generator = random.Random(seed)
    start = date(2026, 1, 5)
    rows: list[list[str]] = []

    for index in range(1, 125):
        day = start + timedelta(days=generator.randint(0, 210))
        product, unit_price = generator.choice(PRODUCTS)
        quantity = generator.randint(1, 8)
        net = quantity * unit_price

        order_date = day.isoformat()
        quantity_text = str(quantity)
        net_text = polish_amount(net)
        unit_text = polish_amount(unit_price)

        # --- deliberate defects, at fixed positions so tests can rely on them ---
        if index % 17 == 0:
            # An amount a person typed as a note instead of a number.
            net_text = "do ustalenia"
        elif index % 23 == 0:
            # A missing date: the row cannot belong to any month.
            order_date = ""
        elif index % 29 == 0:
            # A quantity outside the plausible range declared in the config.
            quantity_text = "9999"
        elif index % 13 == 0:
            # The same date in another format; readable, and must not be dropped.
            order_date = day.strftime("%d.%m.%Y")

        rows.append([
            f"ZAM-{index:04d}", order_date, generator.choice(REGIONS),
            generator.choice(CHANNELS), generator.choice(REPS),
            generator.choice(CUSTOMERS), product,
            quantity_text, unit_text, net_text,
        ])
    return rows


def write_csv(rows: list[list[str]]) -> Path:
    path = SAMPLES / "sample_sales.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(HEADER)
        writer.writerows(rows)
    return path


def write_xlsx(rows: list[list[str]]) -> Path:
    from openpyxl import Workbook

    path = SAMPLES / "sample_sales.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "sprzedaz"
    sheet.append(HEADER)
    for row in rows:
        sheet.append(row)
    workbook.save(path)
    return path


if __name__ == "__main__":
    rows = build_rows()
    print("wrote", write_csv(rows))
    print("wrote", write_xlsx(rows))
    defects = sum(
        1 for row in rows
        if row[1] == "" or row[9] == "do ustalenia" or row[7] == "9999"
    )
    print(f"{len(rows)} rows, {defects} carrying a deliberate defect")
