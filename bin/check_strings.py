# SPDX-License-Identifier: MPL-2.0
"""
Every user-visible string must live in `strings.py`, keyed by locale.

The ONLYOFFICE plugin hardcodes all of its text in pt-BR and has no string
table at all. That is defensible for a plugin shipped from our own site to a
Brazilian audience; it is not for a listing on extensions.libreoffice.org,
where the default visitor is not Brazilian. This repo externalised from day
one, and the only thing that keeps it that way is a gate — the natural thing
to write when adding a message box is the literal.

Uses `ast` rather than grep so comments and docstrings are exempt for free,
and detects by diacritic: Portuguese and Spanish UI text is full of them,
while identifiers, format specifiers and UNO service names are pure ASCII.
That leaves unaccented literals ("Enviar", "Cancelar") undetected, which is
the accepted limit — it catches the common case without false positives.

Run by bin/lint.sh; exits non-zero with file:line on the first offence.
"""

import ast
import os
import sys

ACCENTS = set("áàâãéêíóôõúüçÁÀÂÃÉÊÍÓÔÕÚÜÇñÑ¿¡")
ROOT = os.path.join("pythonpath", "signdocs", "ui")
EXEMPT = {"strings.py"}


def _docstring_ids(tree):
    """Nodes that are docstrings, which may say whatever they like."""
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if (isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                found.add(id(first.value))
    return found


def offences(root=ROOT):
    out = []
    for base, _, files in os.walk(root):
        for name in sorted(files):
            if not name.endswith(".py") or name in EXEMPT:
                continue
            path = os.path.join(base, name)
            with open(path, encoding="utf-8") as handle:
                tree = ast.parse(handle.read(), path)
            skip = _docstring_ids(tree)
            for node in ast.walk(tree):
                if (isinstance(node, ast.Constant)
                        and isinstance(node.value, str)
                        and id(node) not in skip
                        and ACCENTS & set(node.value)):
                    out.append((path, node.lineno, node.value))
    return out


def main():
    found = offences()
    if found:
        print("  user-visible text outside strings.py:")
        for path, line, value in found:
            print("    %s:%d  %r" % (path, line, value))
        return 1
    print("  ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
