import os
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
        "def f(n):    #: Writing f now. // f takes one argument, n.\n"
        "    return n #: /Return n right away.\n"
    )
    result = ip.run_cell(f"%%snippet-cast -o {out} --tts silent\n{cell}")

    assert result.success
    assert out.exists()


def test_cell_magic_help_prints_options_and_renders_nothing(ip, tmp_path, monkeypatch, capsys):
    """magic_arguments builds its parser with add_help=False, so without an
    explicit --help the cell just fails with "unrecognized arguments"."""
    monkeypatch.chdir(tmp_path)
    result = ip.run_cell("%%snippet-cast --help\nx = 1  #: one\n")

    out = capsys.readouterr().out
    assert result.success
    assert "--order" in out and "--tts" in out and "SNIPPET_CAST_PAUSE" in out
    assert "%%snippet-cast" in out           # not magic_arguments' %snippet_cast
    assert not out.lstrip().startswith("::")  # nor its reST literal marker
    # answering the question is all it does
    assert not list(tmp_path.glob("**/*.mp4"))


@pytest.mark.parametrize("src", [
    "%%snippet-cast --help",            # nothing at all under it
    "%%snippet-cast --help\n\n\n",      # only blank lines
])
def test_help_works_with_an_empty_cell_body(ip, tmp_path, monkeypatch, capsys, src):
    """IPython raises on a `%%` cell whose body is empty (`cell == ''` in
    run_cell_magic) BEFORE any magic runs, so this is fixed in the input
    transformer stage by rewriting it to the line-magic form."""
    monkeypatch.chdir(tmp_path)
    result = ip.run_cell(src)

    assert result.success
    assert "--order" in capsys.readouterr().out


def test_line_magic_form_answers_help(ip, capsys):
    result = ip.run_cell("%snippet-cast --help")
    assert result.success
    assert "--tts" in capsys.readouterr().out


def test_line_magic_without_a_cell_says_what_to_do(ip, capsys):
    result = ip.run_cell("%snippet-cast --tts silent")
    assert result.success
    assert "%%snippet-cast" in capsys.readouterr().err


@pytest.mark.parametrize("lines", [
    ["%%snippet-cast -q\n", "x = 1  #: one\n"],   # a real snippet
    ["%%time\n", "x = 1\n"],                      # somebody else's magic
    ["x = 1\n"],                                  # ordinary code
    [],                                            # an empty cell
])
def test_input_transformer_leaves_every_other_cell_alone(lines):
    """It runs on EVERY cell in the notebook, so it has to be inert."""
    assert sc_magic._bodiless_cell_to_line_magic(list(lines)) == lines


def test_input_transformer_is_registered_once(ip):
    """%load_ext can be called again, and autoreload re-imports."""
    sc_magic.load_ipython_extension(ip)
    sc_magic.load_ipython_extension(ip)
    assert sum(1 for t in ip.input_transformers_cleanup
               if getattr(t, "__name__", "") == "_bodiless_cell_to_line_magic") == 1


def test_cell_magic_help_wins_over_other_arguments(ip, tmp_path, monkeypatch, capsys):
    """It is checked before env resolution and every validation, so it
    answers whatever else the line says."""
    monkeypatch.chdir(tmp_path)
    result = ip.run_cell("%%snippet-cast --help --style no-such-style\nx = 1  #: one\n")

    assert result.success
    captured = capsys.readouterr()
    assert "--order" in captured.out
    assert captured.err == ""            # no unknown-style complaint
    assert not list(tmp_path.glob("**/*.mp4"))


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


def test_cell_magic_quiet_suppresses_output(ip, tmp_path, capsys):
    out = tmp_path / "q.mp4"
    cell = 'x = 1  #: one\nprint("snippet output")  #: two\n'

    ip.run_cell(f"%%snippet-cast -o {out} --tts silent\n{cell}")
    assert "done." in capsys.readouterr().out

    out2 = tmp_path / "q2.mp4"
    result = ip.run_cell(f"%%snippet-cast -o {out2} --tts silent -q\n{cell}")
    assert result.success
    quiet = capsys.readouterr().out
    # The rendered video is the cell's RESULT and is still displayed (headless,
    # display() falls back to printing its repr); only the chatter is gone.
    assert "done." not in quiet
    assert "beats ->" not in quiet
    assert "snippet output" not in quiet     # the cell's own print, too
    assert out2.exists()


