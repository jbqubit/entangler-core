"""Test the experimental sequence that UMD Ion-Photon uses."""
import logging
import math
import os
import random
import sys
import typing

import migen
from dynaconf import settings

# fmt: off
sys.path.append(os.path.join(os.path.dirname(__file__), "helpers"))

# pylint: disable=import-error
from coretester import CoreTestHarness  # noqa: E402
from gateware_utils import wait_until  # noqa: E402
from phytester import PhyTestHarness    # noqa: E402
# fmt: on

_LOGGER = logging.getLogger(__name__)
COARSE_CLOCK_PERIOD_NS = 8
ION_PHOTON_HERALD_PATTERNS = (0b0101, 0b1010, 0b1100, 0b0011)


def ion_photon_core_test(dut: CoreTestHarness) -> None:
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
    yield from dut.set_patterns(ION_PHOTON_HERALD_PATTERNS)

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
    yield  # move to check state, out of cycle

    # *** VALIDATION ***
    # Check Entangler worked as expected.
    assert bool((yield dut.core.heralder.is_match))
    assert (yield dut.core.heralder.matches) == 0b0010  # matches 2nd input pattern
    assert bool((yield dut.core.msm.success))
    assert (yield dut.core.msm.cycles_completed) == num_unsuccessful + 1
    assert not bool((yield dut.core.msm.timeout))


