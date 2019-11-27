import logging
import typing

import migen
from dynaconf import settings

import entangler.phy
from gateware_utils import MockPhy, rtio_output_event

_LOGGER = logging.getLogger(__name__)


class PhyHarness(migen.Module):
    """PHY Test Harness for :class:`entangler.phy.Entangler`."""

    def __init__(self):
        """Connect the mocked PHY devices to this device."""
        self.counter = migen.Signal(32)

        self.submodules.phy_apd0 = MockPhy(self.counter)
        self.submodules.phy_apd1 = MockPhy(self.counter)
        self.submodules.phy_apd2 = MockPhy(self.counter)
        self.submodules.phy_apd3 = MockPhy(self.counter)
        self.submodules.phy_ref = MockPhy(self.counter)
        input_phys = [self.phy_apd0, self.phy_apd1, self.phy_apd2, self.phy_apd3]

        core_link_pads = None
        output_pads = None
        passthrough_sigs = None
        self.submodules.core = entangler.phy.Entangler(
            core_link_pads,
            output_pads,
            passthrough_sigs,
            input_phys,
            reference_phy=self.phy_ref,
            simulate=True,
        )

        self.comb += self.counter.eq(self.core.core.msm.m)

    def write(self, address: int, data: int) -> None:
        """Write data to the ``EntanglerPHY`` using the data bus."""
        device_address = address & ((1 << 8) - 1)
        channel = (address - device_address) >> 8
        _LOGGER.debug(
            "Writing: (chan, addr, data) = %i, %i, %i", channel, device_address, data
        )
        yield from rtio_output_event(self.core.rtlink, address, data)

    def read(self, channel: int, data_ref: int) -> None:
        # HACK: sets an input buffer to the value read from the register
        _LOGGER.debug("Reading from channel %i")
        data_ref = (yield self.core.rtlink.i.data)

    def read_timestamped(self, channel: int, data_ref: int, time_ref: int) -> None:
        # HACK: sets an input buffer to the value read from the register
        # TODO: don't think this works
        yield from self.read(channel, data_ref)
        time_ref = (yield self.core.rtlink.i.timestamp)

    def write_heralds(self, heralds: typing.Sequence[int] = None):
        data = 0
        assert len(heralds) <= settings.NUM_PATTERNS_ALLOWED
        for i, h in enumerate(heralds):
            # enable bit
            data |= (1 << i) << (
                settings.NUM_INPUT_SIGNALS * settings.NUM_PATTERNS_ALLOWED
            )
            # move herald to appropriate position in register
            data |= h << (settings.NUM_INPUT_SIGNALS * i)
        yield from self.write(settings.ADDRESS_WRITE.HERALD, data)

    def set_event_times(
        self, ref_time: int, event_time_offsets: typing.Sequence[int]
    ) -> None:
        """Set the input signal event times within a cycle, in mu (ns).

        ``event_time_offsets`` set the event times relative to the ref_time.
        """
        real_event_times = (ref_time + offset for offset in event_time_offsets)
        yield self.phy_ref.t_event.eq(ref_time)
        for i, t in enumerate(real_event_times):
            yield getattr(self, "phy_apd{}".format(i)).t_event.eq(t)
