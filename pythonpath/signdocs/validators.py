# SPDX-License-Identifier: MPL-2.0
"""
Brazilian fiscal-id validators.

Third implementation of these rules, and they must all agree: the Nextcloud
app's lib/Service/CpfCnpjValidator.php came first, signdocs-onlyoffice's
scripts/validators.js is a port of it, and this is a port of that. If one of
them drifts, the same document is accepted by one channel and rejected by
another for reasons the user cannot see. The test suite carries the same
assertions as the JS one, deliberately.

Validating locally means an invalid CPF surfaces in the dialog instead of
coming back as an opaque 4xx from the API.
"""

import re
from collections import namedtuple

#: What `classify` returns. `kind` is None when the input is neither length.
Classification = namedtuple("Classification", "kind digits valid")

# JS uses /^...$/ without the m flag, which anchors to the end of the string.
# Python's `$` would also match just before a trailing newline. The strip()
# below hides that today, so \Z is defence in depth: if the trim is ever
# dropped, `$` would silently start accepting "a@b.cc\n" and this validator
# would disagree with the JS and PHP ones for reasons nobody would find.
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}\Z")
_NON_DIGIT_RE = re.compile(r"\D")
_ALL_SAME_RE = re.compile(r"^(\d)\1*\Z")


def only_digits(value):
    if value is None:
        return ""
    return _NON_DIGIT_RE.sub("", str(value))


def _all_same_digit(digits):
    return bool(_ALL_SAME_RE.match(digits))


def _check_digit_descending(part, start_weight):
    """CPF: weights are a strict-decreasing run from start_weight down to 2."""
    total = sum(int(d) * (start_weight - i) for i, d in enumerate(part))
    remainder = total % 11
    return 0 if remainder < 2 else 11 - remainder


def _check_digit_weighted(part, weights):
    """CNPJ: weights are an explicit cyclic schedule."""
    total = sum(int(d) * w for d, w in zip(part, weights))
    remainder = total % 11
    return 0 if remainder < 2 else 11 - remainder


def is_valid_cpf(value):
    digits = only_digits(value)
    if len(digits) != 11 or _all_same_digit(digits):
        return False
    if _check_digit_descending(digits[:9], 10) != int(digits[9]):
        return False
    return _check_digit_descending(digits[:10], 11) == int(digits[10])


def is_valid_cnpj(value):
    digits = only_digits(value)
    if len(digits) != 14 or _all_same_digit(digits):
        return False
    w1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    w2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    if _check_digit_weighted(digits[:12], w1) != int(digits[12]):
        return False
    return _check_digit_weighted(digits[:13], w2) == int(digits[13])


def classify(value):
    """
    Classify a typed fiscal id by length, then validate.

    Returning the kind explicitly is what keeps an 11-digit value from ever
    being sent as a CNPJ. The API takes `cpf` OR `cnpj`, never both, and never
    infers — so neither does this.
    """
    digits = only_digits(value)
    if len(digits) == 11:
        return Classification("cpf", digits, is_valid_cpf(digits))
    if len(digits) == 14:
        return Classification("cnpj", digits, is_valid_cnpj(digits))
    return Classification(None, digits, False)


def is_valid_email(value):
    return bool(_EMAIL_RE.match("" if value is None else str(value).strip()))


def format_cpf_cnpj(digits):
    """
    Punctuate a fiscal id for the review dialog — CPF as 123.456.789-00, CNPJ
    as 12.345.678/0001-00. Anything that is neither length passes through
    untouched rather than being mangled.
    """
    d = only_digits(digits)
    if len(d) == 11:
        return "{0}.{1}.{2}-{3}".format(d[0:3], d[3:6], d[6:9], d[9:])
    if len(d) == 14:
        return "{0}.{1}.{2}/{3}-{4}".format(d[0:2], d[2:5], d[5:8], d[8:12], d[12:])
    return d
