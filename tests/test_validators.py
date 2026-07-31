# SPDX-License-Identifier: MPL-2.0
"""
Fiscal-id validation is the one piece of extension logic that silently produces
a rejected API call when it is wrong, so it gets real coverage.

These assertions are ported one-for-one from signdocs-onlyoffice's
tests/validators.test.js, which in turn guards a port of the Nextcloud app's
CpfCnpjValidator. Keep the three in lockstep: if a case is added here, add it
there too, or the channels start disagreeing about which documents they accept.
"""

from signdocs import validators as v


def test_accepts_cpfs_with_correct_check_digits():
    assert v.is_valid_cpf("52998224725") is True
    assert v.is_valid_cpf("12345678909") is True
    # Formatting is stripped before the arithmetic.
    assert v.is_valid_cpf("529.982.247-25") is True


def test_rejects_cpfs_with_bad_check_digits_or_wrong_length():
    assert v.is_valid_cpf("52998224726") is False
    assert v.is_valid_cpf("5299822472") is False
    assert v.is_valid_cpf("") is False


def test_rejects_all_same_digit_cpfs_that_pass_the_modulo_arithmetic():
    # Receita blacklists these; the checksum alone would let them through.
    assert v.is_valid_cpf("00000000000") is False
    assert v.is_valid_cpf("11111111111") is False
    assert v.is_valid_cpf("99999999999") is False


def test_accepts_cnpjs_with_correct_check_digits():
    assert v.is_valid_cnpj("11222333000181") is True
    assert v.is_valid_cnpj("11144477000167") is True
    assert v.is_valid_cnpj("11.222.333/0001-81") is True


def test_rejects_cnpjs_with_bad_check_digits_or_wrong_length():
    assert v.is_valid_cnpj("11222333000182") is False
    assert v.is_valid_cnpj("1122233300018") is False
    assert v.is_valid_cnpj("00000000000000") is False


def test_classify_picks_kind_by_length_and_never_guesses():
    cpf = v.classify("529.982.247-25")
    assert cpf.kind == "cpf"
    assert cpf.digits == "52998224725"
    assert cpf.valid is True

    cnpj = v.classify("11.222.333/0001-81")
    assert cnpj.kind == "cnpj"
    assert cnpj.valid is True

    # A 12-digit value is neither; it must not be coerced into either field,
    # or an 11-digit CPF could go out on the wire as a CNPJ.
    neither = v.classify("112223330001")
    assert neither.kind is None
    assert neither.valid is False


def test_classify_reports_a_well_formed_but_invalid_id_as_its_own_kind():
    bad = v.classify("52998224726")
    assert bad.kind == "cpf"
    assert bad.valid is False


def test_format_cpf_cnpj_punctuates_for_the_review_step():
    assert v.format_cpf_cnpj("52998224725") == "529.982.247-25"
    assert v.format_cpf_cnpj("11222333000181") == "11.222.333/0001-81"
    # Already-punctuated input round-trips rather than doubling separators.
    assert v.format_cpf_cnpj("529.982.247-25") == "529.982.247-25"
    # Anything that is neither length is passed through, not mangled.
    assert v.format_cpf_cnpj("12345") == "12345"
    assert v.format_cpf_cnpj("") == ""
    assert v.format_cpf_cnpj(None) == ""


def test_email_check_accepts_ordinary_addresses_and_rejects_malformed_ones():
    assert v.is_valid_email("contato@signdocs.com.br") is True
    assert v.is_valid_email(" contato@signdocs.com.br ") is True
    assert v.is_valid_email("contato@signdocs") is False
    assert v.is_valid_email("sem-arroba.com.br") is False
    assert v.is_valid_email("") is False


def test_email_check_trims_surrounding_whitespace_like_the_js_validator():
    # JS trim() and Python strip() both remove newlines, so these are valid in
    # every channel. Rejecting them here would be the divergence, not the fix.
    assert v.is_valid_email("contato@signdocs.com.br\n") is True
    assert v.is_valid_email("\tcontato@signdocs.com.br\r\n") is True


def test_email_check_rejects_an_interior_newline():
    # The anchoring case that actually matters: two addresses smuggled into one
    # field must not validate on the strength of the first line.
    assert v.is_valid_email("contato@signdocs.com.br\nx@y.zz") is False
    assert v.is_valid_email("a@b.cc\nBcc: victim@example.com") is False
