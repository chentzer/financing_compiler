"""Touch 'n Go eWallet statements.

TNG has shipped two PDF layouts, told apart by the PDF producer:

- v1 (iText): 8 columns with Date, Status, Type, Reference, Description,
  Details, Amount, Wallet Balance. Amounts are unsigned, so the direction
  comes from the transaction type.
- v2 (dompdf and others): 4 columns with Details, Type, Reference No.,
  Amount. Amounts carry their sign.

v1 is read from text positions with pypdf (works in a browser); v2 still
uses camelot. Column positions come from the original
Rexpert/TNG_Statement_in_CSV project (MIT) via the friend's fork.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from pypdf import PdfReader

from ..models import Transaction
from .base import ParseError, Parser, open_pdf

SOURCE = "TNG eWallet"
WALLET = "eWallet"
GOPLUS = "GO+"

V1_COLUMNS = ["Date", "Status", "Type", "Reference", "Description", "Details", "Amount", "Balance"]
V2_COLUMNS = ["Details", "Type", "Reference", "Amount"]

# v1 types that take money out of the wallet; anything else is money in.
# Compared with spaces removed and upper-cased, because camelot sometimes
# splits words ("DUITNOW_TRANS FERTO").
WALLET_OUT_TYPES = {
    "PAYMENT",
    "TRANSFERTOWALLET",
    "RFIDPAYMENT",
    "DUITNOWQRTNGD",
    "DUITNOWQR",
    "EWALLETCASHOUT",
    "DUITNOW_TRANSFERTO",
    "TRANSIT_PASS",
}
# DuitNow to/from a bank account: the Description is the other person.
DUITNOW_TYPES = {"DUITNOW_TRANSFERTO", "DUITNOW_RECEIVEFROM"}
URL_RE = re.compile(r"\s*-?\s*https?://.*$", re.IGNORECASE)


def _norm(value: str) -> str:
    return re.sub(r"\s+", "", str(value)).upper()


def _money(value: str) -> float | None:
    cleaned = re.sub(r"[^\d.\-]", "", str(value))
    if cleaned in ("", "-", ".", "-."):
        return None
    return float(cleaned)


def _clean_description(text: str) -> str:
    # Merchant names carry long numeric suffixes like "_123456789", and app
    # purchases a store link and a numeric merchant code:
    # "281498 - BrownDust2 - https://play.google.com/..." -> "BrownDust2".
    text = re.sub(r"_\d{5,}", "", re.sub(r"\s{2,}", " ", text))
    text = URL_RE.sub("", text)
    text = re.sub(r"^\d{4,}\s*-\s*", "", text)
    return text.strip(" -")


def _monthly_earnings(transactions: list[Transaction]) -> list[Transaction]:
    """GO+ pays interest daily in fractions of a sen; one row per month."""
    daily = [t for t in transactions if t.type.upper().startswith("GO+") and "EARN" in _norm(t.type)]
    daily_ids = {id(t) for t in daily}
    rest = [t for t in transactions if id(t) not in daily_ids]
    months: dict[tuple[int, int], list[Transaction]] = {}
    for t in daily:
        months.setdefault((t.date.year, t.date.month), []).append(t)
    for group in months.values():
        total = round(sum(t.amount for t in group), 2)
        if total:
            rest.append(Transaction(
                date=max(t.date for t in group), source=SOURCE, account=GOPLUS,
                description="GO+ Daily Earnings", amount=total, type="GO+ Daily Earnings",
                purpose="GO+ earnings", note=f"{len(group)} daily payouts", file=group[0].file,
            ))
    return sorted(rest, key=lambda t: t.date)


def parse_v1_tables(frames: list[pd.DataFrame], file: str = "", holder: str = "") -> list[Transaction]:
    """camelot DataFrames (one line per frame row) -> transactions."""
    import pandas as pd

    holder = holder.strip().lower()
    df = pd.concat(frames, ignore_index=True).fillna("").astype(str)
    df.columns = V1_COLUMNS

    # Keep transaction rows and their wrapped continuation lines (empty Date).
    df = df[df["Date"].str.match(r"^\d|^$") & (df["Reference"].str.strip() != "")]

    # Fold continuation lines into the row above.
    groups: list[dict[str, list[str]]] = []
    for _, row in df.iterrows():
        if row["Date"].strip() or not groups:
            groups.append({c: [] for c in V1_COLUMNS})
        for c in V1_COLUMNS:
            if row[c].strip():
                groups[-1][c].append(row[c].strip())

    rows = [{c: " ".join(v) for c, v in g.items()} for g in groups]
    return parse_v1_rows(rows, file=file, holder=holder)


def parse_v1_rows(rows: list[dict[str, str]], file: str = "", holder: str = "") -> list[Transaction]:
    """The v1 rules, on one dict per transaction keyed by V1_COLUMNS."""
    holder = holder.strip().lower()
    transactions = []
    for row in rows:
        try:
            when = datetime.strptime(row["Date"], "%d/%m/%Y").date()
        except ValueError:
            continue
        amount = _money(row["Amount"].replace("-", ""))
        if amount is None:
            continue

        tx_type = row["Type"]
        kind = _norm(tx_type)
        description = _clean_description(row["Description"])
        status = row["Status"]
        transfer = False
        counterparty = purpose = ""
        if kind.startswith("GO+"):
            # Moves between the wallet and the GO+ pot, seen from the GO+ side.
            earning = "EARN" in kind
            signed = -amount if "CASHOUT" in kind else amount
            account, internal = GOPLUS, not earning
        else:
            signed = -amount if kind in WALLET_OUT_TYPES else amount
            account = WALLET
            # Wallet-side mirror of a GO+ move.
            internal = "GO+" in description.upper()
            if kind == "RELOAD":
                # Topped up from GO+, a card or a bank: your own money. Only
                # a card/bank reload has a partner in another statement.
                internal = True
                transfer = "GO+" not in description.upper()
            elif kind in DUITNOW_TYPES or kind == "RECEIVEFROMWALLET":
                to_self = bool(holder) and description.lower() == holder
                internal, transfer = internal or to_self, to_self
                counterparty = description
            elif kind == "TRANSFERTOWALLET":
                # Only your note is shown ("lunch"), not who it went to.
                purpose = description
            if not description:
                description = tx_type.replace("_", " ").title()  # e.g. TRANSIT_PASS
        if status.lower() not in ("", "success"):
            internal = True  # failed or reversed: no money moved

        transactions.append(
            Transaction(
                date=when,
                source=SOURCE,
                account=account,
                description=description,
                amount=signed,
                type=tx_type,
                reference=row["Reference"],
                internal=internal,
                transfer=transfer,
                counterparty=counterparty,
                purpose=purpose,
                note="" if status.lower() in ("", "success") else status,
                file=file,
            )
        )
    return _monthly_earnings(transactions)


def parse_v2_tables(frames: list[pd.DataFrame], file: str = "") -> list[Transaction]:
    import pandas as pd

    parts = []
    for frame in frames:
        frame = frame.iloc[:-2].copy()  # page footer
        frame.columns = V2_COLUMNS
        header = frame["Details"].eq("Details")
        if header.any():
            frame = frame.loc[frame.index > header.idxmax()]
        parts.append(frame)
    df = pd.concat(parts, ignore_index=True).fillna("").astype(str)

    df["When"] = pd.to_datetime(df["Details"], format="%d/%m/%Y %H:%M", errors="coerce")
    df.loc[df["When"].notna(), "Details"] = ""
    # In this layout the date line closes each transaction block, so a row
    # belongs to the group of the next date line at or below it.
    df["group"] = df["When"].notna().cumsum().shift(fill_value=0)

    rows = []
    for _, g in df.groupby("group", sort=True):
        when = g["When"].dropna()
        amount = _money(" ".join(g["Amount"]).replace("RM", ""))
        if when.empty or amount is None:
            continue
        rows.append(
            {
                "date": when.iloc[0].date(),
                "type": " ".join(s for s in g["Type"] if s.strip()).strip(),
                "details": " ".join(s for s in g["Details"] if s.strip()).strip(),
                "reference": " ".join(s for s in g["Reference"] if s.strip()).strip(),
                "amount": amount,
            }
        )

    transactions = [
        Transaction(
            date=r["date"],
            source=SOURCE,
            account=WALLET,
            description=_clean_description(r["details"]),
            amount=r["amount"],
            type=r["type"],
            reference=r["reference"],
            # Auto-reload top-ups mirror a payment that is listed separately.
            internal=r["details"] == "Quick Reload Payment",
            file=file,
        )
        for r in rows
    ]

    # "GO+ Quick Cash In" followed by a matching "eWallet Cash Out" is money
    # pulled from GO+ to pay for something; the pair nets to zero.
    for a, b in zip(transactions, transactions[1:]):
        if (
            a.description == "GO+ Quick Cash In"
            and b.description == "eWallet Cash Out"
            and round(a.amount, 2) == round(-b.amount, 2)
        ):
            a.internal = b.internal = True
    return transactions


# v1 column boundaries on the landscape page (left edge of each column),
# the same positions the original camelot setup used.
V1_COLUMN_STARTS = [0, 80, 140, 230, 294, 460, 660, 720]


def _text_items(page) -> list[tuple[float, float, str]]:
    """(row position, column position, text) for each text run. TNG pages
    are rotated, so the column runs along the PDF's y axis."""
    items = []

    def visit(text, cm, tm, font, size):
        if text.strip():
            x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
            y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
            items.append((x, y, text))

    page.extract_text(visitor_text=visit)
    rotated = int(page.get("/Rotate", 0) or 0) % 180 == 90
    return [(x, y, t) if rotated else (-y, x, t) for x, y, t in items]


