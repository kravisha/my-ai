"""One-off script to generate the mock demo portfolio at data/portfolio.xlsx."""

from datetime import date
from pathlib import Path

from openpyxl import Workbook

ACCOUNT_ID = "ACCT-88421"

ROWS = [
    ("AAPL", 25, 172.34, date(2023, 3, 14)),
    ("MSFT", 15, 310.12, date(2023, 6, 2)),
    ("NVDA", 10, 421.55, date(2024, 1, 18)),
    ("VTI", 40, 215.67, date(2022, 11, 9)),
    ("KO", 60, 58.90, date(2021, 8, 30)),
]


def main() -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Holdings"
    ws.append(["Ticker", "Shares", "Purchase Price", "Purchase Date", "Account ID"])
    for ticker, shares, price, purchased in ROWS:
        ws.append([ticker, shares, price, purchased.isoformat(), ACCOUNT_ID])

    out_path = Path(__file__).resolve().parent.parent / "data" / "portfolio.xlsx"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
