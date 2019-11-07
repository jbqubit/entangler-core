"""Test the :class:`entangler.core.TriggeredInputGater` registers input events."""
import os
import sys

from dynaconf import settings
from migen import If
from migen import Module
from migen import run_simulation
from migen import Signal

# add gateware simulation tools "module" (at ./helpers/*)
sys.path.append(os.path.join(os.path.dirname(__file__), "helpers"))


from entangler.core import TriggeredInputGater  # noqa: E402
from gateware_utils import MockPhy  # noqa: E402 pylint: disable=import-error

#  ./helpers/gateware_utils


class TriggeredGaterHarness(Module):
    """Test harness to wrap & pass signals to a ``TriggeredInputGater``."""

    def __init__(self):
        """Create a test harness for the :class:`TriggeredInputGater`."""
        self.m = Signal(settings.FULL_COUNTER_WIDTH)
        self.rst = Signal()
        self.sync += [self.m.eq(self.m + 1), If(self.rst, self.m.eq(0))]

        self.submodules.phy_ref = MockPhy(self.m)
        self.submodules.phy_sig = MockPhy(self.m)

        core = TriggeredInputGater(self.m, self.phy_ref, self.phy_sig)
        self.submodules.core = core
        self.comb += core.clear.eq(self.rst)


def gater_test(dut, gate_start=None, gate_stop=None, t_ref=None, t_sig=None):
    """Test a ``TriggeredInputGater`` correctly registers inputs."""
    yield dut.core.gate_start.eq(gate_start)
    yield dut.core.gate_stop.eq(gate_stop)
    yield dut.phy_ref.t_event.eq(t_ref)
    yield dut.phy_sig.t_event.eq(t_sig)
    yield
    yield
    yield dut.rst.eq(1)
    yield
    yield dut.rst.eq(0)

    for _ in range(20):
        yield

    triggered = (yield dut.core.triggered)

    ref_ts = (yield dut.core.ref_ts)
    sig_ts = (yield dut.core.sig_ts)

    print(triggered, ref_ts, sig_ts)

    dt = t_sig - t_ref
    expected_triggered = (dt >= gate_start) & (dt <= gate_stop)
    assert triggered == expected_triggered


if __name__ == "__main__":
    dut = TriggeredGaterHarness()
    run_simulation(dut, gater_test(dut, 20, 30, 20, 41), vcd_name="gater.vcd")

    gate_start = 8
    gate_stop = 25
    t_ref = 20

    dut = TriggeredGaterHarness()
    run_simulation(
        dut, gater_test(dut, gate_start, gate_stop, t_ref, t_ref + gate_start - 1)
    )

    dut = TriggeredGaterHarness()
    run_simulation(
        dut, gater_test(dut, gate_start, gate_stop, t_ref, t_ref + gate_start)
    )

    dut = TriggeredGaterHarness()
    run_simulation(
        dut, gater_test(dut, gate_start, gate_stop, t_ref, t_ref + gate_stop)
    )

    dut = TriggeredGaterHarness()
    run_simulation(
        dut, gater_test(dut, gate_start, gate_stop, t_ref, t_ref + gate_stop + 1)
    )
