import csv
from pathlib import Path
from openpyxl import Workbook

CSV_PATH = Path("consum_modelo_comun.csv")
XLSX_PATH = Path("consum_modelo_comun.xlsx")


def main() -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Consum_ModeloComun"
    with CSV_PATH.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.reader(f, delimiter=";"):
            ws.append(row)
    ws.freeze_panes = "A2"
    wb.save(XLSX_PATH)
    print(f"creado={XLSX_PATH}")


if __name__ == "__main__":
    main()
