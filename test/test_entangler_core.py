"""Test the :class:`entangler.core.EntanglerCore` functionality."""
import functools
import logging
import os
import sys
import typing

# add gateware simulation tools "module" (at ./helpers/*)
sys.path.append(os.path.join(os.path.dirname(__file__), "helpers"))


from dynaconf import settings  # noqa: E402
from migen import Module  # noqa: E402
from migen import run_simulation  # noqa: E402
from migen import Signal  # noqa: E402

# pylint: disable=import-error
from entangler.core import EntanglerCore  # noqa: E402
from gateware_utils import MockPhy  # noqa: E402 ./helpers/gateware_utils
from gateware_utils import advance_clock  # noqa: E402
from gateware_utils import wait_until  # noqa: E402

_LOGGER = logging.getLogger(__name__)


def int_to_bool_array(val: int, num_binary_digits: int) -> typing.Sequence[bool]:
    """Convert a one-hot-encoded (binary) number to the equivalent boolean array."""
    bool_arr = [bool(val & 1 << (i - 1)) for i in range(num_binary_digits, 0, -1)]
    assert len(bool_arr) == num_binary_digits
    return bool_arr


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


def standalone_test_parametrized(
    dut: StandaloneHarness, cycle_length: int, failed_cycles: int
):
    """Test that all possible combinations of input signals occur."""
    _LOGGER.info("Starting EntCore param test: cycle_length=%i", cycle_length)
    input_chans = settings.NUM_INPUT_SIGNALS
    output_chans = settings.NUM_OUTPUT_CHANNELS
    yield from dut.setup_core(cycle_length, 10000)
    yield from dut.set_sequencer_outputs([(i, 10 - i) for i in range(output_chans)])

    # setup input checking (patterns & gating)
    ref_time = int(cycle_length / 4 * 8)
    cycle_length_ns = int(cycle_length * 8)
    yield dut.phy_ref.t_event.eq(ref_time)
    # delay window by 1 coarse clock cycle (8ns) b/c it doesn't work in same clock as
    # reference
    gate_windows = [
        (ref_time + (i + 1) * 8, cycle_length_ns - ref_time) for i in range(input_chans)
    ]
    yield from dut.set_gating_times(gate_windows)
    patterns = (0b0011,)
    yield from dut.set_patterns(patterns)
    pattern_to_bool = functools.partial(int_to_bool_array, num_binary_digits=4)
    bool_patterns = list(map(pattern_to_bool, patterns))

    gates_did_trigger = []

    def read_gates_triggered() -> None:
        gates_did_trigger.clear()
        for gater in dut.core.apd_gaters:
            # NOTE: doesn't like yield in iterator syntax...
            gates_did_trigger.append(bool((yield gater.triggered)))

    # Sweep the event times through the window, and check that it triggers properly.
    for signal_time in range(ref_time, cycle_length_ns + 20):
        _LOGGER.info("Testing signal_time (mod cycle_length) = %i", signal_time)

        # run a few dummy cycles where no signal occurs
        yield from dut.set_event_times([cycle_length_ns + 10] * input_chans)
        yield from dut.start_entanglement_generator()
        for cyc in range(failed_cycles):
            yield from wait_until(dut.core.msm.cycle_ending, max_cycles=cycle_length_ns)
            yield from read_gates_triggered()
            yield
            try:
                assert not any(gates_did_trigger)
            except AssertionError as err:
                _LOGGER.error("Gates triggered (none should): %s", gates_did_trigger)
                raise err
            assert not bool((yield dut.core.msm.success))
            cyc_completed = yield dut.core.msm.cycles_completed
            # _LOGGER.debug("Cycles completed: %i", cyc_completed)
            assert cyc_completed == cyc + 1

        # now, allow entanglement to happen
        yield from dut.set_event_times([signal_time] * input_chans)

        yield from wait_until(dut.core.msm.cycle_ending, max_cycles=cycle_length_ns)
        yield  # advance to IDLE state, I think

        # check the proper output events occurred
        yield from read_gates_triggered()
        gates_should_trigger = [
            t1 <= (signal_time - ref_time) <= t2 for t1, t2 in gate_windows
        ]
        try:
            assert gates_did_trigger == gates_should_trigger
        except AssertionError as err:
            _LOGGER.debug("Time elapsed since ref: %i", signal_time - ref_time)
            _LOGGER.debug("Window times (rel to reference): %s", gate_windows)
            _LOGGER.error(
                "Triggered: %s, should_trigger: %s",
                gates_did_trigger,
                gates_should_trigger,
            )
            raise err

        entanglement_did_succeed = yield dut.core.msm.success
        triggers_in_pattern_format = list(reversed(gates_did_trigger))
        entanglement_should_succeed = any(
            triggers_in_pattern_format == pat for pat in bool_patterns
        )
        try:
            assert entanglement_did_succeed == entanglement_should_succeed
        except AssertionError as err:
            _LOGGER.error(
                "Expected, measured entanglement: %s, %s",
                entanglement_should_succeed,
                bool(entanglement_did_succeed),
            )
            raise err
        assert (yield dut.core.msm.cycles_completed) == failed_cycles + 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    dut = StandaloneHarness()
    run_simulation(dut, standalone_test(dut), vcd_name="core_standalone.vcd")

    dut = StandaloneHarness()
    run_simulation(
        dut,
        standalone_test_parametrized(dut, cycle_length=20, failed_cycles=3),
        vcd_name="core_standalone_param_1.vcd",
    )

    dut = StandaloneHarness()
    run_simulation(
        dut,
        standalone_test_parametrized(dut, cycle_length=50, failed_cycles=3),
        vcd_name="core_standalone_param_2.vcd",
    )
