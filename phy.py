from migen import *

from artiq.gateware.rtio import rtlink
from ??? import EntanglerCore


class Entangler(Module):
    def __init__(self, if_pads, output_pads, input_phys):
        self.rtlink = rtlink.Interface(
            rtlink.OInterface(
                data_width=32,
                address_width=5,
                enable_replace=False),
            rtlink.IInterface(
                data_width=14,
                timestamped=False)
            )

        # # #

        read_en = self.rtlink.o.address[4]
        write_timings = Signal()
        self.comb += [
            self.rtlink.o.busy.eq(0),
            write_timings.eq(self.rtlink.o.address[4:3] == 1),
        ]

        self.submodules.core = EntanglerCore(eem_pads, [phy_apd1, phy_apd2],
                            phy_422pulse)

        output_t_starts = [Signal(14) for _ in range(8)]
        output_t_ends = [Signal(14) for _ in range(8)]


        self.sync.rio += [
            If(write_timings & self.rtlink.o.stb, 
                    output_t_starts[self.rtlink.o.address[2:]].eq(self.rtlink.o.data[13:]),
                    output_t_ends[self.rtlink.o.address[2:]].eq(self.rtlink.o.data[29:16])
                ),
            If(self.rtlink.o.address==0 & self.rtlink.o.stb,
                    # Write config
                ),
            If(self.rtlink.o.address==1 & self.rtlink.o.stb,
                    # Pulse run flag
                    # Write timeout reg
                ),
            If(self.rtlink.o.address==2 & self.rtlink.o.stb,
                    # Write cycle length
                ),
            If(self.rtlink.o.address==3 & self.rtlink.o.stb,
                    # Write herald pattern
                ),
        ]


        read = Signal()
        read_timings = Signal()
        read_addr = Signal()

        input_timestamps = [Signal(14) for _ in range(5)]

        self.sync.rio += [
                If(read,
                    read.eq(0)
                ),
                If(self.rtlink.o.stb,
                    read.eq(read_en),
                    read_timings.eq(self.rtlink.o.address[4:3] == 3),
                    read_addr.eq(self.rtlink.o.address[2:]),
                )
        ]

        self.comb += [
                self.rtlink.i.stb.eq(read),
                self.rtlink.i.data.eq(
                    Mux(read_timings,
                        input_timestamps[read_addr],
                        status if read_addr==0 else n_cycles))
        ]