"""Test the :class:`entangler.core.EntanglerCore` functionality."""
import logging
import os
import sys
import typing

# add gateware simulation tools "module" (at ./helpers/*)
sys.path.append(os.path.join(os.path.dirname(__file__), "helpers"))


from migen import Module  # noqa: E402
from migen import run_simulation  # noqa: E402
from migen import Signal  # noqa: E402

# pylint: disable=import-error
from entangler.core import EntanglerCore  # noqa: E402
from gateware_utils import MockPhy  # noqa: E402 ./helpers/gateware_utils
from gateware_utils import advance_clock  # noqa: E402

_LOGGER = logging.getLogger(__name__)


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

    def setup_core(self, cycle_length: int, timeout: int):
        """Initialize the basic settings for the ``EntanglerCore``."""
        msm = self.core.msm
        yield msm.cycle_length_input.eq(cycle_length)
        yield msm.timeout_input.eq(timeout)
        yield msm.is_master.eq(1)
        yield msm.standalone.eq(1)

    def set_sequencer_outputs(
        self, time_pairs: typing.Sequence[typing.Tuple[int, int]]
    ) -> None:
        """Set output TTL/GPIO timings."""
        sequencers = self.core.sequencers
        i = -1
        for i, timing_pair in enumerate(time_pairs):
            start, stop = timing_pair
            yield sequencers[i].m_start.eq(start)
            yield sequencers[i].m_stop.eq(stop)
        for disable_ind in range(i + 1, len(sequencers)):
            yield sequencers[disable_ind].m_start.eq(0)
            yield sequencers[disable_ind].m_stop.eq(0)

    def set_gating_times(
        self, time_pairs: typing.Sequence[typing.Tuple[int, int]]
    ) -> None:
        """Set time windows when the input gaters will register input events."""
        gaters = self.core.apd_gaters
        i = -1
        for i, timing_pair in enumerate(time_pairs):
            start, stop = timing_pair
            yield gaters[i].gate_start.eq(start)
            yield gaters[i].gate_stop.eq(stop)
        for disable_ind in range(i + 1, len(gaters)):
            yield gaters[disable_ind].gate_start.eq(0)
            yield gaters[disable_ind].gate_stop.eq(0)

    def set_event_times(self, event_times: typing.Sequence[int]) -> None:
        """Set the times when the mocked 'input' signals will occur."""
        for i, time in enumerate(event_times):
            yield getattr(self, "phy_apd{}".format(i)).t_event.eq(time)

    def set_patterns(self, pattern_list: typing.Sequence[int]):
        """Set the patterns that the ``EntanglerCore`` will try to match."""
        patterns = self.core.heralder.patterns
        enables = self.core.heralder.pattern_ens
        for i, pattern in enumerate(pattern_list):
            assert pattern < 2 ** len(patterns[i])
            _LOGGER.debug("Setting pattern %i = %x", i, pattern)
            yield self.core.heralder.patterns[i].eq(pattern)
            # yield
            # assert (yield patterns[i]) == pattern
        # set enables. Convert # of patters -> one-hot encoding
        yield enables.eq(2 ** len(pattern_list) - 1)

        # Verify enable setting
        # yield
        # _LOGGER.debug(
        #     "Enables val: %i, should be %i",
        #     (yield enables),
        #     ((2 ** len(pattern_list) - 1)),
        # )
        # assert (yield enables) == (2 ** len(pattern_list) - 1)

    def start_entanglement_generator(self) -> None:
        """Start the state machine that generates & checks for entanglement."""
        yield self.core.msm.run_stb.eq(1)
        yield
        yield self.core.msm.run_stb.eq(0)


def standalone_test(dut: StandaloneHarness):
    """Test the standalone :class:``EntanglerCore`` works properly."""
    yield from dut.setup_core(cycle_length=20, timeout=1000)

    yield from dut.set_sequencer_outputs([(1, 9), (2, 5), (3, 4)])

    yield from dut.set_gating_times([(18, 30), (8, 30), (18, 30)])

    yield dut.phy_ref.t_event.eq(75)
    yield from dut.set_event_times([1000] * 4)  # make events "impossible"

    yield from dut.set_patterns((0b0101, 0b1111))

    yield from advance_clock(5)

    assert (yield dut.core.uses_reference_trigger) == 1

    yield from dut.start_entanglement_generator()

    yield from advance_clock(500)

    # eventually, make an event happen.
    ref_event_time = 8 * 10 + 3
    yield dut.phy_ref.t_event.eq(ref_event_time)
    yield from dut.set_event_times([ref_event_time + i for i in (18, 40, 30, 30)])

    yield from advance_clock(50)

    # check the EntanglerCore succeeded as expected.
    assert (yield dut.core.msm.success) == 1
    assert (yield dut.core.msm.running) == 0
    assert (yield dut.core.msm.timeout) == 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    dut = StandaloneHarness()
    run_simulation(dut, standalone_test(dut), vcd_name="core_standalone.vcd")
