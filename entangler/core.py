"""FPGA HDL modules that describe core 'Entangler' functionality.

Note: STB = "strobe", I forgot that one.
"""
import typing

import migen.build.generic_platform as platform
from dynaconf import settings
from migen import Cat
from migen import FSM
from migen import If
from migen import Instance
from migen import Module
from migen import Mux
from migen import NextState
from migen import NextValue
from migen import Signal

from .config_conversions import max_value_to_bit_width

# The 422ps laser system is shared, so for ease of use we OR the slave's RTIO TTL output
# with the master's signal as long as the entangler core isn't active. The timing will
# be different from entangler-driven use, but this is only for auxiliary calibration
# purposes.
SEQUENCER_IDX_422ps = 2


class ChannelSequencer(Module):
    """Pulses `output` between the given edge times.

    The signals ``m_start``/``m_stop`` define the counter ``m`` values between
    which this module outputs a high signal.

    Assumes that ``m`` is monotonically-increasing.

    Attributes:
        m_start: value of the counter signal at which to output a high signal
        m_stop: value of the counter signal at which the output will be set ``LOW``
        clear: de-asserts the output irrespective of the configured
            :attr:`m_start`/:attr:`m_stop` times.

    """

    def __init__(self, m):
        """Output a signal for a given time.

        Args:
            m: a ``counter_width`` counter :class:`Signal` that governs the output
                times.
        """
        self.m_start = Signal(settings.COARSE_COUNTER_WIDTH)
        self.m_stop = Signal(settings.COARSE_COUNTER_WIDTH)
        self.clear = Signal()

        self.output = Signal()

        # # #

        self.stb_start = Signal()
        self.stb_stop = Signal()

        self.comb += [
            self.stb_start.eq(m == self.m_start),
            self.stb_stop.eq(m == self.m_stop),
        ]

        self.sync += [
            If(self.stb_start, self.output.eq(1)).Else(
                If(self.stb_stop, self.output.eq(0))
            ),
            If(self.clear, self.output.eq(0)),
        ]


class TriggeredInputGater(Module):
    """Event gater that connects to ttl_serdes_generic phys.

    The gate is defined as a time window after a reference event occurs
    (i.e. window = (t_ref + gate_start, t_ref + gate_stop)).
    The reference time is that of a rising edge on ``phy_ref``. There is no protection
    against multiple edges on ``phy_ref``.
    The gate start and stop are specified as offsets in mu (=1 ns mostly) from this
    reference event.

    The module is triggered after it has seen a reference event, then subsequently
    a signal edge (from ``phy_sig``) in the gate window.
    Once the module is triggered, then subsequent signal edges are ignored.
    Clear has to be asserted to clear the reference edge and the triggered flag.

    The start gate offset must be at least 8 * mu.
    """

    def __init__(self, m, phy_ref, phy_sig):
        """Define the gateware to gate & latch inputs."""
        self.clear = Signal()

        self.triggered = Signal()

        n_fine = len(phy_ref.fine_ts)

        full_timestamp_width = settings.COARSE_COUNTER_WIDTH + n_fine
        # TODO: move assertion to where it actually matters, i.e. at PHY level
        assert full_timestamp_width == settings.FULL_COUNTER_WIDTH

        self.ref_ts = Signal(full_timestamp_width)
        self.sig_ts = Signal(full_timestamp_width)

        # In mu
        self.gate_start = Signal(full_timestamp_width)
        self.gate_stop = Signal(full_timestamp_width)

        # # #

        self.got_ref = Signal()

        # Absolute gate times, calculated when we get the reference event
        abs_gate_start = Signal(full_timestamp_width)
        abs_gate_stop = Signal(full_timestamp_width)

        t_ref = Signal(full_timestamp_width)
        self.comb += t_ref.eq(Cat(phy_ref.fine_ts, m))

        self.sync += [
            If(
                phy_ref.stb_rising,
                self.got_ref.eq(1),
                self.ref_ts.eq(t_ref),
                abs_gate_start.eq(self.gate_start + t_ref),
                abs_gate_stop.eq(self.gate_stop + t_ref),
            ),
            If(self.clear, self.got_ref.eq(0), self.triggered.eq(0)),
        ]

        past_window_start = Signal()
        before_window_end = Signal()
        triggering = Signal()
        t_sig = Signal(full_timestamp_width)
        self.comb += [
            t_sig.eq(Cat(phy_sig.fine_ts, m)),
            past_window_start.eq(t_sig >= abs_gate_start),
            before_window_end.eq(t_sig <= abs_gate_stop),
            triggering.eq(past_window_start & before_window_end & ~self.clear),
        ]

        self.sync += [
            If(
                phy_sig.stb_rising & ~self.triggered & triggering,
                self.triggered.eq(triggering),
                self.sig_ts.eq(t_sig),
            )
        ]


