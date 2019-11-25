"""Test the experimental sequence that UMD Ion-Photon uses."""
import logging
import math
import os
import random
import sys

import migen
from dynaconf import settings

import entangler.core  # noqa: E402

# fmt: off
sys.path.append(os.path.join(os.path.dirname(__file__), "helpers"))

# pylint: disable=import-error
from coretester import CoreTestHarness  # noqa: E402
from gateware_utils import MockPhy  # noqa: E402
from gateware_utils import wait_until   # noqa: E402
# fmt: on

_LOGGER = logging.getLogger(__name__)
COARSE_CLOCK_PERIOD_NS = 8


class StandaloneHarness(CoreTestHarness):
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


def ion_photon_test_function(dut: StandaloneHarness) -> None:
    """Test basic IonPhoton experiment.

    Not parametrized or fancy, just runs several unsuccessful experiments and
    eventually succeeds at entangling.
    """
    _LOGGER.info("Starting basic IonPhoton EntanglerCore functional test")
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
    yield from dut.set_patterns((0b0101, 0b1010, 0b1100, 0b0011))

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
    logging.basicConfig(level=logging.INFO)
    dut = StandaloneHarness()
    migen.run_simulation(
        dut,
        ion_photon_test_function(dut),
        vcd_name="ion_photon_entangler.vcd",
        clocks={"sys": COARSE_CLOCK_PERIOD_NS},
    )
