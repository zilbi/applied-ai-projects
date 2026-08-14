from __future__ import annotations

import re


def digits(value: object | None) -> str | None:
    if value is None:
        return None
    # pandas turns integer requisites into floats when a column has blanks;
    # preserve a trailing ".0" as a numeric formatting artefact, not a digit.
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    if re.fullmatch(r"\d+\.0+", text):
        text = text.split(".", 1)[0]
    result = re.sub(r"\D", "", text)
    return result or None


def valid_inn(value: object | None) -> bool:
    inn = digits(value)
    if not inn or len(inn) not in (10, 12) or len(set(inn)) == 1:
        return False
    factors = (2, 4, 10, 3, 5, 9, 4, 6, 8) if len(inn) == 10 else (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
    check = lambda source, weights: sum(int(x) * y for x, y in zip(source, weights)) % 11 % 10
    if len(inn) == 10:
        return check(inn[:9], factors) == int(inn[9])
    return check(inn[:10], factors) == int(inn[10]) and check(inn[:11], (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)) == int(inn[11])


def valid_kpp(value: object | None) -> bool:
    kpp = digits(value)
    return bool(kpp and len(kpp) == 9)


def valid_bic(value: object | None) -> bool:
    bic = digits(value)
    return bool(bic and len(bic) == 9)


def valid_account(value: object | None) -> bool:
    account = digits(value)
    return bool(account and len(account) == 20)
