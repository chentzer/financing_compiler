from __future__ import annotations

import io
from fnmatch import fnmatch
from pathlib import Path, PurePath

from pypdf import PdfReader

from ..config import Config
from ..models import Transaction


class ParseError(Exception):
    pass


class PasswordNeeded(ParseError):
    """The PDF is encrypted and no password (or a wrong one) was given. The
    app catches this to ask for the bank's password."""

    def __init__(self, file: str, parser: str):
        super().__init__(f"{file}: needs the statement password (passwords.{parser})")
        self.file = file
        self.parser = parser


def open_pdf(name: str, data: bytes, password: str, parser: str) -> PdfReader:
    """Open a statement from bytes. Many banks encrypt with an empty
    password, so that's tried before the saved one."""
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted and not reader.decrypt(""):
        if not password or not reader.decrypt(password):
            raise PasswordNeeded(name, parser)
    return reader


def pdf_text(reader: PdfReader) -> str:
    return "\n".join(page.extract_text() or "" for page in reader.pages)


class Parser:
    """A statement format. Subclasses set `name`, `default_patterns`, and
    implement `parse_bytes`. Everything works from bytes so the same code
    runs on the command line and in the browser."""

    name: str = ""
    label: str = ""  # shown in the Source column
    default_patterns: list[str] = []

    def __init__(self, config: Config):
        self.config = config

    @property
    def patterns(self) -> list[str]:
        return self.config.patterns.get(self.name, self.default_patterns)

    def matches(self, path: PurePath) -> bool:
        name = path.name.lower()
        return any(fnmatch(name, p.lower()) for p in self.patterns)

    def sniff(self, name: str, data: bytes, password: str = "") -> bool:
        """Second check after the file name, for names other banks use too.
        Override to peek at the content."""
        return True

    def parse_bytes(self, name: str, data: bytes, password: str = "") -> list[Transaction]:
        raise NotImplementedError

    def parse(self, path: Path) -> list[Transaction]:
        return self.parse_bytes(path.name, path.read_bytes(), self.config.password(self.name))


class TextPdfParser(Parser):
    """A PDF statement read from its text layer. `marker` is text only this
    bank's statements contain, used to tell same-named files apart."""

    marker: str = ""

    def text(self, name: str, data: bytes, password: str) -> str:
        return pdf_text(open_pdf(name, data, password, self.name))

    def sniff(self, name: str, data: bytes, password: str = "") -> bool:
        if not self.marker:
            return True
        try:
            return self.marker.upper() in self.text(name, data, password).upper()
        except PasswordNeeded:
            return True  # let parse_bytes report it
        except Exception:
            return False
