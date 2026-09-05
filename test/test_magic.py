import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import snippet_cast
import snippet_cast.magic as sc_magic
import snippet_cast.screencast as sc_screencast
from snippet_cast.screencast import (
    FONT_NAME, FONT_SIZE, SCREENFLOW_SIZE, _mono_font_path)

DATA = Path(__file__).parent / "data"
FIB = DATA / "fib.py"


def _rendering_available():
    """ffmpeg plus a pygments-resolvable font are both needed to render a clip."""
    if shutil.which("ffmpeg") is None:
        return False
    from pygments.formatters.img import FontManager

    try:
        FontManager(_mono_font_path() or FONT_NAME, FONT_SIZE)
    except Exception:
        return False
    return True


def _ipython_available():
    try:
        import IPython  # noqa: F401
    except ImportError:
        return False
    return True


pytestmark = pytest.mark.skipif(
    not (_ipython_available() and _rendering_available()),
    reason="requires IPython and (ffmpeg + a resolvable FONT_NAME)")


@pytest.fixture
def ip():
    from IPython.testing.globalipapp import get_ipython

    shell = get_ipython()
    shell.run_line_magic("load_ext", "snippet_cast.magic")
    return shell


def test_import_snippet_cast_registers_magic_in_live_kernel(ip):
    """Regression test: a plain `import snippet_cast` (not `import
    snippet_cast.magic`) must also auto-register %%snippet-cast when a live
    kernel and IPython are both present — see
    _register_magic_if_in_notebook() in snippet_cast/__init__.py."""
    ip.magics_manager.magics["cell"].pop("snippet-cast", None)
    assert "snippet-cast" not in ip.magics_manager.magics["cell"]

    snippet_cast._register_magic_if_in_notebook()

    assert "snippet-cast" in ip.magics_manager.magics["cell"]


def test_register_magic_is_noop_without_ipython_installed(monkeypatch):
    """The hook must bail out before ever importing snippet_cast.magic when
    IPython itself isn't installed — that's what keeps a plain `import
    snippet_cast` IPython-free outside a notebook."""
    monkeypatch.setitem(sys.modules, "IPython", None)
    snippet_cast._register_magic_if_in_notebook()  # must not raise


def test_cell_magic_renders_and_displays_video(ip, tmp_path):
    out = tmp_path / "out.mp4"
    cell = FIB.read_text()
    result = ip.run_cell(f"%%snippet-cast -o {out} --tts silent --subtitles\n{cell}")

    assert result.success
    assert out.exists()
    assert out.stat().st_size > 0


def test_cell_magic_export_script_does_not_render(ip, tmp_path, capsys):
    out = tmp_path / "should_not_exist.mp4"
    cell = FIB.read_text()
    result = ip.run_cell(f"%%snippet-cast -o {out} --export-script\n{cell}")

    assert result.success
    assert not out.exists()
    assert "Narration script" in capsys.readouterr().out


def test_cell_magic_two_pass_narration(ip, tmp_path):
    out = tmp_path / "out.mp4"
    cell = (
        "def f(n):    #: Writing f now. / f takes one argument, n.\n"
        "    return n #: /Return n right away.\n"
    )
    result = ip.run_cell(f"%%snippet-cast -o {out} --tts silent\n{cell}")

    assert result.success
    assert out.exists()


def test_cell_magic_reports_clean_error_on_empty_cell(ip, capsys):
    result = ip.run_cell("%%snippet-cast\n# just a comment, no narration\n")

    assert result.success  # the magic itself must not raise/crash the cell
    assert "No narration found" in capsys.readouterr().err


def test_cell_magic_renders_unnarrated_cell_when_pause_is_given(ip, tmp_path):
    out = tmp_path / "silent.mp4"
    result = ip.run_cell(
        f"%%snippet-cast -o {out} --pause 1\n"
        "# no narration here\n"
        "value = 21 * 2\n")

    assert result.success
    assert out.exists()


