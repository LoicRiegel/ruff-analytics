"""Date ranges."""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import NamedTuple


@dataclass(frozen=True)
class DateRange:
    date_from: date
    date_to: date


class DateRangeSplit(NamedTuple):
    first: DateRange
    second: DateRange


def split_date_range(date_range: DateRange) -> DateRangeSplit:
    """Split a date range in two.

    :raises ValueError: if the dates cannot be split.
    """
    if date_range.date_from >= date_range.date_to:
        msg = "Cannot split dates: date_from is > than date_to"
        raise ValueError(msg)
    if date_range.date_from == date_range.date_to:
        msg = "Cannot split dates: date_from is the same as date_to"
        raise ValueError(msg)
    if date_range.date_to - date_range.date_from <= timedelta(days=4):
        msg = "Cannot split dates: date_from and date_to have to be at least 4 days appart"
        raise ValueError(msg)
    mid = date_range.date_from + timedelta(days=(date_range.date_to - date_range.date_from).days // 2)
    mid_day_after = mid + timedelta(days=1)
    return DateRangeSplit(
        DateRange(date_range.date_from, mid),
        DateRange(mid_day_after, date_range.date_to),
    )
