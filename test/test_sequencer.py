"""Test the output event scheduler :class:`entangler.core.ChannelSequencer`."""
from migen import Module
from migen import run_simulation
from migen import Signal

from entangler.core import ChannelSequencer


class ChannelSequencerHarness(Module):
    """Test harness for the :class:`ChannelSequencer`."""

    def __init__(self):
        """Wrap & provide passthroughs for the :class:`ChannelSequencer`."""
        self.m = Signal(10)
        self.submodules.core = ChannelSequencer(self.m)


def channel_sequencer_test(dut):
    """Test the outputs of a :class:`ChannelSequencer`."""
    yield dut.core.clear.eq(1)
    yield dut.core.m_start.eq(10)
    yield dut.core.m_stop.eq(30)
    yield
    yield dut.core.clear.eq(0)

    for i in range(100):
        yield dut.m.eq(i)
        yield

        if i == 10:
            assert (yield dut.core.stb_start) == 1
            assert (yield dut.core.output) == 0
        if i == 11:
            assert (yield dut.core.output) == 1
        if i == 30:
            assert (yield dut.core.stb_stop) == 1
            assert (yield dut.core.output) == 1
        if i == 31:
            assert (yield dut.core.output) == 0


if __name__ == "__main__":
    dut = ChannelSequencerHarness()
    run_simulation(dut, channel_sequencer_test(dut), vcd_name="sequencer.vcd")