def test_cell_magic_renders_unnarrated_cell_with_every(ip, tmp_path):
    out = tmp_path / "loop.mp4"
    # --typing-speed is inert under --every and must not break the pacing.
    result = ip.run_cell(
        f"%%snippet-cast -o {out} --pause 2 --typing-speed 2 --every\n"
        "x = 0\n"
        "for i in range(3):\n"
        "    x += i\n")

    assert result.success
    assert out.exists()
    assert sc_screencast.probe_duration(str(out)) == pytest.approx(7 * 2, abs=0.15)


def test_cell_magic_accepts_font_size(ip, tmp_path):
    out = tmp_path / "big.mp4"
    result = ip.run_cell(
        f"%%snippet-cast -o {out} --tts silent --font-size {FONT_SIZE + 14}\n"
        "x = 1 #: one line\n")

    assert result.success
    assert out.exists()


def test_cell_magic_rejects_a_too_small_font_size(ip, capsys):
    result = ip.run_cell("%%snippet-cast --font-size 2\nx = 1 #: one line\n")

    assert result.success  # the magic itself must not raise/crash the cell
    assert "--font-size must be >=" in capsys.readouterr().err


def test_cell_magic_screenflow_renders_an_exact_frame(ip, tmp_path):
    out = tmp_path / "sf.mp4"
    result = ip.run_cell(
        f"%%snippet-cast -o {out} --tts silent --screenflow 1280x720\n"
        "x = 1 #: one line\n")

    assert result.success
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=width,height",
         "-of", "csv=p=0", str(out)], capture_output=True, text=True, check=True)
    assert probe.stdout.strip().splitlines()[0] == "1280,720"


def test_cell_magic_screenflow_bare_flag_uses_the_default_frame(ip, tmp_path):
    out = tmp_path / "sf.mp4"
    result = ip.run_cell(
        f"%%snippet-cast -o {out} --tts silent --screenflow --font-size 20\n"
        "x = 1 #: one line\n")

    assert result.success
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=width,height",
         "-of", "csv=p=0", str(out)], capture_output=True, text=True, check=True)
    assert probe.stdout.strip().splitlines()[0] == SCREENFLOW_SIZE.replace("x", ",")


def test_cell_magic_reports_a_bad_screenflow_value(ip, capsys):
    result = ip.run_cell("%%snippet-cast --screenflow huge\nx = 1 #: one line\n")

    assert result.success  # the magic itself must not raise/crash the cell
    assert "expected WxH" in capsys.readouterr().err


def test_cell_magic_record_rejects_conflicting_tts(ip, capsys):
    cell = FIB.read_text()
    result = ip.run_cell(f"%%snippet-cast --record --tts say\n{cell}")

    assert result.success  # the magic itself must not raise/crash the cell
    assert "--record always uses the manual backend" in capsys.readouterr().err


def test_cell_magic_record_defaults_manual_audio_dir(ip, tmp_path, monkeypatch):
    out = tmp_path / "out.mp4"
    calls = []

    def fake_record_narration(source_path, manual_audio_dir, out_path, **kw):
        calls.append(manual_audio_dir)
        Path(out_path).write_bytes(b"fake-mp4")
        return True

    monkeypatch.setattr(sc_magic, "record_narration", fake_record_narration)

    cell = FIB.read_text()
    result = ip.run_cell(f"%%snippet-cast -o {out} --record --no-frame\n{cell}")

    assert result.success
    assert calls == [sc_magic.MANUAL_AUDIO_DIR_DEFAULT]