def ion_photon_phy_test(
    phy: PhyTestHarness,
    pump_stop_time_ns: int = 1000,
    photon_window_ns: int = 50,
    num_failed_cycles: int = 9,
    cycles_until_timeout: int = 50,
    herald_patterns: typing.Sequence[int] = None,
    event_times_rel_to_pump_stop: typing.Sequence[int] = None,
):
    """Test the PHY using the settings Ion-Photon will use.

    Performs automatic validation to ensure that the gateware is
    functioning as expected.

    Args:
        phy (PhyTestHarness): The gateware simulation object to modify.
        pump_stop_time_ns (int, optional): Time in ns when pumping the experiment
            should stop (assumes starts pumping at start of cycle, ends at this
            time). Defaults to 1000.
        photon_window_ns (int, optional): Window length in ns past the pumping
            stop time when we should look to observe a photon. Defaults to 50.
        num_failed_cycles (int, optional): Number of cycles that should pass
            without any entanglement success. Leave low to speed simulation.
            Defaults to 9.
        cycles_until_timeout (int, optional): Approximate number of attempts
            until the entanglement generation should timeout. Defaults to 50.
        herald_patterns (typing.Sequence[int], optional): Expected patterns that
            the entangled photons will generate upon detection. The default is
            specified in code in this file.
        event_times_rel_to_pump_stop (typing.Sequence[int], optional): A list of
            times relative to the pump stop when the photons should arrive.
            Set to negative to have them effectively not count.
            Default is a hard-coded set of times that corresponds to success
            with the default ``herald_patterns[0]``.

    Returns:
        None

    Yields:
        Migen gateware simulation.

    """
    _LOGGER.info("Starting basic IonPhoton EntanglerPHY functional test")
    core = phy.core.core
    msm = core.msm
    ADDR_TIMING = settings.ADDRESS_WRITE.TIMING

    if herald_patterns is None:
        herald_patterns = ION_PHOTON_HERALD_PATTERNS
    if event_times_rel_to_pump_stop is None:
        event_times_rel_to_pump_stop = (0, photon_window_ns, -10, -30)

    yield from phy.write(settings.ADDRESS_WRITE.CONFIG, 0b110)  # disable, standalone
    assert not bool((yield core.enable))
    assert bool((yield msm.act_as_master))
    assert bool((yield msm.standalone))

    cycle_len_ns = pump_stop_time_ns + (photon_window_ns * 3)
    pump_stop_time_coarse = math.ceil(pump_stop_time_ns / COARSE_CLOCK_PERIOD_NS)
    pump_timing_coarse = (0, pump_stop_time_coarse)

    for i, seq in enumerate(core.sequencers):
        yield from phy.write(
            ADDR_TIMING + i, (pump_timing_coarse[1] << 16) | pump_timing_coarse[0]
        )
        assert (yield seq.m_start) == pump_timing_coarse[0]
        assert (yield seq.m_stop) == pump_timing_coarse[1]

    photon_valid_window = (pump_stop_time_ns, pump_stop_time_ns + photon_window_ns)

    num_sequencers = settings.NUM_OUTPUT_CHANNELS
    assert num_sequencers == len(core.sequencers)
    for i, gater in enumerate(core.apd_gaters):
        write_addr = ADDR_TIMING + num_sequencers + i
        yield from phy.write(
            write_addr, photon_valid_window[1] << 16 | photon_valid_window[0]
        )
        assert (yield gater.gate_start) == photon_valid_window[0]
        assert (yield gater.gate_stop) == photon_valid_window[1]

    herald_patterns = ION_PHOTON_HERALD_PATTERNS
    yield from phy.write_heralds(herald_patterns)
    assert (yield core.heralder.pattern_ens) == 2 ** len(herald_patterns) - 1
    for i, pattern in enumerate(herald_patterns):
        assert (yield core.heralder.patterns[i]) == pattern
    assert not bool((yield core.heralder.is_match))

    yield from phy.write(settings.ADDRESS_WRITE.CONFIG, 0b111)
    assert bool((yield core.enable))
    assert bool((yield msm.is_master))
    assert bool((yield msm.standalone))

    cycle_len_coarse = int(cycle_len_ns / COARSE_CLOCK_PERIOD_NS)
    yield from phy.write(settings.ADDRESS_WRITE.TCYCLE, cycle_len_coarse)
    assert (yield msm.cycle_length_input) == cycle_len_coarse

    runtime = cycle_len_coarse * cycles_until_timeout
    max_clk_per_cycle = cycle_len_coarse + 5
    yield from phy.write(settings.ADDRESS_WRITE.RUN, runtime)
    for _ in range(num_failed_cycles):
        yield from wait_until(msm.cycle_ending, max_cycles=max_clk_per_cycle)
        assert not bool((yield msm.success))
        assert bool((yield msm.cycle_ending))
        yield

    # trigger first herald match
    yield from phy.set_event_times(pump_stop_time_ns, event_times_rel_to_pump_stop)

    yield from wait_until(msm.done_stb, max_cycles=max_clk_per_cycle)

    assert bool((yield msm.success))
    # check matched the correct pattern
    assert (yield phy.core.rtlink.i.data) == 0b1000
    assert (yield msm.cycles_completed) == num_failed_cycles + 1

    # pass lists as buffers to HACK-return values from yield-from func
    cyc_complete = [0]
    status = [0]
    time_remaining = [0]
    triggers = [0]
    timestamps = [[0]] * settings.NUM_INPUT_SIGNALS

    yield from phy.read(settings.ADDRESS_READ.TIME_REMAINING, time_remaining)
    _LOGGER.debug("Time remaining: %i", time_remaining[0])
    yield from phy.read(settings.ADDRESS_READ.NCYCLES, cyc_complete)
    yield from phy.read(settings.ADDRESS_READ.STATUS, status)
    _LOGGER.debug("Status: %i", status[0])
    yield from phy.read(settings.ADDRESS_READ.NTRIGGERS, triggers)
    _LOGGER.debug("Num triggers: %i", triggers[0])
    for i, ts in enumerate(timestamps):
        yield from phy.read(settings.ADDRESS_READ.TIMESTAMP + i, ts)
        _LOGGER.debug("Read timestamp[%i]: %i", i, ts[0])
        if event_times_rel_to_pump_stop[i] >= 0:
            assert ts[0] == event_times_rel_to_pump_stop[i] + pump_stop_time_ns
        else:
            assert ts[0] == 0

    assert cyc_complete[0] == num_failed_cycles + 1
    assert status[0] == 0b010  # not ready (i.e. starting), success, not timeout
    assert triggers[0] == 0
    # 4 for extra states in state machine (starting/stopping, etc)
    expected_time_elapsed = cyc_complete[0] * (cycle_len_coarse + 4)
    # Bound runtime to a fairly close number of cycles.
    assert (
        (runtime - expected_time_elapsed - 10)
        < time_remaining[0]
        < (runtime - expected_time_elapsed)
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    core_harness = CoreTestHarness(use_reference=False)
    phy_harness = PhyTestHarness(use_ref=False)
    migen.run_simulation(
        core_harness,
        ion_photon_core_test(core_harness),
        vcd_name="ion_photon_core.vcd",
        clocks={"sys": COARSE_CLOCK_PERIOD_NS},
    )
    migen.run_simulation(
        phy_harness,
        ion_photon_phy_test(phy_harness),
        vcd_name="ion_photon_phy.vcd",
        clocks={name: COARSE_CLOCK_PERIOD_NS for name in ["rio", "sys", "rio_phy"]},
    )