def read_v1_rows(reader: PdfReader) -> list[dict[str, str]]:
    """Rebuild the 8-column v1 table from text positions (no camelot, so it
    also runs in a browser). Anything in the Date column (a date, a section
    title, the header, the footer) starts a new row; only rows starting with
    a date are kept. Wrapped lines inside a cell are joined with spaces."""
    rows: list[dict[str, list[str]]] = []
    for page in reader.pages:
        items = sorted(_text_items(page))
        current: dict[str, list[str]] | None = None
        for _row_pos, col_pos, text in items:
            col = max(i for i, start in enumerate(V1_COLUMN_STARTS) if col_pos >= start - 2)
            name = V1_COLUMNS[col]
            if name == "Date":
                current = None
                if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", text.strip()):
                    current = {c: [] for c in V1_COLUMNS}
                    rows.append(current)
            if current is not None:
                current[name].append(text.strip())
    return [{c: " ".join(v) for c, v in r.items()} for r in rows]


def holder_name(reader: PdfReader) -> str:
    """Registered name: the line above the 16-digit Wallet ID."""
    try:
        lines = [l.strip() for l in (reader.pages[0].extract_text() or "").splitlines()]
    except Exception:
        return ""
    return next((lines[i - 1] for i, l in enumerate(lines) if i and re.fullmatch(r"\d{16}", l)), "")


