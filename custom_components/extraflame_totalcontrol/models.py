"""Map between the cloud's ``resourceId`` and a human-readable stove model.

The TotalControl 2.0 cloud API only exposes ``resourceId`` (an internal
Extraflame product code, e.g. ``A700051764``) and a ``type`` integer (most
models report ``"0"``). It does not return a model name. This file is the
community-maintained translation table.

If your stove shows the bare resourceId in Home Assistant's device card,
please open an issue at
https://github.com/Shad107/ha-extraflame-totalcontrol/issues
with the resourceId and the model name printed on the stove's nameplate
(visible from the back / inside the pellet hopper). Pull requests welcome.

The mapping is consulted twice:
- in :func:`stove_device_info` to populate the ``model`` field of the HA
  device, so Settings → Devices & Services shows ``Teodora Evo`` instead
  of ``0``.
- exposed as :func:`resolve_model` for callers that want the resolved
  name (the standalone client doesn't depend on this map at all).
"""
from __future__ import annotations

RESOURCE_ID_TO_MODEL: dict[str, str] = {
    # ---- Extraflame ----
    "A700051764": "Teodora Evo",
    # add yours here, see CONTRIBUTING…
}


def resolve_model(resource_id: str | None, fallback: str = "Pellet stove") -> str:
    """Return the readable model name for a resourceId, or ``fallback``.

    Never returns the raw ``resourceId``; if unknown, the fallback is a
    generic label so the HA device card stays readable.
    """
    if not resource_id:
        return fallback
    return RESOURCE_ID_TO_MODEL.get(resource_id, fallback)
