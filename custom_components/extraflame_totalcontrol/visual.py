"""Stove SVG rendering for the dashboard card.

Builds an inline SVG depicting the stove with a flame proportional to
the current power level and a color shift driven by the machine state
and online/connectivity. The SVG is published as the ``svg`` attribute
of the visual sensor and rendered by the bundled
``custom:extraflame-stove-card`` Lovelace card.
"""
from __future__ import annotations

from .const import (
    MACHINE_STATE_COOLDOWN,
    MACHINE_STATE_LABELS,
    MACHINE_STATE_OFF,
    MACHINE_STATE_PREHEAT,
    MACHINE_STATE_RUNNING,
)

OFF_MACHINE_STATES = MACHINE_STATE_OFF


def _state_color(machine_state: int | None, online: bool) -> tuple[str, str]:
    """Return (window_color, accent_color) for the stove visual."""
    if not online:
        return ("#1a1a1a", "#555")
    if machine_state is None or int(machine_state) in OFF_MACHINE_STATES:
        return ("#202020", "#888")
    s = int(machine_state)
    if s in MACHINE_STATE_PREHEAT:
        return ("#2a1408", "#f59e0b")  # amber for startup
    if s in MACHINE_STATE_RUNNING:
        return ("#3a1a08", "#ff7a18")  # full orange when running
    if s in MACHINE_STATE_COOLDOWN:
        return ("#221208", "#d97706")  # darker amber on cooldown
    return ("#3a1a08", "#ff7a18")


def _status_label(machine_state: int | None, online: bool) -> str:
    if not online:
        return "OFFLINE"
    if machine_state is None:
        return "—"
    s = int(machine_state)
    if s in MACHINE_STATE_OFF:
        return "OFF"
    return MACHINE_STATE_LABELS.get(s, f"État {s}").upper()


def _flame_paths(power: int) -> str:
    """Generate 0..5 flame paths inside the stove window."""
    if power <= 0:
        return ""
    flames = []
    # Each flame: a teardrop-ish blob, with the tallest centered.
    positions = [80, 100, 120, 65, 135][:max(1, min(power, 5))]
    base_h = 70 + min(power, 5) * 8
    for i, cx in enumerate(positions):
        h = base_h - (i * 4)
        flames.append(
            f'<path d="M{cx - 12},170 '
            f'C{cx - 14},{170 - h * 0.4} {cx - 6},{170 - h * 0.6} {cx},{170 - h} '
            f'C{cx + 6},{170 - h * 0.6} {cx + 14},{170 - h * 0.4} {cx + 12},170 Z" '
            f'fill="url(#fl{i})" />'
        )
    grads = (
        '<defs>'
        + ''.join(
            f'<linearGradient id="fl{i}" x1="0" y1="1" x2="0" y2="0">'
            '<stop offset="0%" stop-color="#ffb347"/>'
            '<stop offset="50%" stop-color="#ff5500"/>'
            '<stop offset="100%" stop-color="#ffd56b"/>'
            '</linearGradient>'
            for i in range(5)
        )
        + '</defs>'
    )
    return grads + ''.join(flames)


def render_stove_svg(
    *,
    name: str,
    online: bool,
    machine_state: int | None,
    current_power: int,
    room_temp: float | None,
    target_room_temp: float | None,
    smoke_temp: float | None,
) -> str:
    """Render a stove as an inline SVG string."""
    window, accent = _state_color(machine_state, online)
    flames = _flame_paths(current_power)

    def _fmt_temp(v: float | None, unit: str = "°C") -> str:
        if v is None:
            return "—"
        return f"{v:.1f}{unit}"

    status_label = _status_label(machine_state, online)

    return f'''<svg viewBox="0 0 200 320" xmlns="http://www.w3.org/2000/svg" style="max-width:280px;display:block;margin:0 auto;">
  <!-- top vent / lid -->
  <rect x="30" y="20" width="140" height="14" rx="6" fill="#262626"/>
  <!-- pellet hopper -->
  <rect x="55" y="6" width="90" height="16" rx="4" fill="#1a1a1a"/>
  <!-- body -->
  <rect x="20" y="35" width="160" height="220" rx="14" fill="#1a1a1a" stroke="{accent}" stroke-width="2"/>
  <!-- window frame -->
  <rect x="36" y="65" width="128" height="120" rx="8" fill="#0d0d0d" stroke="{accent}" stroke-width="1.5"/>
  <!-- window background -->
  <rect x="42" y="71" width="116" height="108" rx="4" fill="{window}"/>
  <!-- flames -->
  <g opacity="{0.95 if online and current_power > 0 else 0.0}">{flames}</g>
  <!-- ash bed -->
  <ellipse cx="100" cy="180" rx="50" ry="6" fill="#2a2a2a"/>
  <!-- status pill (wider to fit longer state labels like "Stabilisation") -->
  <rect x="30" y="195" width="140" height="16" rx="8" fill="{accent}" opacity="0.25"/>
  <text x="100" y="206" text-anchor="middle" font-family="system-ui,sans-serif" font-size="10" font-weight="600" fill="{accent}">{status_label}</text>
  <!-- temps -->
  <text x="40" y="232" font-family="system-ui,sans-serif" font-size="10" fill="#bbb">Room</text>
  <text x="160" y="232" text-anchor="end" font-family="system-ui,sans-serif" font-size="13" font-weight="600" fill="#e8e8e8">{_fmt_temp(room_temp)}</text>
  <text x="40" y="246" font-family="system-ui,sans-serif" font-size="10" fill="#bbb">Target</text>
  <text x="160" y="246" text-anchor="end" font-family="system-ui,sans-serif" font-size="11" fill="#e8e8e8">{_fmt_temp(target_room_temp)}</text>
  <!-- legs -->
  <rect x="38" y="255" width="22" height="22" fill="#0f0f0f"/>
  <rect x="140" y="255" width="22" height="22" fill="#0f0f0f"/>
  <!-- power level dots P1..P5 -->
  <g transform="translate(50, 290)">
    {''.join(f'<circle cx="{i * 25}" cy="0" r="7" fill="{accent if i < current_power else "#333"}"/>'+f'<text x="{i*25}" y="3.5" text-anchor="middle" font-family="system-ui,sans-serif" font-size="8" font-weight="700" fill="#000">{i+1}</text>' for i in range(5))}
  </g>
</svg>'''