def detect_version(reader: PdfReader) -> int:
    try:
        producer = str((reader.metadata or {}).get("/Producer", "") or "").lower()
    except Exception:
        producer = ""
    if any(p in producer for p in ("dompdf", "tcpdf", "wkhtmltopdf")):
        return 2
    return 1  # iText, and the fallback for unknown producers


class TngParser(Parser):
    name = "tng"
    label = SOURCE
    default_patterns = ["*transactions*.pdf", "tng*.pdf"]

    def parse_bytes(self, name: str, data: bytes, password: str = "") -> list[Transaction]:
        reader = open_pdf(name, data, password, self.name)
        if detect_version(reader) == 1:
            return parse_v1_rows(read_v1_rows(reader), file=name, holder=holder_name(reader))
        return self._parse_v2_with_camelot(name, data, password)

    def _parse_v2_with_camelot(self, name: str, data: bytes, password: str) -> list[Transaction]:
        """The older 4-column layout still needs camelot (CLI only)."""
        try:
            import camelot
        except ImportError as e:
            raise ParseError(f'{name}: this older TNG layout needs camelot: pip install -e ".[tng]"') from e
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "statement.pdf"
            path.write_bytes(data)
            kwargs = {"password": password} if password else {}
            try:
                tables = camelot.read_pdf(
                    str(path), pages="all", flavor="stream", table_regions=["40,710,560,0"],
                    table_areas=["40,710,560,0"], columns=["170,295,423"], split_text=True,
                    strip_text="\n", **kwargs,
                )
            except Exception as e:
                raise ParseError(f"{name}: camelot could not read it ({e}). Check passwords.tng") from e
        if not tables:
            raise ParseError(f"{name}: no transaction table found")
        return parse_v2_tables([t.df for t in tables], file=name)
