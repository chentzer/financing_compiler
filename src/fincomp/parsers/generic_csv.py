"""Any bank or wallet that exports CSV/XLSX, described by a [[csv]] block in
config.toml (see config.example.toml)."""

from __future__ import annotations

import io
import re
from fnmatch import fnmatch
from pathlib import PurePath

from ..config import Config
from ..models import Transaction
from .base import ParseError, Parser


def _to_amount(series: pd.Series) -> pd.Series:
    import pandas as pd  # CLI only: not needed to run the PDF parsers in a browser

    text = series.fillna("").astype(str).str.strip()
    # "(12.30)" is accounting notation for -12.30.
    negative = text.str.match(r"^\(.*\)$") | text.str.startswith("-") | text.str.endswith("-")
    numbers = pd.to_numeric(text.str.replace(r"[^\d.]", "", regex=True), errors="coerce").fillna(0.0)
    return numbers.where(~negative, -numbers)


class CsvParser(Parser):
    def __init__(self, config: Config, spec: dict):
        super().__init__(config)
        self.spec = spec
        self.label = spec.get("name") or "CSV"
        self.name = "csv:" + re.sub(r"\W+", "_", self.label.lower())

    def matches(self, path: PurePath) -> bool:
        name = path.name.lower()
        return any(fnmatch(name, p.lower()) for p in self.spec.get("patterns", []))

    def _col(self, df: pd.DataFrame, key: str, required: bool = True) -> str | None:
        col = self.spec.get(key) or None
        if col is None:
            if required:
                raise ParseError(f"[[csv]] {self.label}: missing {key}")
            return None
        if col not in df.columns:
            raise ParseError(
                f"[[csv]] {self.label}: column {col!r} ({key}) not found; file has {list(df.columns)}"
            )
        return col

    def parse_bytes(self, name: str, data: bytes, password: str = "") -> list[Transaction]:
        import pandas as pd

        skip = int(self.spec.get("skip_rows", 0))
        if PurePath(name).suffix.lower() in (".xlsx", ".xls"):
            df = pd.read_excel(io.BytesIO(data), skiprows=skip, dtype=str)
        else:
            df = pd.read_csv(io.BytesIO(data), skiprows=skip, dtype=str, encoding="utf-8-sig")
        df.columns = [str(c).strip() for c in df.columns]

        date_col = self._col(df, "date_column")
        desc_col = self._col(df, "description_column")
        amount_col = self._col(df, "amount_column", required=False)
        debit_col = self._col(df, "debit_column", required=False)
        credit_col = self._col(df, "credit_column", required=False)
        type_col = self._col(df, "type_column", required=False)
        ref_col = self._col(df, "reference_column", required=False)

        if amount_col:
            amounts = _to_amount(df[amount_col])
        elif debit_col or credit_col:
            debit = _to_amount(df[debit_col]).abs() if debit_col else 0.0
            credit = _to_amount(df[credit_col]).abs() if credit_col else 0.0
            amounts = credit - debit
        else:
            raise ParseError(f"[[csv]] {self.label}: set amount_column or debit_column/credit_column")
        if self.spec.get("invert_sign"):
            amounts = -amounts

        fmt = self.spec.get("date_format") or None
        dates = pd.to_datetime(df[date_col], format=fmt, errors="coerce", dayfirst=fmt is None)

        # Not the file name: monthly exports of one account must share it, or
        # overlapping files can't be deduplicated.
        account = self.spec.get("account") or self.label
        transactions = []
        for i in df.index:
            if pd.isna(dates[i]) or amounts[i] == 0:
                continue  # blank, subtotal, or opening-balance lines
            transactions.append(
                Transaction(
                    date=dates[i].date(),
                    source=self.label,
                    account=account,
                    description=str(df.at[i, desc_col] or "").strip(),
                    amount=round(float(amounts[i]), 2),
                    type=str(df.at[i, type_col]).strip() if type_col else "",
                    reference=str(df.at[i, ref_col]).strip() if ref_col else "",
                    file=name,
                )
            )
        return transactions