class UntriggeredInputGater(Module):
    """Event gater that connects to ttl_serdes_generic phys.

    The gate is defined as a time window of a counter.
    The gate start and stop are specified as absolute values of the counter,
    in MU (=1 ns mostly).

    The module is triggered if it sees a signal edge (from ``phy_sig``) in the
    gate window.
    Once the module is triggered, then subsequent signal edges are ignored.
    Clear has to be asserted to clear the triggered flag.

    NOTE: if both ``gate_start, gate_stop < 8``, or if ``gate_start >= gate_stop``,
    this module will not trigger.

    The start gate offset must be at least 8 * mu.
    """

    def __init__(self, m, phy_sig):
        """Define the gateware to gate & latch inputs."""
        self.clear = Signal()

        self.is_window_valid = Signal()  # output
        self.triggered = Signal()

        n_fine = len(phy_sig.fine_ts)

        full_timestamp_width = settings.COARSE_COUNTER_WIDTH + n_fine
        # TODO: move assertion to where it actually matters, i.e. at PHY level
        assert full_timestamp_width == settings.FULL_COUNTER_WIDTH

        self.sig_ts = Signal(full_timestamp_width)

        # In mu
        self.gate_start = Signal(full_timestamp_width)
        self.gate_stop = Signal(full_timestamp_width)

        # # #

        self.sync += [
            # reset on clear
            If(self.clear, self.triggered.eq(0))
        ]

        past_window_start = Signal()
        before_window_end = Signal()
        triggering = Signal()
        t_sig = Signal(full_timestamp_width)
        self.comb += [
            t_sig.eq(Cat(phy_sig.fine_ts, m)),
            self.is_window_valid.eq(
                (self.gate_start >= 8)
                & (self.gate_stop >= 8)
                & (self.gate_start < self.gate_stop)
            ),
            past_window_start.eq(t_sig >= self.gate_start),
            before_window_end.eq(t_sig <= self.gate_stop),
            triggering.eq(
                past_window_start
                & before_window_end
                & ~self.clear
                & self.is_window_valid
            ),
        ]

        self.sync += [
            # register input event
            If(
                phy_sig.stb_rising & ~self.triggered & triggering,
                self.triggered.eq(triggering),
                self.sig_ts.eq(t_sig),
            )
        ]


class PatternMatcher(Module):
    """Checks if input vector matches any pattern in patterns.

    Attributes:
        sig (:class:`Signal`(num_inputs)): input signal to match against
        patterns ([:class:`Signal`(num_inputs)] * num_patterns): patterns to match
            input signal against
        pattern_ens (:class:`Signal`(num_patterns)): enables matching for
            the specified pattern (one-hot encoding).
        matches (:class:`Signal`(num_patterns)): Outputs the patterns that matched
            the input
        is_match (:class:`Signal`): Asserted when any pattern matches.

    """

    def __init__(self, num_inputs=4, num_patterns=1):
        """Define pattern matching gateware."""
        self.sig = Signal(num_inputs)
        self.patterns = [Signal(num_inputs) for _ in range(num_patterns)]
        self.pattern_ens = Signal(num_patterns)
        self.matches = Signal(num_patterns)

        self.is_match = Signal()

        # # #

        self.comb += [
            self.matches[i].eq(p == self.sig) for i, p in enumerate(self.patterns)
        ]
        self.comb += self.is_match.eq(self.pattern_ens & self.matches != 0)


