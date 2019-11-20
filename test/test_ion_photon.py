"""Test the experimental sequence that UMD Ion-Photon uses."""
import logging
import math
import os
import random
import sys
import typing

import migen
from dynaconf import settings

import entangler.core  # noqa: E402

# fmt: off
sys.path.append(os.path.join(os.path.dirname(__file__), "helpers"))

# pylint: disable=import-error
from gateware_utils import MockPhy  # noqa: E402
from gateware_utils import wait_until   # noqa: E402
# fmt: on

_LOGGER = logging.getLogger(__name__)
COARSE_CLOCK_PERIOD_NS = 8


class StandaloneHarness(migen.Module):
    """Test harness for the ``EntanglerCore``."""

    def __init__(self):
        """Pass through signals to an ``EntanglerCore`` instance."""
        self.counter = migen.Signal(32)

        self.submodules.phy_apd0 = MockPhy(self.counter)
        self.submodules.phy_apd1 = MockPhy(self.counter)
        self.submodules.phy_apd2 = MockPhy(self.counter)
        self.submodules.phy_apd3 = MockPhy(self.counter)
        input_phys = [self.phy_apd0, self.phy_apd1, self.phy_apd2, self.phy_apd3]

        core_link_pads = None
        output_pads = None
        passthrough_sigs = None
        self.submodules.core = entangler.core.EntanglerCore(
            core_link_pads,
            output_pads,
            passthrough_sigs,
            input_phys,
            reference_phy=None,
            simulate=True,
        )

        self.comb += self.counter.eq(self.core.msm.m)

    def setup_core(self, cycle_length: int, timeout: int):
        """Initialize the basic settings for the ``EntanglerCore``."""
        msm = self.core.msm
        _LOGGER.debug(
            "Setting up Entangler: CycTime (coarse) = %i, timeout (coarse) = %i",
            cycle_length,
            timeout,
        )
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
            yield patterns[i].eq(pattern)
            # yield
            # assert (yield patterns[i]) == pattern
        # set enables. Convert # of patterns -> one-hot encoding
        yield enables.eq((2 ** len(pattern_list)) - 1)

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


def ion_photon_test_function(dut: StandaloneHarness) -> None:
    """Test basic IonPhoton experiment.

    Not parametrized or fancy, just runs several unsuccessful experiments and
    eventually succeeds at entangling.
    """
    # *** SETUP ***
    num_inputs = settings.NUM_INPUT_SIGNALS
    num_outputs = settings.NUM_OUTPUT_CHANNELS

    # setup state machine settings
    # entanglement cycle length ~1300 ns, timeout = 1 ms
    cycle_length_ns = 1300
    timeout_length_ns = 1e6
    yield from dut.setup_core(
        math.ceil(cycle_length_ns / COARSE_CLOCK_PERIOD_NS),
        math.ceil(timeout_length_ns / COARSE_CLOCK_PERIOD_NS),
    )

    # set output timings, all equal
    pump_stop_time_ns = 1000
    pump_stop_time_coarse = math.ceil(pump_stop_time_ns / COARSE_CLOCK_PERIOD_NS)
    pump_timing_coarse = (0, pump_stop_time_coarse)
    yield from dut.set_sequencer_outputs([pump_timing_coarse] * num_outputs)

    window_length_ns = 50
    photon_valid_window = (pump_stop_time_ns, pump_stop_time_ns + window_length_ns)
    yield from dut.set_gating_times([photon_valid_window] * num_inputs)
    # "disable" input signals (set outside of cycle)
    yield from dut.set_event_times([cycle_length_ns + 10] * num_inputs)
    # NOTE: patterns are in reverse order vs setting event times
    # (event times are set for APD 1-4, while patterns are (L->R) 4-1)
    yield from dut.set_patterns((0b0101, 0b1010))

    # *** START RUNNING ***
    # start the state machine running
    yield from dut.start_entanglement_generator()

    # have a few unsuccessful trials
    num_unsuccessful = random.randint(5, 15)
    for _ in range(num_unsuccessful):
        yield from wait_until(dut.core.msm.cycle_ending, max_cycles=cycle_length_ns)
        yield

    # start time of the output event, in coarse units
    # TODO: could sweep photon_time through the window to make sure it registers
    # but, that should be tested exhaustively elsewhere, so not worried about that.
    valid_photon_time = math.ceil(sum(photon_valid_window) / 2)
    # should trigger the second pattern
    yield from dut.set_event_times(
        [cycle_length_ns, valid_photon_time] * int((num_inputs / 2))
    )
    yield from wait_until(dut.core.msm.cycle_ending, max_cycles=cycle_length_ns)
    yield   # move to check state, out of cycle

    # *** VALIDATION ***
    # Check Entangler worked as expected.
    assert bool((yield dut.core.heralder.is_match))
    assert (yield dut.core.heralder.matches) == 0b0010  # matches 2nd input pattern
    assert bool((yield dut.core.msm.success))
    assert (yield dut.core.msm.cycles_completed) == num_unsuccessful + 1
    assert not bool((yield dut.core.msm.timeout))


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    dut = StandaloneHarness()
    migen.run_simulation(
        dut,
        ion_photon_test_function(dut),
        vcd_name="ion_photon_entangler.vcd",
        clocks={"sys": COARSE_CLOCK_PERIOD_NS},
    )
