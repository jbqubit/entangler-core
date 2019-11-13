# Entangler Gateware Notes

## Pin Configuration Notes

### Master Entangler -> Slave Entangler Communication

5 pins (Oxford) or 4 pins (UMD) are used for Master <-> Slave entangler communication. These must be connected
to correctly synchronize the two devices/gateware modules.

To do this:
    1. Build two gateware modules. Provide appropriate TTL/GPIO pins to communicate
        between the two modules.
    2. Configure the two gateware modules using appropriate driver calls.
        NOTE: the is_master flag is set on driver instantiation, so you can change
        this between ARTIQ experiments but probably not within the same experiment.
        An example sequence:
        ```python
        # In device_db.py:
        {
            "entangler_device_master": {
                "type": "local",
                "module": "entangler.driver",
                "class": "Entangler",
                "arguments": {
                    "channel": ENTANGLER_RTIO_CHANNEL,
                    "is_master": True,  # CHANGE THIS for slave
                },
            },
        }
        ```
        ```python
        @host_only
        def build():
            self.setattr_device("entangler_device_master")

        @kernel
        def prep_entangler()
            self.entangler_device_master.set_config(enable=False, standalone=False)
        ```

The synchronization pins are used as follows (in order they must be input into the Gateware builder):
    1. Ready: if ready to start the next entanglement cycle (Slave -> Master)
    2. (Master -> Slave): Trigger output
    3. (Master -> Slave): Entanglement success output
    4. (Master -> Slave): Entanglement cycle has timed out
    5. (OXFORD ONLY): (Slave -> Master): Sharing of the 422 laser pulse (disabled in Ion-Photon version of Entangler)

NOTE: these definitions can be found in [core.EntanglerCore](./core).

## Timestamp Configuration

Input timestamp resolution is 1ns
Max cycle length is ~10us
So lets use 14 bits per timestamp (16.38us max).
    * 11 upper bits are for the coarse timestamp (8 ns resolution),
    * 3 lowest bits are for the fine timestamp (< 8 ns resolution).

Core should only be enabled after sensible values are loaded into the registers.
E.g. if n_cycles=0 when the core is enabled it will saturate the ififo with timeout events...

## Coredevice Driver/Register Notes

Registers:
0b0000 : Config : w:
    from low to high bits [enable, is_master, standalone]
    set if master or slave, set if core enabled (i.e. un-tris master / slave outputs, override output phys)
0b0001 : Run : w: trigger sequence on write, set max time to run for
0b0010 : Cycle length: w:
0b0011 : Heralds: w: 4x 4 bit heralds, then 4 bits of herald enable flags (to allow working with fewer heralds) -> 20 bits

Timing registers: 4x outputs, 4x gating inputs
Each has 14 bits t_start, 14 bits t_end -> 32 bits (to align top to dword)
0b1_000 ... 0b1_110


0b10_000 : Status: r: core running?
0b10_001 : NCycles: r: How many cycles have been completed (reset every write to 'run') (14 bits, will roll over!)
5x timestamps: r: 14 bits each
0b11_000 ... 0b11_100

So bits[4:3]:
    * ``2'd0`` for low reg writes
    * ``2'd1`` for timing reg writes
    * ``2'd2`` for status reads
    * ``2'd3`` for timestamp reads

The smallest time stamp that is valid for output events is 1 (0 makes the output stay off permanently)
