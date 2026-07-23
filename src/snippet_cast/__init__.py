from .screencast import build, export_script, main, record_narration

__all__ = ["build", "export_script", "main", "record_narration"]


def _register_magic_if_in_notebook():
    """Auto-register `%%snippet-cast` on a plain `import snippet_cast` when
    IPython is already installed AND a live kernel/shell is running — so a
    notebook user doesn't have to know about `import snippet_cast.magic` or
    `%load_ext` at all. The `except ImportError: return` (no IPython
    installed) and `ip is None` (installed, but no live kernel — e.g. a
    plain script) cases both bail out *before* touching `snippet_cast.magic`,
    so a non-notebook `import snippet_cast` still never requires IPython —
    see magic.py's own module docstring for why that matters (IPython stays
    an optional `snippet-cast[jupyter]` extra).

    Calls `magic.load_ipython_extension()` explicitly (not just relying on
    `magic.py`'s own module-level auto-register) so this is idempotent and
    re-registers every time it's called — not only the first time
    `magic.py` is ever imported in this process (a bare `import
    snippet_cast.magic` is a no-op on the second call, since Python caches
    modules; IPython's `register_magics()` has no such caching)."""
    try:
        from IPython import get_ipython
    except ImportError:
        return
    ip = get_ipython()
    if ip is None:
        return
    from . import magic
    magic.load_ipython_extension(ip)


_register_magic_if_in_notebook()