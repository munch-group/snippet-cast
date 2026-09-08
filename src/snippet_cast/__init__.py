from .screencast import build, export_script, main, record_narration

__all__ = ["build", "export_script", "main", "record_narration", "video"]


def __getattr__(name):
    """Expose `snippet_cast.video` without importing IPython up front.

    `video()` renders a snippet string and returns something to DISPLAY, so it
    lives in magic.py — the one module allowed to depend on IPython (see its
    docstring). Importing it here at module level would drag IPython into
    every `import snippet_cast`, including a plain script or a CLI run, and
    break the `jupyter` extra's whole point. PEP 562 lets the import wait
    until someone actually reaches for the name.

    Deliberately NOT gated on a live kernel the way
    _register_magic_if_in_notebook() is: registering a cell magic outside a
    kernel is meaningless, but calling video() from a plain script with
    IPython installed is not — it returns a displayable object like any other
    IPython.display helper."""
    if name == "video":
        try:
            from .magic import video
        except ImportError as e:      # IPython isn't installed
            raise ImportError(
                "snippet_cast.video needs IPython (it returns something to "
                "display in a notebook): pip install snippet-cast[jupyter]. "
                "To render a snippet without IPython, use "
                "snippet_cast.build(path, out_path, tts)."
            ) from e
        globals()["video"] = video    # only ever resolved once
        return video
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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