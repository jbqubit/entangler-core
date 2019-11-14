"""Shared functions & classes for testing the :mod:`entangler` gateware."""
import logging

from migen import If
from migen import Module
from migen import Signal

_LOGGER = logging.getLogger(__name__)


def advance_clock(num_cycles: int) -> None:
    """Advance the simulation clock by some number of cycles."""
    for _ in range(num_cycles):
        yield


def wait_until(
    signal: Signal, wait_until_high: bool = True, max_cycles: int = None
) -> None:
    """Advance the simulation clock until signal goes high (==1).

    If you provide ``max_cycles``, then it will timeout. If you set
    ``wait_until_high=False``, then it will look for a low signal instead.
    """
    if max_cycles is None:
        while (yield signal) != int(wait_until_high):
            yield
    else:
        i = 0
        while (yield signal) != int(wait_until_high) and i < max_cycles:
            i += 1
            yield
        if i >= max_cycles:
            _LOGGER.warning(
                "Wait timed out after %i cycles, might not have waited long enough",
                max_cycles,
            )


def rtio_output_event(rtlink, addr, data):
    """Simulate a RTIO output event happening on the RTIO bus."""
    yield rtlink.o.address.eq(addr)
    yield rtlink.o.data.eq(data)
    yield rtlink.o.stb.eq(1)
    yield
    yield rtlink.o.stb.eq(0)


class MockPhy(Module):
    """Mock an ARTIQ PHY module."""

    def __init__(self, counter: Signal):
        """Define the basic logic for a PHY module."""
        self.fine_ts = Signal(3)
        self.stb_rising = Signal()
        self.t_event = Signal(32)

        # # #
        # On clock edges, reset signals
        self.sync += [self.stb_rising.eq(0), self.fine_ts.eq(0)]
        # As soon as counter matches, register an event output
        # (set fine_ts & stb_rising). Putting this in sync makes it one clock delayed
        self.comb += [
            If(
                counter == self.t_event[3:],
                self.stb_rising.eq(1),
                self.fine_ts.eq(self.t_event[:3]),
            )
        ]