def test_cell_magic_quiet_rejects_record(ip, capsys):
    result = ip.run_cell("%%snippet-cast --record -q\nx = 1  #: one\n")

    assert result.success  # the magic itself must not raise/crash the cell
    assert "--quiet can't be used with --record" in capsys.readouterr().err










def _tag(html):
    return html[html.index("<video"):html.index(">", html.index("<video")) + 1]


def _style(html):
    return html[html.index("<style>"):html.index("</style>")]


def test_controls_are_restyled_by_default(tmp_path):
    """The gradient scrim always goes — it covers roughly the bottom two-thirds
    of the frame — so every displayed video now carries the <style> block."""
    f = tmp_path / "v.mp4"
    f.write_bytes(b"\x00")
    html = sc_magic._video(str(f), False, False)._repr_html_()
    assert "::-webkit-media-controls-panel" in _style(html)
    assert "background-image:none" in _style(html)


def test_dark_glyphs_for_a_light_frame_light_glyphs_for_a_dark_one(tmp_path):
    """`light_controls` selects the glyph colour: inverted (dark) for a light
    frame, left white for a dark one, where inverting would hide them."""
    f = tmp_path / "v.mp4"
    f.write_bytes(b"\x00")

    dark_glyphs = sc_magic._video(str(f), False, False, False)._repr_html_()
    assert "invert(1)" in _style(dark_glyphs)
    assert f'class="{sc_magic.CONTROLS_CLASSES[False]}"' in _tag(dark_glyphs)

    light_glyphs = sc_magic._video(str(f), False, False, True)._repr_html_()
    assert "invert" not in _style(light_glyphs)
    assert f'class="{sc_magic.CONTROLS_CLASSES[True]}"' in _tag(light_glyphs)


def test_controls_variants_use_distinct_classes(tmp_path):
    """A Quarto page can hold a light cell and a dark one. Two <style> blocks
    on the SAME class would leave the later rule governing both videos."""
    assert sc_magic.CONTROLS_CLASSES[True] != sc_magic.CONTROLS_CLASSES[False]
    f = tmp_path / "v.mp4"
    f.write_bytes(b"\x00")
    page = (sc_magic._video(str(f), False, False, False)._repr_html_()
            + sc_magic._video(str(f), False, False, True)._repr_html_())
    assert page.count("::-webkit-media-controls-panel") == 2
    assert page.count("invert(1)") == 1


def test_responsive_still_styles_the_video_element(tmp_path):
    f = tmp_path / "v.mp4"
    f.write_bytes(b"\x00")
    assert sc_magic.RESPONSIVE_STYLE not in _tag(
        sc_magic._video(str(f), False, False)._repr_html_())
    tag = _tag(sc_magic._video(str(f), False, True)._repr_html_())
    assert sc_magic.RESPONSIVE_STYLE in tag and "controls" in tag


def test_light_controls_auto_detects_from_the_frame_background():
    """Unset, the right variant comes from the frame's own resolved
    background — so the shipped light theme and --style monokai both come out
    right with no flag at all."""
    auto = sc_magic._light_controls_for
    assert auto("numpy", None, None, None) is False          # light frame
    assert auto("monokai", None, None, None) is True         # dark frame
    assert auto("monokai", "#1F1F1F", None, None) is True
    assert auto("github-dark", None, None, None) is True
    # An explicit value always wins over the detection.
    assert auto("numpy", None, None, True) is True
    assert auto("monokai", None, None, False) is False


def test_light_controls_auto_detection_survives_a_bad_style():
    """A bad --style is reported by resolve_style_args; picking a glyph colour
    must not raise a second, confusing error on top of it."""
    assert sc_magic._light_controls_for("no-such-style", None, None, None) is False


