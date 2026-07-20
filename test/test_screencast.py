import shutil
import subprocess
from pathlib import Path

import pytest

from snippet_cast import build, export_script
from snippet_cast.screencast import (
    FONT_NAME,
    FONT_SIZE,
    Beat,
    _format_script,
    _mono_font_path,
    _parse_order,
    _two_pass_beats,
    build_beats,
    loop_body_ranges,
    order_markers,
    parse,
    split_narration,
    trace_run,
)

DATA = Path(__file__).parent / "data"
FIB = DATA / "fib.py"
LOOP = DATA / "loop.py"
TWOPASS = DATA / "twopass.py"


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


def test_parse_strips_narration_and_finds_markers():
    source = FIB.read_text()
    code_lines, markers = parse(source)

    assert len(code_lines) == len(source.splitlines())
    assert all("#:" not in line for line in code_lines)
    assert [m.line_no for m in markers] == [1, 2, 3, 4, 5, 6, 7]
    # the first marker is a comment-only intro line (no code on line 1)
    assert markers[0].has_code is False
    assert markers[1].has_code is True


def test_first_exec_beats_cover_every_marker():
    source = FIB.read_text()
    code_lines, markers = parse(source)
    steps = trace_run(source, str(FIB))
    beats = build_beats(code_lines, markers, steps, every=False)

    assert len(beats) == len(markers)
    # `result = fib(7)` runs, so its beat's state should include result=13
    result_beat = next(b for b in beats if b.highlight == 7)
    assert result_beat.state.get("result") == "13"


def test_every_exec_interpolates_and_suppresses_loop_exit_beat():
    source = LOOP.read_text()
    code_lines, markers = parse(source)
    steps = trace_run(source, str(LOOP))
    loop_ranges = loop_body_ranges(source)
    beats = build_beats(code_lines, markers, steps, every=True, loop_ranges=loop_ranges)

    header_beats = [b for b in beats if b.highlight == 3]
    assert [b.narration for b in header_beats] == [
        f"Iteration where i is {i}." for i in range(5)
    ]

    body_beats = [b for b in beats if b.highlight == 4]
    assert body_beats[-1].narration == "Add i, so total is now 10."


@pytest.mark.skipif(not _rendering_available(), reason="requires ffmpeg and a resolvable FONT_NAME")
def test_build_renders_silent_mp4(tmp_path):
    out = tmp_path / "out.mp4"
    build(str(FIB), str(out), tts="silent", subtitles=True)

    assert out.exists()
    assert out.stat().st_size > 0


def test_split_narration_no_slash_is_backward_compatible():
    assert split_narration("Loop n times; the counter itself is unused.") == (
        "", "Loop n times; the counter itself is unused.")


def test_split_narration_splits_on_first_slash_only():
    assert split_narration("write it / explain it / extra") == ("write it", "explain it / extra")
    assert split_narration(" leading and trailing / narration ") == ("leading and trailing", "narration")
    assert split_narration("only silent typing /") == ("only silent typing", "")
    assert split_narration("/ only walkthrough") == ("", "only walkthrough")


def test_two_pass_beats_pass1_has_no_state_or_highlight():
    source = TWOPASS.read_text()
    code_lines, markers = parse(source)
    steps = trace_run(source, str(TWOPASS))
    beats1, beats2 = _two_pass_beats(code_lines, markers, steps)

    assert len(beats1) == len(beats2) == len(markers)
    assert all(b.state == {} for b in beats1)
    # the fixture has an empty part1 and an empty part2 marker
    assert any(b.narration == "" for b in beats1)
    assert any(b.narration == "" for b in beats2)
    # pass 2 keeps real state/interpolation, exactly like single-pass mode
    result_beat = next(b for b in beats2 if b.highlight == 7)
    assert result_beat.state.get("result") == "6"


def test_format_script_dedups_and_marks_silent_beats():
    beats1 = [Beat(1, None, "hello", {}), Beat(2, 2, "", {})]
    beats2 = [Beat(1, None, "hello", {}), Beat(2, 2, "world", {})]

    lines = _format_script(beats1, beats2)

    assert any(line.startswith("001") and "hello" in line for line in lines)
    assert any("(silent)" in line for line in lines)
    assert any("(dup of #001)" in line for line in lines)
    assert any(line.startswith("002") and "world" in line for line in lines)


def test_export_script_matches_two_pass_beat_count():
    lines = export_script(str(TWOPASS))
    tagged = [l for l in lines if "[pass 1," in l or "[pass 2," in l]
    assert len(tagged) == 14  # 7 markers x 2 passes
    assert sum(1 for l in tagged if "[pass 1," in l) == 7
    assert sum(1 for l in tagged if "[pass 2," in l) == 7


