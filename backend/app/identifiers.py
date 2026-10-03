"""Safe Oracle identifier handling. Identifiers cannot be bind variables, so they are
validated against a strict pattern and double-quoted. Names that come from Oracle
metadata are used verbatim (case preserved); user-supplied names are upper-cased."""
import re

_IDENT = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]{0,127}$")


def ident(name: str) -> str:
    if not isinstance(name, str) or not _IDENT.match(name):
        raise ValueError(f"unsafe identifier: {name!r}")
    return name


def quote(name: str) -> str:
    return '"' + ident(name) + '"'
