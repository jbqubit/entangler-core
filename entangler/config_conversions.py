"""Conversions between settings values and usable values."""
import math


def max_value_to_bit_width(max_value: int) -> int:
    """Calculate how many bits are needed to represent an unsigned int."""
    return math.ceil(math.log2(max_value))
