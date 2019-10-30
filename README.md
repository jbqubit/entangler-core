# Entangler

FPGA code & ARTIQ coredevice driver for generating entanglement between multiple ions.

## Functionality

An ``entangler`` works by repeating the same sequence of outputs continuously until it
receives an entanglement signature (herald). The output sequence and desired inputs can
be configured at runtime with software calls. Then you trigger the sequencers & pattern
matchers, and it will either time out or stop when it has detected entanglement.

## Components

This repository is organized into several folders.

The ``entangler`` folder holds the gateware ([core.py](./entangler/core.py)
and [phy.py](./entangler/phy.py)) that describes how the entangler works.
It also holds the [ARTIQ](http://github.com/m-labs/artiq) coredevice driver that
sets up the entangler, triggers it, and gets information from it.

## Authors

Originally designed by the Oxford Ion Trap Group (@cjbe & @dnadlinger), extended/modified
by Drew Risinger (University of Maryland, Chris Monroe Ion Trap Group) (@drewrisinger).
