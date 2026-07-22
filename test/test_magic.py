import shutil
from pathlib import Path

import pytest

import snippet_cast.magic as sc_magic
from snippet_cast.screencast import FONT_NAME, FONT_SIZE, _mono_font_path

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


def test_cell_magic_record_requires_manual_audio_dir(ip, capsys):
    cell = FIB.read_text()
    result = ip.run_cell(f"%%snippet-cast --record\n{cell}")

    assert result.success
    assert "--record requires --manual-audio-dir" in capsys.readouterr().err


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

    status_calls = [c for c in calls if isinstance(c[1], str)]
    assert sum(1 for kind, _ in status_calls if kind == "display") == 1
    assert sum(1 for kind, _ in status_calls if kind == "update") == 2
    assert status_calls[-1] == ("update", "line two\nline three")

    frame1 = tmp_path / "frame1.png"
    frame2 = tmp_path / "frame2.png"
    PILImage.new("RGB", (4, 4), "red").save(frame1)
    PILImage.new("RGB", (4, 4), "blue").save(frame2)
    view(str(frame1))
    view(str(frame2))

    frame_calls = [c for c in calls if not isinstance(c[1], str)]
    assert sum(1 for kind, _ in frame_calls if kind == "display") == 1
    assert sum(1 for kind, _ in frame_calls if kind == "update") == 1


def test_cell_magic_record_output_goes_through_live_view_not_real_stdout(ip, tmp_path, monkeypatch, capsys):
    """Regression test: print()s made during a --record session (e.g. the
    per-beat '001 [pass 2, beat 1] ...' lines) must be captured by the
    redirect_stdout(view) wrapper and routed through display()'s
    create-once/update-thereafter path, not leak straight to stdout as
    separate accumulating lines. The globalipapp test shell has no real
    frontend, so display()/update() fall back to printing each object's
    repr() — that's expected and still lets this test verify the SECOND
    print() triggered an update() carrying the ACCUMULATED text (both
    lines together), not a second independent, disconnected display()."""
    out = tmp_path / "out.mp4"
    audio_dir = tmp_path / "audio"

    def fake_record_narration(source_path, manual_audio_dir, out_path, **kw):
        print("001  [pass 2, beat 1]  some narration")
        print("recording — press Enter to stop.")
        Path(out_path).write_bytes(b"fake-mp4")
        return True

    monkeypatch.setattr(sc_magic, "record_narration", fake_record_narration)

    cell = FIB.read_text()
    result = ip.run_cell(
        f"%%snippet-cast -o {out} --manual-audio-dir {audio_dir} --record --no-frame\n{cell}")

    assert result.success
    output = capsys.readouterr().out
    combined = "001  [pass 2, beat 1]  some narration\nrecording — press Enter to stop."
    assert repr(combined) in output
