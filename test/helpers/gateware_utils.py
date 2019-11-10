"""Shared functions & classes for testing the :mod:`entangler` gateware."""
from migen import If
from migen import Module
from migen import Signal


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
