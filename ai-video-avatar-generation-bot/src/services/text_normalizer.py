from __future__ import annotations

import json
import re
from dataclasses import dataclass

from num2words import num2words

from src.core.config import ROOT


MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


@dataclass(frozen=True)
class NormalizationResult:
    normalized_text: str
    issues: list[str]
    success: bool
    warnings: list[str]


def _words(number: str, ordinal: bool = False) -> str:
    try:
        return num2words(int(number), lang="en", to="ordinal" if ordinal else "cardinal")
    except (ValueError, NotImplementedError):
        return number


class TextNormalizer:
    def __init__(self) -> None:
        self.abbreviations = json.loads(
            (ROOT / "config" / "abbreviations.json").read_text(encoding="utf-8")
        )

    def normalize(self, text: str) -> NormalizationResult:
        issues: list[str] = []
        warnings: list[str] = []
        value = re.sub(r"https?://\S+|www\.\S+", "", text)
        value = re.sub(r"[*_`#\[\]()]", "", value)
        if value != text:
            issues.append("links or markup removed")

        for short, expanded in self.abbreviations.items():
            value, count = re.subn(
                rf"(?<!\w){re.escape(short)}(?!\w)",
                expanded,
                value,
            )
            if count:
                issues.append(f"expanded: {short}")

        unknown = sorted(set(re.findall(r"(?<!\w)[A-Z]{2,}(?!\w)", value)))
        for item in unknown:
            warnings.append(f"Unknown abbreviation: {item}")

        month_pattern = "|".join(MONTHS)

        def replace_day_month(match: re.Match[str]) -> str:
            issues.append("date written as words")
            return f"the {_words(match.group(1), ordinal=True)} of {match.group(2)}"

        value = re.sub(
            rf"\b(\d{{1,2}})\s+({month_pattern})\b",
            replace_day_month,
            value,
            flags=re.I,
        )

        def replace_month_day(match: re.Match[str]) -> str:
            issues.append("date written as words")
            return f"{match.group(1)} {_words(match.group(2), ordinal=True)}"

        value = re.sub(
            rf"\b({month_pattern})\s+(\d{{1,2}})\b",
            replace_month_day,
            value,
            flags=re.I,
        )

        def replace_time(match: re.Match[str]) -> str:
            hours, minutes = match.groups()
            issues.append("time written as words")
            if int(minutes) == 0:
                return f"{_words(hours)} o'clock"
            return f"{_words(hours)} {_words(minutes)}"

        value = re.sub(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)", replace_time, value)
        value, count = re.subn(
            r"\b(\d+)\s*%",
            lambda match: f"{_words(match.group(1))} percent",
            value,
        )
        if count:
            issues.append("percentages written as words")

        value, count = re.subn(r"\b(\d+)\b", lambda match: _words(match.group(1)), value)
        if count:
            issues.append("numbers written as words")

        value = re.sub(r"\s+", " ", value).strip()
        return NormalizationResult(
            normalized_text=value,
            issues=list(dict.fromkeys(issues)),
            success=True,
            warnings=warnings,
        )


def normalize(text: str) -> NormalizationResult:
    return TextNormalizer().normalize(text)
