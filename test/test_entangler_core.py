"""Test the :class:`entangler.core.EntanglerCore` functionality."""
import os
import sys
import typing

# add gateware simulation tools "module" (at ./helpers/*)
sys.path.append(os.path.join(os.path.dirname(__file__), "helpers"))


from migen import Module  # noqa: E402
from migen import run_simulation  # noqa: E402
from migen import Signal  # noqa: E402

from entangler.core import EntanglerCore  # noqa: E402
from gateware_utils import MockPhy  # noqa: E402 ./helpers/gateware_utils
from gateware_utils import advance_clock  # noqa: E402


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

    def set_sequencer_outputs(
        time_pairs: typing.Sequence[typing.Tuple[int, int]]
    ) -> None:
        for i, timing_pair in enumerate(time_pairs):
            start, stop = timing_pair
            yield dut.core.sequencers[i].m_start.eq(start)
            yield dut.core.sequencers[i].m_stop.eq(stop)
        for disable_ind in range(i + 1, len(dut.core.sequencers)):
            yield dut.core.sequencers[disable_ind].m_start.eq(0)
            yield dut.core.sequencers[disable_ind].m_start.eq(0)

    def set_gating_times(time_pairs: typing.Sequence[typing.Tuple[int, int]]) -> None:
        for i, timing_pair in enumerate(time_pairs):
            start, stop = timing_pair
            yield dut.core.apd_gaters[i].gate_start.eq(start)
            yield dut.core.apd_gaters[i].gate_stop.eq(stop)
        for disable_ind in range(i + 1, len(dut.core.apd_gaters)):
            yield dut.core.sequencers[disable_ind].m_start.eq(0)
            yield dut.core.sequencers[disable_ind].m_start.eq(0)

    def set_event_times(event_times: typing.Sequence[int]) -> None:
        for i, time in enumerate(event_times):
            yield getattr(dut, "phy_apd{}".format(i)).t_event.eq(time)

    yield dut.core.msm.m_end.eq(20)
    yield dut.core.msm.is_master.eq(1)
    yield dut.core.msm.standalone.eq(1)
    yield dut.core.msm.cycle_timeout_length_input.eq(1000)

    yield from set_sequencer_outputs([(1, 9), (2, 5), (3, 4)])

    yield from set_gating_times([(18, 30), (18, 30)])

    yield dut.phy_ref.t_event.eq(1000)
    yield from set_event_times([1000] * 4)

    yield dut.core.heralder.patterns[0].eq(0b0101)
    yield dut.core.heralder.pattern_ens[0].eq(1)

    yield from advance_clock(5)

    assert (yield dut.core.uses_reference_trigger) == 1

    yield dut.core.msm.run_stb.eq(1)
    yield
    yield dut.core.msm.run_stb.eq(0)

    yield from advance_clock(50)

    yield dut.phy_ref.t_event.eq(8 * 10 + 3)
    yield from set_event_times([8 * 10 + 3 + i for i in (18, 30, 30, 30)])

    yield from advance_clock(50)


if __name__ == "__main__":
    dut = StandaloneHarness()
    run_simulation(
        dut, standalone_test(dut), vcd_name="core_standalone.vcd", clocks={"sys": 8}
    )