class MainStateMachine(Module):
    """State machine to run the entanglement generation process.

    Attributes:
        m (:class:`Signal`(counter_width)): Global counter, provides current
            position in cycle.
        time_remaining (:class:`Signal`(32)): Clock cycles remaining until
            the state machine times out. Output, only valid while running
        time_remaining_buf (:class:`Signal`(32)): Input, sets the time until
            ``timeout`` for the next run of the state machine.
        cycles_completed (:class:`Signal`(~14 bits)): number of entanglement
            cycles/loops completed since most recent start. Exact width is
            derived from settings.MAX_CYCLES_PER_RUN
        run_stb (:class:`Signal`(1)): Input signal/strobe, pulse high to start
            the state machine/entanglement generation loops.
        done_stb (:class:`Signal`(1)): Output signal, pulses high to signal
            completion (either timeout or success)
        running (:class:`Signal`(1)): High the whole time that the state
            machine is running
        timeout (:class:`Signal`(1)): Output signal, set if the state machine
            times out.
        success (:class:`Signal`(1)): Asserted when the state machine achieves
            success/pattern match/entanglement.
        ready (:class:`Signal`(1)): ??
        herald (:class:`Signal`): ??
        is_master (:class:`Signal`): Input signal, sets this instance of the
            state machine as a master, i.e. the main state machine
            driver/controller.
        standalone (:class:`Signal`): If this state machine is independent,
            and doesn't have a partner/slave state machine.
        act_as_master (:class:`Signal`): OUTPUT, If the state machine is acting in
            master configuration.
        trigger_out (:class:`Signal`): Trigger signal from master state machine
            to slave
        trigger_in_raw (:class:`Signal`): raw trigger input from the master ->
            slave state machine
        success_in_raw (:class:`Signal`): raw success input from the master state
            machine (used when slave)
        timeout_in_raw (:class:`Signal`): raw signal input (as slave) from master
            when the state machine sequence has timed out (too many cycles
            without success).
        slave_ready_raw (:class:`Signal`): Signal from slave -> master that the
            slave is ready.
        m_end (:class:`Signal`(``counter_width``)): The number of clock cycles
            that each entanglement loop should run for (units of coarse clock,
            should be 8 ns).
        cycle_starting (:class:`Signal`): asserted when an entanglement cycle
            (loop of the state machine) is starting
        cycle_ending (:class:`Signal`): asserted when an entanglement cycle
            (loop of the state machine) is ending

    """

    def __init__(self, counter_width=10):
        """Define the state machine logic for running the input & output sequences."""
        self.m = Signal(counter_width)  # Global cycle-relative time.
        self.time_remaining = Signal(32)  # Clock cycles remaining before timeout
        self.time_remaining_buf = Signal(32)
        # How many iterations of the loop have completed since last start
        self.cycles_completed = Signal(
            max_value_to_bit_width(settings.MAX_CYCLES_PER_RUN)
        )

        self.run_stb = Signal()  # Pulsed to start core running until timeout or success
        self.done_stb = (
            Signal()
        )  # Pulsed when core has finished (on timeout or success)
        self.running = Signal()  # Asserted on run_stb, cleared on done_stb

        self.timeout = Signal()
        self.success = Signal()

        self.ready = Signal()

        self.herald = Signal()

        self.is_master = Signal()
        self.standalone = Signal()  # Ignore state of partner for single-device testing.
        self.act_as_master = Signal()
        self.comb += self.act_as_master.eq(self.is_master | self.standalone)

        self.trigger_out = Signal()  # Trigger to slave

        # *** Sync signals from Master <-> Slave ***
        # Unregistered inputs from master
        self.trigger_in_raw = Signal()
        self.success_in_raw = Signal()
        self.timeout_in_raw = Signal()

        # Unregistered input from slave
        self.slave_ready_raw = Signal()

        self.m_end = Signal(
            counter_width
        )  # Number of clock cycles to run main loop for

        # Asserted while the entangler is idling, waiting for the entanglement cycle to
        # start.
        self.cycle_starting = Signal()

        self.cycle_ending = Signal()

        # # #

        self.comb += self.cycle_ending.eq(self.m == self.m_end)

        self.trigger_in = Signal()
        self.success_in = Signal()
        self.slave_ready = Signal()
        self.timeout_in = Signal()
        self.sync += [
            self.trigger_in.eq(self.trigger_in_raw),
            self.success_in.eq(self.success_in_raw),
            self.slave_ready.eq(self.slave_ready_raw),
            self.timeout_in.eq(self.timeout_in_raw),
        ]

        self.sync += [
            If(self.run_stb, self.running.eq(1)),
            If(self.done_stb, self.running.eq(0)),
        ]

        # The core times out if time_remaining countdown reaches zero, or,
        # if we are a slave, if the master has timed out.
        # This is required to ensure the slave syncs with the master
        self.comb += self.timeout.eq(
            (self.time_remaining == 0) | (~self.act_as_master & self.timeout_in)
        )

        self.sync += [
            If(self.run_stb, self.time_remaining.eq(self.time_remaining_buf)).Else(
                If(~self.timeout, self.time_remaining.eq(self.time_remaining - 1))
            )
        ]

        done = Signal()
        done_d = Signal()
        finishing = Signal()
        self.comb += finishing.eq(
            ~self.run_stb & self.running & (self.timeout | self.success)
        )
        # Done asserted at the at the end of the successful / timedout cycle
        self.comb += done.eq(finishing & self.cycle_starting)
        self.comb += self.done_stb.eq(done & ~done_d)

        # Ready asserted when run_stb is pulsed, and cleared on success or timeout
        self.sync += [
            If(
                self.run_stb,
                self.ready.eq(1),
                self.cycles_completed.eq(0),
                self.success.eq(0),
            ),
            done_d.eq(done),
            If(finishing, self.ready.eq(0)),
        ]

        fsm = FSM()
        self.submodules += fsm

        fsm.act(
            "IDLE",
            self.cycle_starting.eq(1),
            If(
                self.act_as_master,
                If(
                    ~finishing & self.ready & (self.slave_ready | self.standalone),
                    NextState("TRIGGER_SLAVE"),
                ),
            ).Else(If(~finishing & self.ready & self.trigger_in, NextState("COUNTER"))),
            NextValue(self.m, 0),
            self.trigger_out.eq(0),
        )
        fsm.act("TRIGGER_SLAVE", NextState("TRIGGER_SLAVE2"), self.trigger_out.eq(1))
        fsm.act("TRIGGER_SLAVE2", NextState("COUNTER"), self.trigger_out.eq(1))
        fsm.act(
            "COUNTER",
            NextValue(self.m, self.m + 1),
            If(
                self.cycle_ending,
                NextValue(self.cycles_completed, self.cycles_completed + 1),
                If(
                    self.act_as_master,
                    If(self.herald, NextValue(self.success, 1)),
                    NextState("IDLE"),
                ).Else(NextState("SLAVE_SUCCESS_WAIT")),
            ),
            self.trigger_out.eq(0),
        )
        fsm.act("SLAVE_SUCCESS_WAIT", NextState("SLAVE_SUCCESS_CHECK"))
        fsm.act(
            "SLAVE_SUCCESS_CHECK",  # On slave, checking if master broadcast success
            If(self.success_in, NextValue(self.success, 1)),
            NextState("IDLE"),
        )