def test_two_pass_rejects_every():
    with pytest.raises(SystemExit):
        export_script(str(TWOPASS), every=True)


def test_parse_order_strips_prefix_or_returns_none():
    assert _parse_order("3) Some text") == (3, "Some text")
    assert _parse_order("10)   Some text") == (10, "Some text")
    assert _parse_order("Some text") == (None, "Some text")
    assert _parse_order("") == (None, "")


def test_order_markers_defaults_to_source_order_when_unnumbered():
    source = FIB.read_text()
    _, markers = parse(source)
    out = order_markers(markers, [m.text for m in markers])
    assert [m.line_no for m in out] == [m.line_no for m in markers]
    assert [m.text for m in out] == [m.text for m in markers]


def test_order_markers_reorders_by_explicit_numbers():
    source = (
        "def fib(n):             #: 3) def line\n"
        "    a, b = 0, 1          #: 1) init line\n"
        "    for _ in range(n):   #: 2) loop line\n"
    )
    _, markers = parse(source)
    out = order_markers(markers, [m.text for m in markers])
    assert [m.line_no for m in out] == [2, 3, 1]
    assert [m.text for m in out] == ["init line", "loop line", "def line"]


def test_order_markers_rejects_mixed_numbering():
    source = (
        "def fib(n):    #: 1) def line\n"
        "    a = 1      #: init line\n"
    )
    _, markers = parse(source)
    with pytest.raises(SystemExit):
        order_markers(markers, [m.text for m in markers])


def test_build_beats_reveal_upto_never_shrinks_for_reordered_markers():
    source = (
        "def fib(n):             #: 3) def line\n"
        "    a = n                #: 1) init line\n"
        "    b = a + 1            #: 2) plus one line\n"
    )
    code_lines, markers = parse(source)
    steps = trace_run(source, "<reorder-test>")
    ordered = order_markers(markers, [m.text for m in markers])
    beats = build_beats(code_lines, ordered, steps, every=False)

    reveal = [b.reveal_upto for b in beats]
    assert reveal == sorted(reveal)              # non-decreasing, never shrinks
    assert [b.highlight for b in beats] == [2, 3, 1]
    assert reveal[-1] == 3                        # final beat has revealed everything


def test_two_pass_beats_supports_independent_per_pass_order():
    source = (
        "def counter(n):       #: 2) sig / whole thing\n"
        "    total = 0         #: 1) start / total is {total}\n"
        "    return total      #: 3) ret / return it\n"
    )
    code_lines, markers = parse(source)
    steps = trace_run(source, "<reorder-twopass-test>")
    beats1, beats2 = _two_pass_beats(code_lines, markers, steps)

    # pass 1 is explicitly reordered: line 2, then line 1, then line 3
    assert [b.highlight for b in beats1] == [2, 1, 3]
    # pass 2 has no numbers anywhere -> default top-to-bottom order
    assert [b.highlight for b in beats2] == [1, 2, 3]


def test_build_rejects_order_prefixes_with_every(tmp_path):
    src = tmp_path / "ordered.py"
    src.write_text(
        "def fib(n):             #: 3) def line\n"
        "    a = n                #: 1) init line\n"
        "    b = a + 1            #: 2) plus one line\n"
    )
    with pytest.raises(SystemExit):
        export_script(str(src), every=True)


@pytest.mark.skipif(not _rendering_available(), reason="requires ffmpeg and a resolvable FONT_NAME")
def test_build_renders_two_pass_silent_mp4(tmp_path):
    out = tmp_path / "out.mp4"
    build(str(TWOPASS), str(out), tts="silent", subtitles=True)

    assert out.exists()
    assert out.stat().st_size > 0


@pytest.mark.skipif(not _rendering_available(), reason="requires ffmpeg and a resolvable FONT_NAME")
def test_manual_backend_round_trip(tmp_path):
    lines = export_script(str(TWOPASS))
    numbered = [l for l in lines if l[:3].isdigit()]
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    for line in numbered:
        stem = line[:3]
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
             "-t", "1", str(audio_dir / f"{stem}.wav")],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    out = tmp_path / "manual.mp4"
    build(str(TWOPASS), str(out), tts="manual", manual_audio_dir=str(audio_dir))

    assert out.exists()
    assert out.stat().st_size > 0


@pytest.mark.skipif(not _rendering_available(), reason="requires ffmpeg and a resolvable FONT_NAME")
def test_manual_backend_missing_recording_errors(tmp_path):
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()  # empty — no recordings at all
    out = tmp_path / "manual.mp4"
    with pytest.raises(SystemExit):
        build(str(TWOPASS), str(out), tts="manual", manual_audio_dir=str(audio_dir))
