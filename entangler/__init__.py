"""Migen code & ARTIQ module to quickly generate & detect entanglement.

Outputs a certain sequence of GPIO/TTL pulses, and then checks for a return
pattern in a certain time window. If it receives that pattern, then it knows
entanglement has occurred.
"""
