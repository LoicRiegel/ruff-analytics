"""Size ranges."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SizeRange:
    size_from: int
    size_to: int


@dataclass(frozen=True)
class SizeRangeSplit:
    first: SizeRange
    second: SizeRange


def split_size_range(size_range: SizeRange) -> SizeRangeSplit:
    """Split a size range in two.

    :raises ValueError: if the sizes cannot be split.
    """
    min_nb_of_bytes_to_split = 4
    if size_range.size_from > size_range.size_to:
        msg = "Cannot split sizes: size_from is > than size_to"
        raise ValueError(msg)
    if size_range.size_from == size_range.size_to:
        msg = "Cannot split sizes: size_from is the same as size_to"
        raise ValueError(msg)
    if size_range.size_to - size_range.size_from <= min_nb_of_bytes_to_split:
        msg = "Cannot split sizes: size_from and size_to have to be at least 4 bytes apart"
        raise ValueError(msg)
    mid = (size_range.size_from + size_range.size_to) // 2
    mid_after = mid + 1
    return SizeRangeSplit(SizeRange(size_range.size_from, mid), SizeRange(mid_after, size_range.size_to))