def test_cell_magic_record_calls_record_narration_and_displays_video(ip, tmp_path, monkeypatch):
    out = tmp_path / "out.mp4"
    audio_dir = tmp_path / "audio"
    calls = []

    def fake_record_narration(source_path, manual_audio_dir, out_path, **kw):
        calls.append((manual_audio_dir, out_path, kw))
        Path(out_path).write_bytes(b"fake-mp4")
        return True

    monkeypatch.setattr(sc_magic, "record_narration", fake_record_narration)

    cell = FIB.read_text()
    result = ip.run_cell(
        f"%%snippet-cast -o {out} --manual-audio-dir {audio_dir} --record --no-frame\n{cell}")

    assert result.success
    assert out.read_bytes() == b"fake-mp4"
    assert len(calls) == 1
    manual_audio_dir, out_path, kw = calls[0]
    assert manual_audio_dir == str(audio_dir)
    assert out_path == str(out)
    assert kw["show_frame"] is False
    assert isinstance(kw["frame_fn"], sc_magic._LiveRecordView)


def test_cell_magic_record_clears_live_view_before_showing_video(ip, tmp_path, monkeypatch):
    """Regression test: the per-beat frame/status live view should be
    emptied once the real result (the video) is about to be shown, not
    left behind as stale clutter under it."""
    out = tmp_path / "out.mp4"
    audio_dir = tmp_path / "audio"
    cleared = []

    def fake_record_narration(source_path, manual_audio_dir, out_path, **kw):
        Path(out_path).write_bytes(b"fake-mp4")
        return True

    monkeypatch.setattr(sc_magic, "record_narration", fake_record_narration)
    orig_clear = sc_magic._LiveRecordView.clear

    def spy_clear(self):
        cleared.append(True)
        return orig_clear(self)

    monkeypatch.setattr(sc_magic._LiveRecordView, "clear", spy_clear)

    cell = FIB.read_text()
    result = ip.run_cell(
        f"%%snippet-cast -o {out} --manual-audio-dir {audio_dir} --record --no-frame\n{cell}")

    assert result.success
    assert cleared == [True]


def test_cell_magic_record_skips_display_and_clear_when_build_was_skipped(ip, tmp_path, monkeypatch):
    """Regression test: record_narration() returns True both when the
    build actually ran AND when it committed but skipped build_after (e.g.
    beats still missing recordings — see screencast.py's pre-build check).
    In the latter case out_path never gets created; the cell magic must
    not try to display() a nonexistent file, and must leave the live view
    (which already shows record_narration()'s own explanatory note)
    visible instead of clearing it."""
    out = tmp_path / "out.mp4"
    audio_dir = tmp_path / "audio"
    cleared = []

    def fake_record_narration(source_path, manual_audio_dir, out_path, **kw):
        print("note: 2 beat(s) still have no recording: 001, 002.")
        return True  # committed, but no file written -- build_after was skipped

    monkeypatch.setattr(sc_magic, "record_narration", fake_record_narration)
    orig_clear = sc_magic._LiveRecordView.clear

    def spy_clear(self):
        cleared.append(True)
        return orig_clear(self)

    monkeypatch.setattr(sc_magic._LiveRecordView, "clear", spy_clear)

    cell = FIB.read_text()
    result = ip.run_cell(
        f"%%snippet-cast -o {out} --manual-audio-dir {audio_dir} --record --no-frame\n{cell}")

    assert result.success  # must not crash trying to display a missing file
    assert not out.exists()
    assert cleared == []  # the diagnostic note must stay visible, not get wiped


def test_cell_magic_record_aborted_skips_display(ip, tmp_path, monkeypatch):
    out = tmp_path / "out.mp4"
    audio_dir = tmp_path / "audio"

    monkeypatch.setattr(sc_magic, "record_narration", lambda *a, **kw: False)

    cell = FIB.read_text()
    result = ip.run_cell(
        f"%%snippet-cast -o {out} --manual-audio-dir {audio_dir} --record\n{cell}")

    assert result.success  # aborting must not raise/crash the cell
    assert not out.exists()


