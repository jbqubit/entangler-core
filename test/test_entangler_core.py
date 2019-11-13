"""Test the :class:`entangler.core.EntanglerCore` functionality."""
import os
import sys

# add gateware simulation tools "module" (at ./helpers/*)
sys.path.append(os.path.join(os.path.dirname(__file__), "helpers"))


from migen import Module  # noqa: E402
from migen import run_simulation  # noqa: E402
from migen import Signal  # noqa: E402

from entangler.core import EntanglerCore  # noqa: E402
from gateware_utils import MockPhy  # noqa: E402 ./helpers/gateware_utils


class StandaloneHarness(Module):
    """Test harness for the ``EntanglerCore``."""

    def __init__(self):
        """Pass through signals to an ``EntanglerCore`` instance."""
        self.counter = Signal(32)

        self.submodules.phy_apd0 = MockPhy(self.counter)
        self.submodules.phy_apd1 = MockPhy(self.counter)
        self.submodules.phy_apd2 = MockPhy(self.counter)
        self.submodules.phy_apd3 = MockPhy(self.counter)
        self.submodules.phy_ref = MockPhy(self.counter)
        input_phys = [self.phy_apd0, self.phy_apd1, self.phy_apd2, self.phy_apd3]

        core_link_pads = None
        output_pads = None
        passthrough_sigs = None
        self.submodules.core = EntanglerCore(
            core_link_pads,
            output_pads,
            passthrough_sigs,
            input_phys,
            reference_phy=self.phy_ref,
            simulate=True,
        )

        self.comb += self.counter.eq(self.core.msm.m)


def standalone_test(dut):
    """Test the standalone :class:``EntanglerCore`` works properly."""
    yield dut.core.msm.m_end.eq(20)
    yield dut.core.msm.is_master.eq(1)
    yield dut.core.msm.standalone.eq(1)
    yield dut.core.msm.time_remaining.eq(100)

    yield dut.core.sequencers[0].m_start.eq(1)
    yield dut.core.sequencers[0].m_stop.eq(9)
    yield dut.core.sequencers[1].m_start.eq(2)
    yield dut.core.sequencers[1].m_stop.eq(5)
    yield dut.core.sequencers[2].m_start.eq(3)
    yield dut.core.sequencers[2].m_stop.eq(4)
    yield dut.core.sequencers[3].m_start.eq(0)
    yield dut.core.sequencers[3].m_stop.eq(0)

    yield dut.core.apd_gaters[0].gate_start.eq(18)
    yield dut.core.apd_gaters[0].gate_stop.eq(30)
    yield dut.core.apd_gaters[1].gate_start.eq(18)
    yield dut.core.apd_gaters[1].gate_stop.eq(30)

    yield dut.phy_ref.t_event.eq(1000)
    yield dut.phy_apd0.t_event.eq(1000)
    yield dut.phy_apd1.t_event.eq(1000)
    yield dut.phy_apd2.t_event.eq(1000)
    yield dut.phy_apd3.t_event.eq(1000)

    yield dut.core.heralder.patterns[0].eq(0b0101)
    yield dut.core.heralder.pattern_ens[0].eq(1)

    for _ in range(5):
        yield

    assert (yield dut.core.uses_reference_trigger) == 1
    
    yield dut.core.msm.run_stb.eq(1)
    yield
    yield dut.core.msm.run_stb.eq(0)

    for _ in range(50):
        yield

    yield dut.phy_ref.t_event.eq(8 * 10 + 3)
    yield dut.phy_apd0.t_event.eq(8 * 10 + 3 + 18)
    yield dut.phy_apd1.t_event.eq(8 * 10 + 3 + 30)
    yield dut.phy_apd2.t_event.eq(8 * 10 + 3 + 30)
    yield dut.phy_apd3.t_event.eq(8 * 10 + 3 + 30)

    for _ in range(50):
        yield


if __name__ == "__main__":
    dut = StandaloneHarness()
    run_simulation(
        dut, standalone_test(dut), vcd_name="core_standalone.vcd", clocks={"sys": 8}
    )
