from __future__ import annotations

from pathlib import PurePath

from ..config import Config
from .aeon import AeonParser
from .aeon_credit import AeonCreditParser
from .base import ParseError, PasswordNeeded, Parser
from .gx import GxParser
from .maybank_cc import MaybankCardParser
from .maybank_sa import MaybankSavingsParser
from .ryt import RytParser
from .splitwise import SplitwiseParser
from .tng import TngParser

# Add new statement formats here.
BUILTIN_PARSERS: list[type[Parser]] = [
    AeonParser, AeonCreditParser, GxParser, MaybankCardParser, MaybankSavingsParser, RytParser, SplitwiseParser, TngParser,
]


def build_parsers(config: Config) -> list[Parser]:
    return [p(config) for p in BUILTIN_PARSERS]


def find_parser(name: str, data: bytes, parsers: list[Parser]) -> Parser | None:
    path = PurePath(name)
    return next(
        (p for p in parsers if p.matches(path) and p.sniff(name, data, p.config.password(p.name))),
        None,
    )


__all__ = ["ParseError", "PasswordNeeded", "Parser", "build_parsers", "find_parser"]
