"""willo_orchestrator — the persistent on-device process that turns a
freshly flashed Home Assistant Green into a claimed Willo Local device.

NOT part of custom_components/ — this package runs as its own process
(a HAOS add-on on real hardware), never inside HA Core's own Python
process. See main.py's module doc comment for the full boot sequence, and
this repo's README for what was verified against a real local HA Core
instance versus what still needs real HAOS hardware.
"""