def test_live_record_view_updates_status_and_frame_in_place(tmp_path, monkeypatch):
    """Regression test: --record's status text and per-beat frame previews
    used to accumulate as a growing stack of separate cell outputs (one
    display()/print() per beat). _LiveRecordView must instead create each
    display area ONCE and thereafter call .update() on the same handle."""
    from PIL import Image as PILImage

    calls = []

    class FakeHandle:
        def __init__(self, obj):
            self.obj = obj

        def update(self, obj):
            self.obj = obj
            calls.append(("update", obj))

    def fake_display(obj, display_id=None):
        calls.append(("display", obj))
        return FakeHandle(obj)

    monkeypatch.setattr(sc_magic, "display", fake_display)

    view = sc_magic._LiveRecordView(max_lines=2)
    view.write("line one\n")
    view.write("line two\n")
    view.write("line three\n")  # should push "line one" out of the window

    status_calls = [c for c in calls if isinstance(c[1], sc_magic.HTML)]
    assert sum(1 for kind, _ in status_calls if kind == "display") == 1
    assert sum(1 for kind, _ in status_calls if kind == "update") == 2
    assert status_calls[-1][1].data == "<pre>line two\nline three</pre>"

    frame1 = tmp_path / "frame1.png"
    frame2 = tmp_path / "frame2.png"
    PILImage.new("RGB", (4, 4), "red").save(frame1)
    PILImage.new("RGB", (4, 4), "blue").save(frame2)
    view(str(frame1))
    view(str(frame2))

    frame_calls = [c for c in calls if not isinstance(c[1], sc_magic.HTML)]
    assert sum(1 for kind, _ in frame_calls if kind == "display") == 1
    assert sum(1 for kind, _ in frame_calls if kind == "update") == 1


def test_live_record_view_clear_calls_clear_output(monkeypatch):
    calls = []
    monkeypatch.setattr(sc_magic, "clear_output", lambda wait=False: calls.append(wait))

    sc_magic._LiveRecordView().clear()

    assert calls == [True]


def test_cell_magic_record_output_goes_through_live_view_not_real_stdout(ip, tmp_path, monkeypatch):
    """Regression test: print()s made during a --record session (e.g. the
    per-beat '001 [pass 2, beat 1] ...' lines) must be captured by the
    redirect_stdout(view) wrapper and routed through display()'s
    create-once/update-thereafter path, not leak straight to stdout as
    separate accumulating lines. Spies on the REAL display() (and the
    handle it returns) rather than faking it, so this also stands as the
    regression test for two bugs only caught by going through the real
    IPython display machinery: a RecursionError from calling display()
    while sys.stdout was still redirected to the object display() itself
    writes through, and status text rendering as a quoted, \\n-escaped
    repr() instead of readable multi-line text (fixed by wrapping in
    HTML('<pre>...</pre>') rather than passing a bare str to display())."""
    out = tmp_path / "out.mp4"
    audio_dir = tmp_path / "audio"

    def fake_record_narration(source_path, manual_audio_dir, out_path, **kw):
        print("001  [pass 2, beat 1]  some narration")
        print("recording — press Enter to stop.")
        Path(out_path).write_bytes(b"fake-mp4")
        return True

    monkeypatch.setattr(sc_magic, "record_narration", fake_record_narration)

    rendered = []
    orig_display = sc_magic.display

    def spy_display(obj, display_id=None):
        handle = orig_display(obj, display_id=display_id)
        rendered.append(obj)
        if handle is not None:  # display() returns None unless display_id is set
            orig_update = handle.update

            def spy_update(o):
                rendered.append(o)
                return orig_update(o)

            handle.update = spy_update
        return handle

    monkeypatch.setattr(sc_magic, "display", spy_display)

    cell = FIB.read_text()
    result = ip.run_cell(
        f"%%snippet-cast -o {out} --manual-audio-dir {audio_dir} --record --no-frame\n{cell}")

    assert result.success
    html_objs = [o for o in rendered if isinstance(o, sc_magic.HTML)]
    assert len(html_objs) >= 2  # at least one create + one update
    assert "some narration" in html_objs[0].data
    assert "recording — press Enter to stop." in html_objs[-1].data
    assert "\\n" not in html_objs[-1].data  # real newline, not an escaped one