def test_cell_magic_passes_light_controls_through(ip, tmp_path, monkeypatch):
    seen = {}
    real = sc_magic._video

    def spy(out_path, embed, responsive, light_controls=False):
        seen["light"] = light_controls
        return real(out_path, embed, responsive, light_controls)

    monkeypatch.setattr(sc_magic, "_video", spy)
    cell = "x = 1  #: one\n"

    ip.run_cell(f"%%snippet-cast -o {tmp_path / 'a.mp4'} --tts silent -q\n{cell}")
    assert seen["light"] is False                       # auto: light theme

    ip.run_cell(f"%%snippet-cast -o {tmp_path / 'b.mp4'} --tts silent -q "
                f"--style monokai\n{cell}")
    assert seen["light"] is True                        # auto: dark theme

    ip.run_cell(f"%%snippet-cast -o {tmp_path / 'c.mp4'} --tts silent -q "
                f"--light-controls\n{cell}")
    assert seen["light"] is True                        # explicit override

    ip.run_cell(f"%%snippet-cast -o {tmp_path / 'd.mp4'} --tts silent -q "
                f"--style monokai --no-light-controls\n{cell}")
    assert seen["light"] is False

    monkeypatch.setenv("SNIPPET_CAST_LIGHT_CONTROLS", "1")
    ip.run_cell(f"%%snippet-cast -o {tmp_path / 'e.mp4'} --tts silent -q\n{cell}")
    assert seen["light"] is True


def test_strip_directives_removes_whole_quarto_option_lines():
    """`#|` lines configure Quarto, not the snippet — they must not be typed
    out, narrated or highlighted. Whole lines go rather than being blanked:
    a blank row would take up height in every frame (invariant 12)."""
    assert sc_magic._strip_directives(
        "#| fig-column: margin\nx = 1  #: one\n") == "x = 1  #: one\n"
    assert sc_magic._strip_directives(
        "  #| echo: false\nx = 1  #: one\n") == "x = 1  #: one\n"
    assert sc_magic._strip_directives(
        "#| a: 1\n#| b: 2\nx = 1  #: one\n") == "x = 1  #: one\n"


def test_strip_directives_leaves_everything_else_alone():
    """Found via tokenize, not a regex (critical invariant 5): a `#|` inside a
    string literal is not a comment, and a trailing one is not a whole line."""
    trailing = "x = 1  #| not a directive\n"
    assert sc_magic._strip_directives(trailing) == trailing

    in_string = 'sql = """\n#| not a directive\n"""\nx = 1  #: one\n'
    assert sc_magic._strip_directives(in_string) == in_string

    plain = "x = 1  #: one\n"
    assert sc_magic._strip_directives(plain) is plain   # untouched, not rebuilt


def test_cell_magic_drops_directives_before_rendering(ip, tmp_path, monkeypatch):
    """End to end: the directive must not become a beat or a code row."""
    monkeypatch.chdir(tmp_path)
    seen = {}
    real = sc_magic.build

    def spy(source_path, *a, **kw):
        seen["source"] = open(source_path).read()
        return real(source_path, *a, **kw)

    monkeypatch.setattr(sc_magic, "build", spy)
    ip.run_cell("%%snippet-cast --tts silent -q\n"
                "#| fig-column: margin\n"
                "x = 1  #: one\n")

    assert seen["source"] == "x = 1  #: one\n"


def test_cell_output_path_is_unique_per_cell_and_stable_across_reruns(tmp_path, monkeypatch):
    """Every cell used to default to out.mp4, so in a notebook of N cells the
    first N-1 videos were silently overwritten by the last. Hashing the cell
    fixes that — and, unlike a random name, re-running an unchanged cell
    reuses its file instead of leaving another orphan behind."""
    monkeypatch.chdir(tmp_path)
    a = sc_magic._cell_output_path("--tts silent", "x = 1  #: one\n")
    a_again = sc_magic._cell_output_path("--tts silent", "x = 1  #: one\n")
    b = sc_magic._cell_output_path("--tts silent", "y = 2  #: two\n")
    c = sc_magic._cell_output_path("--tts silent --typing", "x = 1  #: one\n")

    assert a == a_again          # same cell -> same file, no accumulation
    assert a != b                # different body -> different file
    assert a != c                # different flags -> different file too
    assert os.path.dirname(a) == sc_magic.CACHE_DIR


