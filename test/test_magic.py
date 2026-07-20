import shutil
from pathlib import Path

import pytest

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