def test_cell_magic_accepts_style_and_bg_color(ip, tmp_path, monkeypatch):
    """--style/--bg-color reach build() from a cell the same way every other
    option does."""
    seen = {}
    monkeypatch.setattr(sc_magic, "build",
                        lambda *a, **kw: seen.update(kw) or Path(a[1]).touch())
    out = tmp_path / "out.mp4"
    result = ip.run_cell(
        f"%%snippet-cast --tts silent --style nord --bg-color none -o {out}\n"
        "x = 1 #: Assign one.\n")

    assert result.success
    assert seen["style"] == "nord"
    assert seen["bg_color"] is None   # 'none' -> the style's own background


def test_cell_magic_reports_clean_error_on_bad_style(ip, capsys):
    """A bad name must be caught at parse time with a listing, not surface as
    a pygments ClassNotFound from inside the first frame render (by which
    point the trace has already executed the user's snippet)."""
    result = ip.run_cell("%%snippet-cast --style no-such-style\nx = 1 #: One.\n")

    assert result.success  # the magic itself must not raise/crash the cell
    err = capsys.readouterr().err
    assert "no-such-style" in err and "monokai" in err


def test_cell_magic_reports_clean_error_on_bad_bg_color(ip, capsys):
    result = ip.run_cell("%%snippet-cast --bg-color chartreuse\nx = 1 #: One.\n")

    assert result.success
    assert "#rrggbb" in capsys.readouterr().err


def test_cell_magic_style_env_vars_are_read_per_cell(ip, tmp_path, monkeypatch):
    """The env var must be read fresh on every cell run — the whole reason
    magic.py resolves defaults in the method body instead of in an
    @argument(default=...), which is evaluated once at import time."""
    seen = {}
    monkeypatch.setattr(sc_magic, "build",
                        lambda *a, **kw: seen.update(kw) or Path(a[1]).touch())
    monkeypatch.setenv("SNIPPET_CAST_STYLE", "gruvbox-dark")
    monkeypatch.setenv("SNIPPET_CAST_BG_COLOR", "#101010")
    out = tmp_path / "out.mp4"
    result = ip.run_cell(
        f"%%snippet-cast --tts silent -o {out}\nx = 1 #: Assign one.\n")

    assert result.success
    assert (seen["style"], seen["bg_color"]) == ("gruvbox-dark", "#101010")


def test_cell_magic_accepts_state_colors(ip, tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(sc_magic, "build",
                        lambda *a, **kw: seen.update(kw) or Path(a[1]).touch())
    out = tmp_path / "out.mp4"
    result = ip.run_cell(
        f"%%snippet-cast --tts silent --state-bg-color #0d1117 "
        f"--state-fg-color #9CDCFE -o {out}\nx = 1 #: Assign one.\n")

    assert result.success
    assert seen["state_bg_color"] == "#0d1117"
    assert seen["state_fg_color"] == "#9CDCFE"


def test_cell_magic_reports_clean_error_on_bad_state_color(ip, capsys):
    result = ip.run_cell("%%snippet-cast --state-fg-color chartreuse\nx = 1 #: One.\n")

    assert result.success  # the magic itself must not raise/crash the cell
    err = capsys.readouterr().err
    assert "--state-fg-color" in err and "#rrggbb" in err


def test_cell_magic_state_color_env_vars_are_read_per_cell(ip, tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(sc_magic, "build",
                        lambda *a, **kw: seen.update(kw) or Path(a[1]).touch())
    monkeypatch.setenv("SNIPPET_CAST_STATE_BG_COLOR", "#222233")
    monkeypatch.setenv("SNIPPET_CAST_STATE_FG_COLOR", "#DCDCAA")
    out = tmp_path / "out.mp4"
    result = ip.run_cell(f"%%snippet-cast --tts silent -o {out}\nx = 1 #: One.\n")

    assert result.success
    assert (seen["state_bg_color"], seen["state_fg_color"]) == ("#222233", "#DCDCAA")