class EntanglerCore(Module):
    """Highest block of the :mod:`entangler` gateware.

    This top-level block incorporates all the other subcomponents in this file,
    and is the primary one that should be used by end-users.
    """

    def __init__(
        self,
        core_link_pads: typing.Sequence[platform.Pins],
        output_pads: typing.Sequence[platform.Pins],
        passthrough_sigs: typing.Sequence[Signal],
        input_phys: typing.Sequence["PHY"],
        simulate: bool = False,
    ):
        """Define the submodules & connections between them to form an ``Entangler``.

        Args:
            core_link_pads (typing.Sequence[platform.Pins]): A list of 5 FPGA pins
                used to link a master & slave ``Entangler`` device.
            output_pads (typing.Sequence[platform.Pins]): The output pins that will
                be driven by the state machines to output the entanglement generation
                signals.
            passthrough_sigs (typing.Sequence[Signal]): The signals that should be
                passed through to the ``output_pads`` when the ``Entangler`` is not
                running.
            input_phys (typing.Sequence["PHY"]): TTLInput physical gateware modules
                that register an input TTL event. Expects a list of 4, with
                the first 4 being the input APD/TTL signals, and the last one
                as a sync signal with the entanglement laser.
            simulate (bool, optional): If this should be instantiated in
                simulation mode. If it is simulated, it disables several options like
                the passthrough_sigs. Defaults to False.
        """
        self.enable = Signal()

        # number of input APDs + 1 for the 422 pulse reference trigger
        assert len(input_phys) == settings.NUM_INPUT_SIGNALS + 1
        # TODO: more input length assertions
        # TODO: fix docs to refer to settings parameter
        # # #

        phy_apds = input_phys[0 : settings.NUM_INPUT_SIGNALS]  # noqa: E203
        phy_422pulse = input_phys[settings.NUM_INPUT_SIGNALS]

        self.submodules.msm = MainStateMachine()

        self.submodules.sequencers = [
            ChannelSequencer(self.msm.m) for _ in range(settings.NUM_OUTPUT_CHANNELS)
        ]

        self.submodules.apd_gaters = [
            TriggeredInputGater(self.msm.m, phy_422pulse, phy_apd)
            for phy_apd in phy_apds
        ]

        self.submodules.heralder = PatternMatcher(
            num_inputs=settings.NUM_INPUT_SIGNALS,
            num_patterns=settings.NUM_PATTERNS_ALLOWED,
        )

        if not simulate:
            # To be able to trigger the pulse picker from both systems without
            # re-plugging cables, we OR the output from the slave (transmitted over the
            # core link ribbon cable) into the master, as long as the entangler core is
            # not actually active. There is no mechanism to arbitrate between concurrent
            # users at this level; the application code must ensure only one experiment
            # requiring the pulsed laser runs at a time.
            local_422ps_out = Signal()
            slave_422ps_raw = Signal()

            # Connect output pads to sequencer output when enabled, otherwise use
            # the RTIO phy output
            for i, (sequencer, pad, passthrough_sig) in enumerate(
                zip(self.sequencers, output_pads, passthrough_sigs)
            ):
                if i == SEQUENCER_IDX_422ps:
                    local_422ps_out = Mux(
                        self.enable, sequencer.output, passthrough_sig
                    )
                    passthrough_sig = passthrough_sig | (
                        slave_422ps_raw & self.msm.is_master
                    )
                self.specials += Instance(
                    "OBUFDS",
                    i_I=Mux(self.enable, sequencer.output, passthrough_sig),
                    o_O=pad.p,
                    o_OB=pad.n,
                )

            # Connect the "running" output, which is asserted when the core is
            # running, or controlled by the passthrough signal when the core is
            # not running.
            # TODO: convert to settings
            self.specials += Instance(
                "OBUFDS",
                i_I=Mux(self.msm.running, 1, passthrough_sigs[4]),
                o_O=output_pads[-1].p,
                o_OB=output_pads[-1].n,
            )

            def ts_buf(pad, sig_o, sig_i, en_out):
                # diff. IO.
                # sig_o: output from FPGA
                # sig_i: intput to FPGA
                # en_out: enable FPGA output driver
                self.specials += Instance(
                    "IOBUFDS_INTERMDISABLE",
                    p_DIFF_TERM="TRUE",
                    p_IBUF_LOW_PWR="TRUE",
                    p_USE_IBUFDISABLE="TRUE",
                    i_IBUFDISABLE=en_out,
                    i_INTERMDISABLE=en_out,
                    i_I=sig_o,
                    o_O=sig_i,
                    i_T=~en_out,
                    io_IO=pad.p,
                    io_IOB=pad.n,
                )

            # Interface between master and slave core.

            # Slave -> master:
            ts_buf(
                core_link_pads[0],
                self.msm.ready,
                self.msm.slave_ready_raw,
                ~self.msm.is_master & ~self.msm.standalone,
            )

            ts_buf(
                core_link_pads[4], local_422ps_out, slave_422ps_raw, ~self.msm.is_master
            )

            # Master -> slave:
            ts_buf(
                core_link_pads[1],
                self.msm.trigger_out,
                self.msm.trigger_in_raw,
                self.msm.is_master,
            )
            ts_buf(
                core_link_pads[2],
                self.msm.success,
                self.msm.success_in_raw,
                self.msm.is_master,
            )
            ts_buf(
                core_link_pads[3],
                self.msm.timeout,
                self.msm.timeout_in_raw,
                self.msm.is_master,
            )

        # Connect heralder inputs.
        self.comb += self.heralder.sig.eq(Cat(*(g.triggered for g in self.apd_gaters)))

        # Clear gater and sequencer state at start of each cycle
        self.comb += [
            gater.clear.eq(self.msm.cycle_starting) for gater in self.apd_gaters
        ]
        self.comb += [
            sequencer.clear.eq(self.msm.cycle_starting) for sequencer in self.sequencers
        ]

        self.comb += self.msm.herald.eq(self.heralder.is_match)

        # 422ps trigger event counter. We use got_ref from the first gater for
        # convenience (any other channel would work just as well).
        self.triggers_received = Signal(
            max_value_to_bit_width(settings.MAX_TRIGGER_COUNTS)
        )
        self.sync += [
            If(self.msm.run_stb, self.triggers_received.eq(0)).Else(
                If(
                    # TODO: convert to parametrized??
                    self.msm.cycle_ending & self.apd_gaters[0].got_ref,
                    self.triggers_received.eq(self.triggers_received + 1),
                )
            )
        ]
