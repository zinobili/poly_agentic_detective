"""Page CSS for the dashboard, with colours for the light and dark Streamlit themes."""

from __future__ import annotations

CSS = """
<style>
.badge{display:inline-block;padding:2px 10px;border-radius:999px;font-size:.8rem;
  font-weight:600;background:#e5e7eb;color:#374151}
.badge.lead{background:#dbeafe;color:#1e40af}
.badge.same{background:#fef3c7;color:#92400e}
.badge.none{background:#e5e7eb;color:#374151}
.meter i{display:inline-block;width:18px;height:6px;margin-right:3px;border-radius:3px;
  background:#e5e7eb}
.meter i.on{background:#2563eb}
.tech{font-family:ui-monospace,Consolas,monospace;font-size:.75rem;color:#6b7280;
  margin:-6px 0 8px 1.4rem}
.chip{display:inline-block;margin:0 6px 6px 0;padding:3px 10px;border:1px solid #d1d5db;
  border-radius:999px;font-size:.85rem}
.st-key-pair_nav{position:sticky;top:2.9rem;z-index:99;background:%(nav_bg)s;padding:6px 0;
  border-bottom:1px solid %(nav_border)s}
</style>
"""

# The sticky pair bar needs an opaque background that matches the active Streamlit theme.
NAV_COLORS = {
    "light": {"nav_bg": "#ffffff", "nav_border": "#e5e7eb"},
    "dark": {"nav_bg": "#0e1117", "nav_border": "#31333f"},
}


def page_css(theme: str | None) -> str:
    """The page CSS for the browser's theme ("light" when unknown)."""
    return CSS % NAV_COLORS.get(theme or "light", NAV_COLORS["light"])
