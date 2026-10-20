from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import date


@dataclass
class Transaction:
    """One line of any statement, in the shape every parser must produce.

    amount: positive = money in, negative = money out.
    internal: True when the money only moved between the user's own accounts
    (wallet <-> savings pot, card reload of a wallet). Internal rows are kept
    in the ledger but left out of income/spending totals.
    transfer: the parser knows this row is one side of a transfer (e.g. a
    card repayment), so it is internal but can still be paired with the other
    side in another account.
    """

    date: date
    source: str
    account: str
    description: str
    amount: float
    type: str = ""
    reference: str = ""
    internal: bool = False
    transfer: bool = False
    # Who the money went to, and what for, when the statement says so
    # (e.g. a DuitNow reference like "lunch"). Empty purpose = unclear.
    counterparty: str = ""
    purpose: str = ""
    note: str = ""
    category: str = ""  # when the source says (e.g. Splitwise's "Dining out" -> Food)
    file: str = field(default="", compare=False)

    @classmethod
    def columns(cls) -> list[str]:
        return [f.name for f in fields(cls)]