def test_cell_output_dir_ignores_itself_in_git(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sc_magic._cell_output_path("", "x = 1  #: one\n")
    assert (tmp_path / sc_magic.CACHE_DIR / ".gitignore").read_text().strip() == "*"


def test_cell_magic_writes_into_the_cache_dir_by_default(ip, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ip.run_cell("%%snippet-cast --tts silent -q\nx = 1  #: one\n")

    made = list((tmp_path / sc_magic.CACHE_DIR).glob("*.mp4"))
    assert len(made) == 1
    # ...and nothing was dropped in the student's own folder.
    assert not list(tmp_path.glob("*.mp4"))


@pytest.mark.parametrize("flag", ["-o mine.mp4", "-n mine", "-d subdir"])
def test_explicit_output_still_bypasses_the_cache_dir(ip, tmp_path, monkeypatch, flag):
    monkeypatch.chdir(tmp_path)
    ip.run_cell(f"%%snippet-cast --tts silent -q {flag}\nx = 1  #: one\n")

    assert list(tmp_path.glob("**/*.mp4"))                 # something was written
    assert not (tmp_path / sc_magic.CACHE_DIR).exists()    # but not in the cache


def test_env_vars_set_to_their_defaults_express_no_preference(ip, tmp_path, monkeypatch):
    """A project-wide activation env (pixi's [tool.pixi.activation.env], a
    shell profile) may materialise EVERY SNIPPET_CAST_* var at its default.
    That must behave exactly like setting none of them — it broke three ways
    at once: --manual-audio-dir errored out and rendered nothing, NAME/
    OUTPUT_DIR put every cell back to overwriting one out.mp4, and SCREENFLOW
    was a hard error because 'none' had no meaning."""
    monkeypatch.chdir(tmp_path)
    for k, v in (("SNIPPET_CAST_MANUAL_AUDIO_DIR", "./manual_audio"),
                 ("SNIPPET_CAST_NAME", "out"),
                 ("SNIPPET_CAST_OUTPUT_DIR", "."),
                 ("SNIPPET_CAST_SCREENFLOW", "none"),
                 ("SNIPPET_CAST_LIGHT_CONTROLS", "auto"),
                 ("SNIPPET_CAST_TTS", "silent")):
        monkeypatch.setenv(k, v)

    result = ip.run_cell("%%snippet-cast -q\nx = 1  #: one\n")

    assert result.success
    assert len(list((tmp_path / sc_magic.CACHE_DIR).glob("*.mp4"))) == 1
    assert not list(tmp_path.glob("*.mp4"))     # not back to out.mp4


def test_light_controls_env_var_accepts_auto(monkeypatch):
    """So the variable can sit in an activation env without forcing a choice."""
    for value in ("auto", "AUTO", ""):
        monkeypatch.setenv("SNIPPET_CAST_LIGHT_CONTROLS", value)
        assert sc_magic._light_controls_for("numpy", None, None, None) is False
        assert sc_magic._light_controls_for("monokai", None, None, None) is True


def test_output_env_vars_also_count_as_explicit(ip, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SNIPPET_CAST_NAME", "fromenv")   # differs from "out"
    ip.run_cell("%%snippet-cast --tts silent -q\nx = 1  #: one\n")

    assert (tmp_path / "fromenv.mp4").exists()
    assert not (tmp_path / sc_magic.CACHE_DIR).exists()


def test_cell_magic_is_responsive_by_default(ip, tmp_path, monkeypatch):
    """The frame is sized to the snippet, so a wide line makes a wide video
    that overflows a Quarto column. Capping it never scales a small video UP,
    so it is only ever an improvement — hence on by default."""
    seen = {}
    real = sc_magic._video

    def spy(out_path, embed, responsive, light_controls=False):
        seen["responsive"] = responsive
        return real(out_path, embed, responsive, light_controls)

    monkeypatch.setattr(sc_magic, "_video", spy)
    cell = "x = 1  #: one\n"

    ip.run_cell(f"%%snippet-cast -o {tmp_path / 'a.mp4'} --tts silent -q\n{cell}")
    assert seen["responsive"] is True

    ip.run_cell(f"%%snippet-cast -o {tmp_path / 'b.mp4'} --tts silent -q --no-responsive\n{cell}")
    assert seen["responsive"] is False

    # The env var can turn it off too, and --responsive overrides that back on.
    monkeypatch.setenv("SNIPPET_CAST_RESPONSIVE", "0")
    ip.run_cell(f"%%snippet-cast -o {tmp_path / 'c.mp4'} --tts silent -q\n{cell}")
    assert seen["responsive"] is False
    ip.run_cell(f"%%snippet-cast -o {tmp_path / 'd.mp4'} --tts silent -q --responsive\n{cell}")
    assert seen["responsive"] is True


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
    # `any`, not `[-1]`: the finished video is itself an HTML object now (the
    # control-bar restyling needs a <style> block), so it lands last.
    assert any("recording — press Enter to stop." in o.data for o in html_objs)
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
