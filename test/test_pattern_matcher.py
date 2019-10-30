"""Test the :class:`entangler.core.PatternMatcher` properly pattern matches."""
from migen import run_simulation

from entangler.core import PatternMatcher

patterns = [0b1001, 0b0110, 0b1010, 0b0101]
n_sig = 4


def pattern_match_test(dut):
    """Test pattern recognition in the :class:`PatternMatcher`."""
    for i, p in enumerate(patterns):
        yield dut.patterns[i].eq(p)
    yield

    for j in range(2 ** len(patterns)):
        yield dut.pattern_ens.eq(j)
        yield
        for i in range(2 ** n_sig):
            yield dut.sig.eq(i)
            yield
            assert (yield dut.is_match) == any(
                [p == i and (j & 2 ** n) for n, p in enumerate(patterns)]
            )


if __name__ == "__main__":
    dut = PatternMatcher(num_inputs=n_sig, num_patterns=len(patterns))
    run_simulation(dut, pattern_match_test(dut), vcd_name="heralder.vcd")
