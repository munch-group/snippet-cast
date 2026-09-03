import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import snippet_cast.screencast as sc
from snippet_cast import build, export_script
from snippet_cast.screencast import (
    FPS,
    FONT_NAME,
    FONT_SIZE,
    PAD,
    TYPE_SPEED,
    Beat,
    BG_COLOR_NONE,
    BUILTIN_STYLES,
    DarkModernStyle,
    LightModernStyle,
    _env_default,
    _format_script,
    _mono_font_path,
    _narration_sequence,
    _parse_order,
    _two_pass_beats,
    build_beats,
    loop_body_ranges,
    make_pass1_code_clip,
    order_markers,
    parse,
    plan_canvas,
    resolve_env_defaults,
    resolve_footnotes,
    resolve_panel_args,
    resolve_output_path,
    resolve_style_args,
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


def test_build_beats_reveals_only_visited_lines_in_custom_order():
    source = (
        "def fib(n):             #: 3) def line\n"
        "    a = n                #: 1) init line\n"
        "    b = a + 1            #: 2) plus one line\n"
    )
    code_lines, markers = parse(source)
    steps = trace_run(source, "<reorder-test>")
    ordered = order_markers(markers, [m.text for m in markers])
    beats = build_beats(code_lines, ordered, steps, every=False)

    revealed = [b.revealed for b in beats]
    assert [b.highlight for b in beats] == [2, 3, 1]
    # each beat's revealed set only grows (a superset of the last), never shrinks
    assert all(revealed[i] <= revealed[i + 1] for i in range(len(revealed) - 1))
    # line 1 (an earlier, not-yet-visited source line) is NOT dragged along
    # just because line 2 -- a higher line number -- is revealed first
    assert revealed[0] == {2}
    assert revealed[1] == {2, 3}
    assert revealed[-1] == {1, 2, 3}               # final beat has revealed everything


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


def test_narration_sequence_numbers_dedups_and_flags_silent():
    beats1 = [Beat(1, None, "hello", {}), Beat(2, 2, "", {})]
    beats2 = [Beat(1, None, "hello", {}), Beat(2, 2, "world", {})]

    seq = list(_narration_sequence(beats1, beats2))

    assert [(pass_no, idx, number, dup_of) for pass_no, idx, _, number, dup_of in seq] == [
        (1, 0, 1, None),      # 'hello' -> #001
        (1, 1, None, None),   # silent
        (2, 0, None, 1),      # 'hello' again -> dup of #001
        (2, 1, 2, None),      # 'world' -> #002
    ]


def _scripted_input(responses):
    it = iter(responses)
    return lambda prompt="": next(it)


def test_record_narration_keep_record_delete_then_commits(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sc, "_default_input_device", lambda: "Fake Mic")

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    (audio_dir / "001.wav").write_bytes(b"old-recording")

    def fake_record(dest_wav, device_name, input_fn=input):
        Path(dest_wav).write_bytes(b"new-recording")
        return True

    # fib.py has 7 unique, non-silent markers -> beats 001-007:
    # 001: delete the pre-existing recording
    # 002: record a new take, accept it
    # 003-007: nothing exists yet, explicitly skip ('s' — a blank Enter
    #          isn't accepted there, see _decide_recording)
    responses = _scripted_input(["d", "r", "", "s", "s", "s", "s", "s"])

    ok = sc.record_narration(
        str(FIB), str(audio_dir), str(tmp_path / "out.mp4"),
        show_frame=False, build_after=False,
        input_fn=responses, record_fn=fake_record, play_fn=lambda path: None)

    assert ok is True
    assert not (audio_dir / "001.wav").exists()
    assert (audio_dir / "002.wav").read_bytes() == b"new-recording"
    assert not (audio_dir / "003.wav").exists()


@pytest.mark.skipif(not _rendering_available(), reason="requires ffmpeg and a resolvable FONT_NAME")
def test_record_narration_calls_custom_frame_fn(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sc, "_default_input_device", lambda: "Fake Mic")

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    shown = []

    def fake_frame_fn(path):
        shown.append(Path(path).read_bytes())  # capture content at call time

    responses = _scripted_input(["s"] * 7)  # fib.py: 7 beats, nothing exists -> skip each

    ok = sc.record_narration(
        str(FIB), str(audio_dir), str(tmp_path / "out.mp4"),
        show_frame=True, build_after=False,
        input_fn=responses, record_fn=lambda *a, **k: True, play_fn=lambda p: None,
        frame_fn=fake_frame_fn)

    assert ok is True
    assert len(shown) == 7  # one preview per beat
    assert all(len(png) > 0 for png in shown)  # each was a real, non-empty PNG


def test_record_narration_disables_show_frame_when_imgcat_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sc, "_default_input_device", lambda: "Fake Mic")
    monkeypatch.setattr(sc.shutil, "which", lambda name: None)  # imgcat not on PATH

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    responses = _scripted_input(["s"] * 7)

    ok = sc.record_narration(
        str(FIB), str(audio_dir), str(tmp_path / "out.mp4"),
        show_frame=True, build_after=False,  # no frame_fn given -> imgcat path
        input_fn=responses, record_fn=lambda *a, **k: True, play_fn=lambda p: None)

    assert ok is True  # missing imgcat degrades gracefully, doesn't abort the session
    assert "imgcat" in capsys.readouterr().out


def test_record_narration_retries_after_failed_take(tmp_path, monkeypatch):
    """Regression test: a record_fn that fails to produce audio (e.g. Enter
    races ffmpeg's own startup — reproduced manually, see _record_until_enter)
    must send the beat back to the main prompt, not crash the session."""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sc, "_default_input_device", lambda: "Fake Mic")

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()

    attempts = {"n": 0}

    def flaky_record(dest_wav, device_name, input_fn=input):
        attempts["n"] += 1
        if attempts["n"] == 1:
            return False  # simulates no file produced
        Path(dest_wav).write_bytes(b"good-take")
        return True

    # beat 001: 'r' fails -> back to main prompt -> 'r' succeeds -> accept
    # beats 002-007: nothing exists -> explicitly skip ('s')
    responses = _scripted_input(["r", "r", "", "s", "s", "s", "s", "s", "s"])

    ok = sc.record_narration(
        str(FIB), str(audio_dir), str(tmp_path / "out.mp4"),
        show_frame=False, build_after=False,
        input_fn=responses, record_fn=flaky_record, play_fn=lambda path: None)

    assert ok is True
    assert attempts["n"] == 2
    assert (audio_dir / "001.wav").read_bytes() == b"good-take"


def test_record_narration_redo_stays_in_record_loop(tmp_path, monkeypatch):
    """Regression test: 'r' (redo) at the accept/redo prompt must record
    again immediately, not fall through to the outer keep/record/delete
    prompt — falling through there meant a plain Enter typed to confirm the
    redo was instead read as 'keep' at the OUTER prompt, silently discarding
    the just-recorded take. Reproduced in a real --record session: 2 beats
    recorded, only 1 change committed, the build then failed with a missing
    recording."""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sc, "_default_input_device", lambda: "Fake Mic")

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()

    attempts = {"n": 0}

    def fake_record(dest_wav, device_name, input_fn=input):
        attempts["n"] += 1
        Path(dest_wav).write_bytes(f"take-{attempts['n']}".encode())
        return True

    # beat 001: 'r' -> record -> 'r' (redo) -> record again -> '' (accept)
    # beats 002-007: nothing exists -> explicitly skip ('s')
    responses = _scripted_input(["r", "r", "", "s", "s", "s", "s", "s", "s"])

    ok = sc.record_narration(
        str(FIB), str(audio_dir), str(tmp_path / "out.mp4"),
        show_frame=False, build_after=False,
        input_fn=responses, record_fn=fake_record, play_fn=lambda path: None)

    assert ok is True
    assert attempts["n"] == 2  # the redo actually re-recorded
    assert (audio_dir / "001.wav").read_bytes() == b"take-2"  # the redo's take, committed


@pytest.mark.skipif(not _rendering_available(), reason="requires ffmpeg and a resolvable FONT_NAME")
def test_record_narration_build_after_does_not_retrace(tmp_path, monkeypatch):
    """Regression test: build_after=True must render from the beats the
    interactive session already built, not re-parse and re-run the
    snippet — a prior version called trace_run() (a full re-execution of
    the user's own code) a second time here, visible as the snippet's
    side effects (e.g. prints) happening twice per --record session."""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sc, "_default_input_device", lambda: "Fake Mic")

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()

    def fake_record(dest_wav, device_name, input_fn=input):
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
             "-t", "1", dest_wav],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True

    trace_calls = {"n": 0}
    real_trace_run = sc.trace_run

    def counting_trace_run(*a, **kw):
        trace_calls["n"] += 1
        return real_trace_run(*a, **kw)

    monkeypatch.setattr(sc, "trace_run", counting_trace_run)

    responses = _scripted_input(["r", ""] * 7)  # fib.py has 7 unique markers
    out = tmp_path / "out.mp4"

    ok = sc.record_narration(
        str(FIB), str(audio_dir), str(out),
        show_frame=False, build_after=True,
        input_fn=responses, record_fn=fake_record, play_fn=lambda path: None)

    assert ok is True
    assert trace_calls["n"] == 1
    assert out.exists()
    assert out.stat().st_size > 0


def test_record_narration_aborts_without_committing(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sc, "_default_input_device", lambda: "Fake Mic")

    audio_dir = tmp_path / "audio"

    def raise_interrupt(prompt=""):
        raise KeyboardInterrupt

    ok = sc.record_narration(
        str(FIB), str(audio_dir), str(tmp_path / "out.mp4"),
        show_frame=False, build_after=False,
        input_fn=raise_interrupt, record_fn=lambda *a, **k: None, play_fn=lambda path: None)

    assert ok is False
    assert list(audio_dir.iterdir()) == []


def test_record_narration_requires_macos(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(SystemExit):
        sc.record_narration(str(FIB), str(tmp_path / "audio"), str(tmp_path / "out.mp4"))


def test_decide_recording_rejects_blank_enter_when_nothing_exists(tmp_path, capsys):
    """Regression test: a beat with no existing recording must not be
    skippable by the same blank Enter that means 'keep' when a recording
    DOES exist — that was a silent way to end up with a beat build(tts=
    'manual') fails outright on. Blank Enter is re-prompted; only the
    explicit 's' skips."""
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    responses = _scripted_input(["", "", "s"])  # two rejected blanks, then explicit skip

    action, tmp_path_out = sc._decide_recording(
        1, "[pass 2, beat 1]", "some narration", str(audio_dir), str(tmp_path),
        "Fake Mic", input_fn=responses, record_fn=lambda *a, **k: True, play_fn=lambda p: None)

    assert action == "skip"
    assert tmp_path_out is None
    assert "won't skip it" in capsys.readouterr().out


def test_record_narration_skips_build_after_and_warns_when_recordings_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sc, "_default_input_device", lambda: "Fake Mic")

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    out = tmp_path / "out.mp4"

    def fake_record(dest_wav, device_name, input_fn=input):
        Path(dest_wav).write_bytes(b"take")
        return True

    # beat 001: record it; beats 002-007: explicitly skip (nothing exists)
    responses = _scripted_input(["r", "", "s", "s", "s", "s", "s", "s"])

    ok = sc.record_narration(
        str(FIB), str(audio_dir), str(out),
        show_frame=False, build_after=True,
        input_fn=responses, record_fn=fake_record, play_fn=lambda p: None)

    assert ok is True
    assert not out.exists()  # auto-build must not have been attempted
    output = capsys.readouterr().out
    assert "skipping the auto-build" in output
    assert "002, 003, 004, 005, 006, 007" in output


def test_env_default_types_against_fallback(monkeypatch):
    monkeypatch.delenv("SNIPPET_CAST_TTS", raising=False)
    assert _env_default("tts", "say") == "say"  # unset -> fallback

    monkeypatch.setenv("SNIPPET_CAST_TTS", "piper")
    assert _env_default("tts", "say") == "piper"

    monkeypatch.setenv("SNIPPET_CAST_PAUSE", "0.6")
    assert _env_default("pause", 0.0) == 0.6

    monkeypatch.setenv("SNIPPET_CAST_SUBTITLES", "1")
    assert _env_default("subtitles", False) is True
    monkeypatch.setenv("SNIPPET_CAST_SUBTITLES", "0")
    assert _env_default("subtitles", False) is False

    monkeypatch.setenv("SNIPPET_CAST_PAUSE", "not-a-number")
    with pytest.raises(SystemExit):
        _env_default("pause", 0.0)


def test_resolve_env_defaults_leaves_explicit_values_alone(monkeypatch):
    monkeypatch.setenv("SNIPPET_CAST_PAUSE", "9.0")

    class Args:
        pause = 0.5  # explicitly set (e.g. via CLI flag) — not the None sentinel

    args = Args()
    resolve_env_defaults(args, pause=0.0)
    assert args.pause == 0.5  # explicit value wins over the env var


def test_main_record_rejects_conflicting_tts(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["snippet-cast", str(FIB), "--record", "--tts", "say"])
    with pytest.raises(SystemExit) as excinfo:
        sc.main()
    assert "--record always uses the manual backend" in str(excinfo.value)


def test_main_record_defaults_manual_audio_dir_and_forces_tts_manual(tmp_path, monkeypatch):
    out = tmp_path / "out.mp4"
    calls = []

    def fake_record_narration(source_path, manual_audio_dir, out_path, **kw):
        calls.append(manual_audio_dir)
        Path(out_path).write_bytes(b"fake-mp4")
        return True

    monkeypatch.setattr(sc, "record_narration", fake_record_narration)
    monkeypatch.setattr(
        sys, "argv",
        ["snippet-cast", str(FIB), "-o", str(out), "--record", "--no-frame"])

    sc.main()

    assert calls == [sc.MANUAL_AUDIO_DIR_DEFAULT]


def test_resolve_output_path_prefers_explicit_output(tmp_path):
    explicit = str(tmp_path / "explicit.mp4")
    assert resolve_output_path(explicit, str(tmp_path / "unused"), "unused") == explicit


def test_resolve_output_path_builds_from_dir_and_name_and_creates_dir(tmp_path):
    out_dir = tmp_path / "videos"
    path = resolve_output_path(None, str(out_dir), "myvideo")
    assert path == str(out_dir / "myvideo.mp4")
    assert out_dir.is_dir()  # created even though nothing was rendered yet


@pytest.mark.skipif(not _rendering_available(), reason="requires ffmpeg and a resolvable FONT_NAME")
def test_make_pass1_code_clip_paces_by_typing_speed_not_narration_length(tmp_path):
    """Regression test: --typing-speed previously had zero effect whenever
    pass 1 had real narration, since frame count was sized entirely to the
    narration's duration (spread evenly across it). Now the reveal itself is
    paced by typing_speed frames, and a longer narration only pads a held
    final frame — verified by checking the padded frames are byte-identical
    copies of the last *typed* frame, and that typing itself progressed."""
    code_lines = ["def f(n):", "    return n"]
    beat = Beat(frozenset({1, 2}), 1, "test", {})
    cv = plan_canvas(code_lines, [beat], show_panel=True, subtitles=False)
    outdir = str(tmp_path)

    # A silent audio stand-in so make_typing_clip's ffmpeg call succeeds;
    # only frame count/content is under test here, not the muxed result.
    audio = str(tmp_path / "narration.wav")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
         "-t", "10", audio], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    make_pass1_code_clip(cv, code_lines, frozenset(), [1, 2], None,
                         duration=10.0, outdir=outdir, tag="t1", audio=audio,
                         typing_speed=0.035)

    frames_dir = Path(outdir) / "type_t1"
    total_chars = len("\n".join(code_lines))
    typing_n_frames = min(150, max(1, round(total_chars * 0.035 * FPS)))
    floor_frames = round(10.0 * FPS)
    assert len(list(frames_dir.glob("*.png"))) == floor_frames  # padded to the narration floor

    last_typed = (frames_dir / f"{typing_n_frames - 1:03d}.png").read_bytes()
    mid_pad = (frames_dir / f"{typing_n_frames + 10:03d}.png").read_bytes()
    last_pad = (frames_dir / f"{floor_frames - 1:03d}.png").read_bytes()
    assert last_typed == mid_pad == last_pad  # all padding is the held, fully-typed frame

    first_frame = (frames_dir / "000.png").read_bytes()
    assert first_frame != last_typed  # typing actually progressed, not stretched thin


@pytest.mark.skipif(not _rendering_available(), reason="requires ffmpeg and a resolvable FONT_NAME")
def test_build_two_pass_pause_applies_to_both_passes_without_trailing_pause(tmp_path):
    """Regression test: --pause previously only had an effect in pass 2's
    loop — pass 1 had no pause logic at all, and later still had no gap at
    the pass-1-to-pass-2 seam. Uses a minimal 2-marker snippet, both markers
    narrated in both passes, so the gap count is unambiguous by construction:
    1 internal gap within pass 1 (between its 2 beats) + 1 at the seam
    between the passes + 1 within pass 2 = 3 gaps total, none after the very
    last beat of the whole video. pause=P adds exactly 3*P s vs. pause=0."""
    src = tmp_path / "two_beats.py"
    src.write_text(
        "print(1) #: one / one narrated\n"
        "print(2) #: two / two narrated\n"
    )
    out0 = tmp_path / "pause0.mp4"
    out2 = tmp_path / "pause2.mp4"
    build(str(src), str(out0), tts="silent", pause=0.0)
    build(str(src), str(out2), tts="silent", pause=2.0)

    d0 = sc.probe_duration(str(out0))
    d2 = sc.probe_duration(str(out2))
    assert round(d2 - d0, 1) == 6.0  # exactly 3 gaps * 2.0s — no more, no fewer


def _fixed_duration_synth(duration):
    """A stub synth(text, out) -> path that ignores `text` and always
    returns a silent clip of exactly `duration` seconds — isolates
    _synth_with_pauses()'s splitting/stitching from any real backend's own
    timing model (e.g. synth_silent's word-count floor)."""
    def synth(text, out):
        path = out + ".wav"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
             "-t", f"{duration}", path],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return path
    return synth


def test_synth_with_pauses_ignores_single_period(tmp_path):
    calls = []

    def synth(text, out):
        calls.append(text)
        return "unused"

    result = sc._synth_with_pauses(synth, "Hello. World.", str(tmp_path), "t")
    assert calls == ["Hello. World."]  # a lone '.' is not a pause marker
    assert result == "unused"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="requires ffmpeg")
def test_synth_with_pauses_two_periods_add_0_2s(tmp_path):
    audio = sc._synth_with_pauses(_fixed_duration_synth(1.0), "Hello.. world",
                                  str(tmp_path), "t")
    assert sc.probe_duration(audio) == pytest.approx(1.0 + 0.2 + 1.0, abs=0.05)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="requires ffmpeg")
def test_synth_with_pauses_four_periods_add_0_4s(tmp_path):
    audio = sc._synth_with_pauses(_fixed_duration_synth(1.0), "Hello.... world",
                                  str(tmp_path), "t")
    assert sc.probe_duration(audio) == pytest.approx(1.0 + 0.4 + 1.0, abs=0.05)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="requires ffmpeg")
def test_synth_with_pauses_leading_and_trailing_markers(tmp_path):
    """A run at the very start/end of the text has no speech on that side —
    only the silence for it should be produced, no empty-string synth call."""
    calls = []

    def synth(text, out):
        calls.append(text)
        return _fixed_duration_synth(1.0)(text, out)

    audio = sc._synth_with_pauses(synth, "..Wait for it", str(tmp_path), "t")
    assert calls == ["Wait for it"]
    assert sc.probe_duration(audio) == pytest.approx(0.2 + 1.0, abs=0.05)


def test_cached_synth_pause_mode_none_calls_synth_once_unmodified(tmp_path):
    """The manual backend (pause_mode="none") must get exactly one synth()
    call per beat regardless of '..' markers — splitting would consume more
    than one numbered recording and desync --tts manual's file order."""
    calls = []

    def synth(text, out):
        calls.append(text)
        return f"{out}.wav"

    sc._cached_synth(synth, {}, "Hello.. world", str(tmp_path), "001", pause_mode="none")
    assert calls == ["Hello.. world"]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="requires ffmpeg")
def test_cached_synth_pause_mode_split_splits_on_marker(tmp_path):
    calls = []

    def synth(text, out):
        calls.append(text)
        return _fixed_duration_synth(0.5)(text, out)

    sc._cached_synth(synth, {}, "Hello.. world", str(tmp_path), "001")
    assert calls == ["Hello", "world"]


def test_cached_synth_pause_mode_say_rewrites_markup_in_one_call(tmp_path):
    calls = []

    def synth(text, out):
        calls.append(text)
        return f"{out}.wav"

    sc._cached_synth(synth, {}, "Hello.. world", str(tmp_path), "001", pause_mode="say")
    assert calls == ["Hello[[slnc 400]] world"]


def test_say_emphasis_markup_flanks_all_caps_run():
    assert (sc._say_emphasis_markup("Please NEVER DO THAT AGAIN")
            == "Please [[emph +]] NEVER DO THAT AGAIN [[emph -]]")


def test_say_emphasis_markup_flanks_single_all_caps_word():
    assert sc._say_emphasis_markup("STOP now") == "[[emph +]] STOP [[emph -]] now"


def test_say_emphasis_markup_ignores_mixed_case_word():
    text = "The IDentifier stays untouched"
    assert sc._say_emphasis_markup(text) == text  # no partial "ID" match


def test_say_emphasis_markup_ignores_lone_single_letter():
    text = "I am here"
    assert sc._say_emphasis_markup(text) == text  # "I" alone doesn't count


def test_say_emphasis_markup_noop_without_all_caps():
    text = "Nothing shouted here."
    assert sc._say_emphasis_markup(text) == text


def test_say_markup_combines_pause_and_emphasis():
    assert (sc._say_markup("Wait.. NEVER DO THAT")
            == "Wait[[slnc 400]] [[emph +]] NEVER DO THAT [[emph -]]")


@pytest.mark.skipif(not _rendering_available(), reason="requires ffmpeg and a resolvable FONT_NAME")
def test_manual_backend_unaffected_by_inline_pause_markers(tmp_path):
    """Regression test: a manual-backend beat's narration containing '..'
    must still consume exactly one numbered recording, same as any other
    beat — pause-splitting is a real-speech-backend-only feature."""
    src = tmp_path / "paused.py"
    src.write_text(
        "a = 1 #: First we set a.. then keep going.\n"
        "b = 2 #: Now set b.\n"
    )
    lines = export_script(str(src))
    numbered = [l for l in lines if l[:3].isdigit()]
    assert len(numbered) == 2  # one recording per beat, '..' notwithstanding

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    for line in numbered:
        stem = line[:3]
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
             "-t", "1", str(audio_dir / f"{stem}.wav")],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    out = tmp_path / "manual.mp4"
    build(str(src), str(out), tts="manual", manual_audio_dir=str(audio_dir))

    assert out.exists()
    assert out.stat().st_size > 0


# ---------------------------------------------------------------------------
# --style / --bg-color (and their SNIPPET_CAST_* env vars / build() kwargs)
# ---------------------------------------------------------------------------
def test_resolve_style_args_accepts_pygments_name_builtin_key_and_class():
    assert resolve_style_args("monokai", "#1F1F1F") == ("monokai", "#1F1F1F", None)
    assert resolve_style_args("dark-modern", "#1F1F1F") == \
        ("dark-modern", "#1F1F1F", None)
    # A Style subclass passed programmatically is handed straight through —
    # only strings are name-checked.
    assert resolve_style_args(LightModernStyle, "#FFFFFF")[0] is LightModernStyle


def test_resolve_style_args_none_keyword_means_the_styles_own_background():
    """'none' is the CLI/env spelling of the Python API's bg_color=None —
    the only way to express "no override" where only strings can be passed."""
    assert resolve_style_args("monokai", BG_COLOR_NONE)[1] is None
    assert resolve_style_args("monokai", "NONE")[1] is None   # case-insensitive


def test_resolve_style_args_rejects_unknown_style_listing_valid_names():
    with pytest.raises(ValueError) as e:
        resolve_style_args("no-such-style", "#1F1F1F")
    assert "no-such-style" in str(e.value)
    assert "monokai" in str(e.value) and "dark-modern" in str(e.value)


@pytest.mark.parametrize("bad", ["red", "1F1F1F", "#abc", "#12345g", "#1F1F1F1F"])
def test_resolve_style_args_rejects_non_rrggbb_colors(bad):
    """Restricted to '#rrggbb' even though PIL would accept more, because
    _is_light() picks caption colors by slicing those exact six hex digits."""
    with pytest.raises(ValueError):
        resolve_style_args("monokai", bad)


def test_resolve_style_applies_bg_override_without_touching_the_base_style():
    """The override is a subclass, so a shared registered style is never
    mutated for anything else in the process."""
    base = sc.get_style_by_name("monokai")
    resolved = sc._resolve_style("monokai", "#123456")
    assert resolved.background_color == "#123456"
    assert base.background_color == "#272822"
    # Same syntax colors — only the background is overridden.
    assert resolved.styles == base.styles


def test_resolve_style_none_bg_keeps_the_styles_own_background():
    assert sc._resolve_style("monokai", None).background_color == "#272822"
    assert sc._resolve_style("dark-modern", None).background_color == \
        DarkModernStyle.background_color


def test_resolve_style_unset_bg_falls_back_to_the_global(monkeypatch):
    """_USE_DEFAULT ("caller said nothing") must stay distinct from None
    ("caller asked for the style's own background")."""
    monkeypatch.setattr(sc, "BG_COLOR", "#ABCDEF")
    assert sc._resolve_style("monokai").background_color == "#ABCDEF"
    assert sc._resolve_style("monokai", None).background_color == "#272822"


def test_style_env_vars_resolve_like_every_other_option(monkeypatch):
    monkeypatch.setenv("SNIPPET_CAST_STYLE", "nord")
    monkeypatch.setenv("SNIPPET_CAST_BG_COLOR", BG_COLOR_NONE)

    class Args:
        style = None
        bg_color = None

    args = resolve_env_defaults(Args(), style="monokai", bg_color="#1F1F1F")
    assert (args.style, args.bg_color) == ("nord", BG_COLOR_NONE)
    assert resolve_style_args(args.style, args.bg_color) == ("nord", None, None)


def test_explicit_style_arg_beats_the_env_var(monkeypatch):
    monkeypatch.setenv("SNIPPET_CAST_STYLE", "nord")

    class Args:
        style = "dracula"   # explicitly passed, not the None sentinel
        bg_color = "#000000"

    assert resolve_env_defaults(Args(), style="monokai", bg_color="#1F1F1F").style \
        == "dracula"


@pytest.mark.skipif(not _rendering_available(), reason="requires ffmpeg and a resolvable FONT_NAME")
@pytest.mark.parametrize("style,bg_color,expected", [
    ("monokai", "#1F1F1F", "#1F1F1F"),        # override wins over the style
    ("monokai", None, "#272822"),             # style's own background
    ("dark-modern", None, "#1F1F1F"),         # a BUILTIN_STYLES key by name
])
def test_plan_canvas_and_code_frame_share_one_background(style, bg_color, expected):
    """Both consumers of the style — the canvas fill and pygments' own code
    image — must resolve the SAME background, or the code renders as a
    differently-colored rectangle pasted onto the canvas."""
    beat = Beat(frozenset({1}), 1, "n", {})
    cv = plan_canvas(["x = 1"], [beat], show_panel=False, subtitles=False,
                     style=style, bg_color=bg_color)
    assert cv.bg == expected
    code_img = sc._render_code("x = 1", hl_lines=[], style=cv.style)
    r, g, b = (int(expected[i:i + 2], 16) for i in (1, 3, 5))
    assert code_img.getpixel((code_img.width - 1, code_img.height - 1)) == (r, g, b)


@pytest.mark.skipif(not _rendering_available(), reason="requires ffmpeg and a resolvable FONT_NAME")
def test_light_style_gets_readable_caption_colors():
    """_is_light() runs on whichever background actually wins, so a light
    style only gets light-appropriate caption colors when the dark BG_COLOR
    default isn't overriding it."""
    beat = Beat(frozenset({1}), 1, "n", {})
    light = plan_canvas(["x = 1"], [beat], show_panel=False, subtitles=True,
                        style="light-modern", bg_color=None)
    assert (light.cap_fg, light.cap_rule) == (sc.COL_CAPTION_LIGHT, sc.COL_RULE_LIGHT)
    dark = plan_canvas(["x = 1"], [beat], show_panel=False, subtitles=True,
                       style="light-modern", bg_color="#1F1F1F")
    assert (dark.cap_fg, dark.cap_rule) == (sc.COL_CAPTION, sc.COL_RULE)


@pytest.mark.skipif(not _rendering_available(), reason="requires ffmpeg and a resolvable FONT_NAME")
def test_build_honors_style_and_bg_color_end_to_end(tmp_path):
    src = tmp_path / "s.py"
    src.write_text("x = 1 #: Assign one.\n")
    out = tmp_path / "styled.mp4"
    build(str(src), str(out), tts="silent", style="light-modern", bg_color=None)

    frame = tmp_path / "f.png"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(out),
                    "-frames:v", "1", str(frame)], check=True)
    from PIL import Image
    r, g, b = Image.open(frame).convert("RGB").getpixel((2, 2))
    # LightModernStyle is #FFFFFF; h264's yuv420p round-trip shifts a level
    # or two, so assert "unmistakably light" rather than an exact triple.
    assert min(r, g, b) > 240


def test_builtin_styles_are_not_registered_with_pygments():
    """The reason BUILTIN_STYLES exists at all: get_style_by_name() can't
    find these, so without the dict they'd be unreachable from --style."""
    for name in BUILTIN_STYLES:
        with pytest.raises(Exception):
            sc.get_style_by_name(name)


# ---------------------------------------------------------------------------
# Footnote narration ('#: N)' reference + a numbered body elsewhere)
# ---------------------------------------------------------------------------
FOOTNOTE = DATA / "footnote.py"


def test_resolve_footnotes_pastes_body_and_drops_the_block():
    src = ("x = 2  #: 1)\n"
           "y = 3  #: 2)\n"
           "\n"
           "#: 1) Body one.\n"
           "#: 2) Body two.\n")
    assert resolve_footnotes(src) == "x = 2  #: 1) Body one.\ny = 3  #: 2) Body two.\n"


def test_resolve_footnotes_unwraps_continuation_lines_into_one_line():
    """The point of the feature: a body wrapped over plain '#' lines to stay
    inside the right margin becomes a single narration string."""
    src = ("x = 2  #: 1)\n"
           "\n"
           "#: 1) One two\n"
           "# three four\n"
           "#   five.\n")
    assert resolve_footnotes(src) == "x = 2  #: 1) One two three four five.\n"


def test_resolve_footnotes_does_not_renumber_the_walkthrough_pass():
    """Regression: the label must NOT be re-attached to the '/' side. Doing
    so silently made the walkthrough pass numbered, so a single footnote in
    an otherwise walkthrough-unnumbered file tripped order_markers()'
    all-or-none check (see the mixing test below)."""
    src = "x = 2  #: 1)\n\n#: 1) Writing. / Walkthrough.\n"
    assert resolve_footnotes(src) == "x = 2  #: 1) Writing. / Walkthrough.\n"


def test_footnote_body_is_appended_to_the_references_own_text_per_pass():
    """The body is pasted at the END of whatever text the first occurrence
    already has, joined per pass so a '/' on either side keeps its meaning."""
    src = "x = 2  #: 1) Head one. / Head two.\n\n#: 1) Body one. / Body two.\n"
    assert resolve_footnotes(src) == \
        "x = 2  #: 1) Head one. Body one. / Head two. Body two.\n"


def test_footnote_mixes_with_single_occurrence_order_prefixes(tmp_path):
    """The reported failure: a two-pass file numbering only its writing pass,
    with most lines using the plain one-occurrence 'N)' prefix and ONE line
    using a two-occurrence footnote. Every pass-1 text must come out numbered
    and every pass-2 text unnumbered — no all-or-none mix in either."""
    src = tmp_path / "mixed.py"
    src.write_text(
        "#: 0) Intro. / Trace it.\n"
        "def fib(n):     #: 2) Names it. / Captures n.\n"
        "    return n    #: 3) / Returns n.\n"
        "\n"
        "assert fib(7) == 7  #: 1)\n"
        "\n"
        "#: 1) Always write the test first. / Call it with seven.\n")
    code_lines, markers = parse(resolve_footnotes(src.read_text()))
    passes = [split_narration(m.text) for m in markers]
    assert all(_parse_order(p1)[0] is not None for p1, _ in passes)
    assert all(_parse_order(p2)[0] is None for _, p2 in passes)
    # ...and it actually builds, in footnote-number order for pass 1.
    beats1, beats2 = _two_pass_beats(code_lines, markers, [])
    assert [b.narration for b in beats1][:2] == \
        ["Intro.", "Always write the test first."]
    assert [b.narration for b in beats2][0] == "Trace it."


def test_resolve_footnotes_single_pass_body_gains_no_separator():
    src = "x = 2  #: 1)\n\n#: 1) Just one pass.\n"
    assert sc.TWO_PASS_SEP not in resolve_footnotes(src)


def test_footnote_label_orders_the_pass_it_is_numbered_in():
    """The label keeps its 'N)' playback-order meaning, and — like any order
    prefix — that is PER PASS: it lands on the writing side here, so only
    that pass reorders. Number the walkthrough side inside the body if you
    want it ordered too (exactly as when writing the text inline)."""
    src = ("x = 2  #: 2)\n"
           "y = 3  #: 1)\n"
           "\n"
           "#: 1) First write. / First walk.\n"
           "#: 2) Second write. / Second walk.\n")
    code_lines, markers = parse(resolve_footnotes(src))
    beats1, beats2 = _two_pass_beats(code_lines, markers, [])
    assert [b.narration for b in beats1] == ["First write.", "Second write."]
    assert [b.narration for b in beats2] == ["Second walk.", "First walk."]
    # ...and the reordered beat still reveals its own source line, not y's.
    assert beats1[0].highlight == 2   # footnote 1 sits on line 2 (y = 3)


@pytest.mark.parametrize("src", [
    "x = 1  #: Plain narration.\n",                        # no numbering at all
    "x = 1  #: 2) Second.\ny = 2  #: 1) First.\n",          # legacy order prefixes
    "#: 1) A numbered intro line.\nx = 1  #: 2) Then this.\n",
    "x = 1  #: 1)\n",                                      # a lone numbered line
])
def test_resolve_footnotes_leaves_non_footnote_sources_byte_identical(src, capsys):
    """Strictly opt-in: substitution needs BOTH a reference and a matching
    definition, so nothing that predates the feature can change meaning."""
    assert resolve_footnotes(src) == src


def test_resolve_footnotes_ignores_a_marker_inside_a_string_literal(capsys):
    """Critical invariant 5 — comments are found with tokenize, never a
    regex, so a '#:' in a string is not a footnote reference."""
    src = 's = "look  #: 1)"\nz = 1  #: 1)\n\n#: 1) Real body.\n'
    assert resolve_footnotes(src) == 's = "look  #: 1)"\nz = 1  #: 1) Real body.\n'


def test_resolve_footnotes_rejects_a_label_used_three_times():
    with pytest.raises(SystemExit) as e:
        resolve_footnotes("a = 1  #: 1)\n\n#: 1) One.\n#: 1) Again.\n")
    assert "appears 3 times" in str(e.value)


def test_resolve_footnotes_leaves_two_code_line_occurrences_alone(capsys):
    """Neither line can be deleted without deleting code, so the pair is left
    exactly as it was (a duplicate order number, as before footnotes)."""
    src = "a = 1  #: 1) One.\nb = 2  #: 1) Two.\n"
    assert resolve_footnotes(src) == src
    assert "two code lines" in capsys.readouterr().out


def test_single_occurrence_labels_are_untouched_and_silent(capsys):
    """A label used once is the old order prefix and stays exactly that —
    no substitution, and no note, however it's spelled."""
    src = ("#: 0) A numbered intro line. / And its walkthrough.\n"
           "a = 1  #: 1)\n"          # numbered, no narration of its own
           "b = 2  #: 9) Orphan body text.\n"
           "\n"
           "#: 1) One.\n")           # this pairs with line 2 and IS merged
    out = resolve_footnotes(src)
    assert out.splitlines()[0] == "#: 0) A numbered intro line. / And its walkthrough."
    assert "b = 2  #: 9) Orphan body text." in out
    assert "a = 1  #: 1) One." in out
    assert capsys.readouterr().out == ""


def test_footnote_body_may_start_on_a_continuation_line():
    """Occurrence counting — not "the body must start on the '#:' line" —
    is what disambiguates now, so a bare second '#: N)' can carry its whole
    body on the wrapped lines beneath it."""
    src = "a = 1  #: 1)\n\n#: 1)\n# the body\n# continues here.\n"
    assert resolve_footnotes(src) == "a = 1  #: 1) the body continues here.\n"


def test_resolve_footnotes_trims_the_blank_lines_the_block_leaves_behind():
    """plan_canvas() sizes every frame from the full code and _render_code
    keeps blank rows (invariant 12), so a leftover trailing blank would add
    dead height to the whole video."""
    src = "a = 1  #: 1)\n\n\n#: 1) One.\n"
    assert resolve_footnotes(src) == "a = 1  #: 1) One.\n"


def test_resolve_footnotes_handles_a_block_in_the_middle_of_the_file():
    src = ("a = 1  #: 1)\n"
           "#: 1) One.\n"
           "b = 2  #: 2)\n"
           "#: 2) Two.\n")
    assert resolve_footnotes(src) == "a = 1  #: 1) One.\nb = 2  #: 2) Two.\n"


def test_footnote_body_may_sit_above_the_line_it_narrates():
    """Whichever occurrence is on a line of its own supplies the body, so a
    block written above the code works as well as one below."""
    src = "#: 1) The body.\na = 1  #: 1)\n"
    assert resolve_footnotes(src) == "a = 1  #: 1) The body.\n"


def test_footnote_body_keeps_interpolation_and_pause_markers():
    """The body is ordinary narration text after substitution — nothing about
    {var} interpolation or '..' inline pauses is special-cased."""
    src = "a = 1  #: 1)\n\n#: 1) a is {a}.. and that is all.\n"
    assert resolve_footnotes(src) == "a = 1  #: 1) a is {a}.. and that is all.\n"


def test_footnotes_reach_beats_through_the_shared_preamble(tmp_path):
    """build()/export_script()/record_narration() all go through
    _build_all_beats(), so wiring the transform in there covers all three."""
    src = tmp_path / "fn.py"
    src.write_text("x = 2  #: 1)\n\n#: 1) The body text.\n")
    lines = list(export_script(str(src)))
    assert any("The body text." in ln for ln in lines)


def test_footnotes_are_rejected_with_every_like_any_order_prefix(tmp_path):
    src = tmp_path / "fn.py"
    src.write_text("x = 2  #: 1)\n\n#: 1) The body.\n")
    with pytest.raises(SystemExit) as e:
        sc._build_all_beats(str(src), trace=True, every=True)
    assert "first-exec" in str(e.value)


@pytest.mark.skipif(not _rendering_available(), reason="requires ffmpeg and a resolvable FONT_NAME")
def test_build_renders_the_footnote_sample(tmp_path):
    out = tmp_path / "footnote.mp4"
    build(str(FOOTNOTE), str(out), tts="silent", subtitles=True)

    assert out.exists() and out.stat().st_size > 0
    # The footnote block itself must not survive into the rendered code.
    code_lines, _ = parse(resolve_footnotes(FOOTNOTE.read_text()))
    assert not any(ln.lstrip().startswith("#:") for ln in code_lines)


# ---------------------------------------------------------------------------
# Highlight band padding (_tighten_highlight)
# ---------------------------------------------------------------------------
def _band_and_ink(code, line_no):
    """(band_box, ink_box) for `line_no`'s row: the highlight band's extent
    (pixels differing from the page background in the highlighted render) and
    the text's own extent (same, from an unhighlighted render)."""
    from PIL import Image, ImageChops

    style = sc._resolve_style()
    bg = style.background_color
    plain = sc._render_code(code, hl_lines=[])
    shown = sc._render_code(code, hl_lines=[line_no])
    rows = len(code.splitlines())
    line_h = plain.height / rows
    y0, y1 = round((line_no - 1) * line_h), round(line_no * line_h)

    def extent(img):
        crop = img.crop((0, y0, img.width, y1))
        return ImageChops.difference(
            crop, Image.new("RGB", crop.size, bg)).getbbox()

    return extent(shown), extent(plain)


HL_CODE = "total = 0\nfor i in range(5):\n    total = total + i\nprint(total)"


@pytest.mark.skipif(not _rendering_available(), reason="requires ffmpeg and a resolvable FONT_NAME")
@pytest.mark.parametrize("line_no", [1, 2, 3, 4])
def test_highlight_band_pads_left_and_right_by_hl_pad(line_no):
    """pygments draws the band across the WHOLE image, so out of the box the
    left padding is zero and the right is whatever's left over from the
    longest line. Every line must get HL_PAD on both sides instead —
    including line 3, which is indented, and line 3 again as the longest line
    (the band has to extend past pygments' own right edge there)."""
    band, ink = _band_and_ink(HL_CODE, line_no)
    assert ink[0] - band[0] == sc.HL_PAD      # left
    assert band[2] - ink[2] == sc.HL_PAD      # right


@pytest.mark.skipif(not _rendering_available(), reason="requires ffmpeg and a resolvable FONT_NAME")
def test_highlight_band_does_not_leak_into_neighbouring_rows():
    """ImageDraw.rectangle's bottom coordinate is INCLUSIVE and pygments
    passes `y + recth`, so its band is one row taller than the line box. Every
    repaint has to reach that row too, or a 1px full-width stripe of the old
    band survives under the highlighted line."""
    from PIL import ImageChops

    plain = sc._render_code(HL_CODE, hl_lines=[])
    shown = sc._render_code(HL_CODE, hl_lines=[2])
    changed = ImageChops.difference(plain, shown).getbbox()
    line_h = plain.height / len(HL_CODE.splitlines())
    assert changed[1] >= round(line_h)             # nothing above line 2
    assert changed[3] <= round(2 * line_h) + 1     # nothing below its band


@pytest.mark.skipif(not _rendering_available(), reason="requires ffmpeg and a resolvable FONT_NAME")
def test_unhighlighted_render_is_untouched_by_the_band_logic():
    """_tighten_highlight only runs when there's something to highlight, so a
    plain frame (every typing frame, and plan_canvas()'s measuring render)
    must come back exactly as pygments drew it, plus the side margins."""
    from PIL import Image, ImageChops

    plain = sc._render_code(HL_CODE, hl_lines=[])
    style = sc._resolve_style()
    hl = Image.new("RGB", plain.size, style.highlight_color)
    assert ImageChops.difference(plain, hl).getbbox() is not None  # no band at all
    # The margins are background, so the ink never reaches the image edge.
    ink = ImageChops.difference(
        plain, Image.new("RGB", plain.size, style.background_color)).getbbox()
    assert ink[0] >= sc.HL_PAD
    assert plain.width - ink[2] >= sc.HL_PAD


@pytest.mark.skipif(not _rendering_available(), reason="requires ffmpeg and a resolvable FONT_NAME")
def test_highlight_and_measuring_renders_agree_on_width():
    """plan_canvas() sizes the canvas from an UNhighlighted render while
    compose() draws highlighted ones, so the side margins must be added to
    both or the code column would be mismeasured (invariant 1)."""
    assert sc._render_code(HL_CODE, hl_lines=[]).size == \
        sc._render_code(HL_CODE, hl_lines=[2]).size


@pytest.mark.skipif(not _rendering_available(), reason="requires ffmpeg and a resolvable FONT_NAME")
def test_highlighting_a_blank_line_draws_no_band():
    """_visible_code() renders unrevealed lines as empty strings; a band with
    no text to wrap would just be a stray full-width stripe."""
    from PIL import ImageChops

    code = "x = 1\n\ny = 2"
    plain = sc._render_code(code, hl_lines=[])
    shown = sc._render_code(code, hl_lines=[2])
    assert ImageChops.difference(plain, shown).getbbox() is None


# ---------------------------------------------------------------------------
# --state-bg-color / --state-fg-color
# ---------------------------------------------------------------------------
def test_panel_colors_default_to_the_module_constants():
    """Not passing either flag must leave the panel exactly as it looked
    before they existed."""
    assert sc._panel_colors() == sc.PanelColors(
        bg=sc.PANEL_BG, header=sc.COL_HEADER, name=sc.COL_NAME, value=sc.COL_VALUE)


def test_state_bg_color_alone_leaves_the_text_colors_alone():
    colors = sc._panel_colors(state_bg="#0d1117")
    assert colors.bg == "#0d1117"
    assert (colors.header, colors.name, colors.value) == \
        (sc.COL_HEADER, sc.COL_NAME, sc.COL_VALUE)


def test_state_fg_color_sets_both_names_and_values():
    """One knob for "the text in the box", so it covers names and values
    both — the default green/off-white split needs COL_NAME/COL_VALUE."""
    colors = sc._panel_colors(state_fg="#9CDCFE")
    assert colors.name == colors.value == "#9CDCFE"
    assert colors.bg == sc.PANEL_BG


def test_state_fg_color_dims_the_header_toward_the_background():
    """The 'STATE' label has to stay quieter than the values it labels, the
    way the default COL_HEADER/COL_VALUE pair does."""
    colors = sc._panel_colors(state_bg="#000000", state_fg="#ffffff")
    assert colors.header == sc._mix("#ffffff", "#000000", sc.HEADER_DIM)

    def lum(c):
        return sum(int(c.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))

    # strictly between background and text, i.e. dimmer than the values
    assert lum(colors.bg) < lum(colors.header) < lum(colors.value)


@pytest.mark.parametrize("fg,bg,t,expected", [
    ("#ffffff", "#000000", 0.0, "#ffffff"),
    ("#ffffff", "#000000", 1.0, "#000000"),
    ("#ffffff", "#000000", 0.5, "#808080"),
    ("#102030", "#102030", 0.5, "#102030"),
])
def test_mix_blends_channelwise(fg, bg, t, expected):
    assert sc._mix(fg, bg, t) == expected


def test_resolve_panel_args_accepts_hex_and_the_none_keyword():
    assert resolve_panel_args("#0d1117", "#9CDCFE") == ("#0d1117", "#9CDCFE")
    assert resolve_panel_args(BG_COLOR_NONE, BG_COLOR_NONE) == (None, None)
    assert resolve_panel_args(None, None) == (None, None)
    assert resolve_panel_args("  #0D1117  ", None)[0] == "#0D1117"   # stripped


@pytest.mark.parametrize("bad", ["blue", "0d1117", "#abc", "#12345g"])
def test_resolve_panel_args_rejects_non_rrggbb(bad):
    with pytest.raises(ValueError) as e:
        resolve_panel_args(bad, None)
    assert "--state-bg-color" in str(e.value)
    with pytest.raises(ValueError) as e:
        resolve_panel_args(None, bad)
    assert "--state-fg-color" in str(e.value)


def test_state_color_env_vars_resolve_like_every_other_option(monkeypatch):
    monkeypatch.setenv("SNIPPET_CAST_STATE_BG_COLOR", "#222233")
    monkeypatch.setenv("SNIPPET_CAST_STATE_FG_COLOR", "#DCDCAA")

    class Args:
        state_bg_color = None
        state_fg_color = None

    args = resolve_env_defaults(Args(), state_bg_color=sc.PANEL_BG,
                                state_fg_color=None)
    assert resolve_panel_args(args.state_bg_color, args.state_fg_color) == \
        ("#222233", "#DCDCAA")


@pytest.mark.skipif(not _rendering_available(), reason="requires ffmpeg and a resolvable FONT_NAME")
def test_plan_canvas_carries_the_resolved_panel_colors():
    """Resolved once, on the Canvas — same reason as Canvas.style: every frame
    of one video has to draw the panel from the same colors."""
    beat = Beat(frozenset({1}), 1, "n", {"a": "1"})
    cv = plan_canvas(["x = 1"], [beat], show_panel=True, subtitles=False,
                     state_bg_color="#0d1117", state_fg_color="#9CDCFE")
    assert cv.panel.bg == "#0d1117"
    assert cv.panel.name == cv.panel.value == "#9CDCFE"


@pytest.mark.skipif(not _rendering_available(), reason="requires ffmpeg and a resolvable FONT_NAME")
def test_render_panel_paints_the_requested_background():
    colors = sc.PanelColors(bg="#0d1117", header="#333333",
                            name="#9CDCFE", value="#9CDCFE")
    img = sc.render_panel({"a": "1"}, 240, 200, colors)
    assert img.getpixel((img.width - 2, img.height - 2)) == (0x0d, 0x11, 0x17)


@pytest.mark.skipif(not _rendering_available(), reason="requires ffmpeg and a resolvable FONT_NAME")
def test_render_panel_without_colors_uses_the_defaults():
    """Kept as an optional argument so any existing call still renders the
    default panel."""
    from PIL import ImageChops

    plain = sc.render_panel({"a": "1"}, 240, 200)
    explicit = sc.render_panel({"a": "1"}, 240, 200, sc.PanelColors())
    assert ImageChops.difference(plain, explicit).getbbox() is None


@pytest.mark.skipif(not _rendering_available(), reason="requires ffmpeg and a resolvable FONT_NAME")
def test_build_honors_state_colors_end_to_end(tmp_path):
    src = tmp_path / "s.py"
    src.write_text("x = 1 #: Assign one.\n")
    out = tmp_path / "panel.mp4"
    build(str(src), str(out), tts="silent",
          state_bg_color="#0d1117", state_fg_color="#9CDCFE")

    frame = tmp_path / "f.png"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(out),
                    "-frames:v", "1", str(frame)], check=True)
    from PIL import Image
    img = Image.open(frame).convert("RGB")
    # The panel occupies the top-right of the code row; sample inside it.
    r, g, b = img.getpixel((img.width - PAD - 4, PAD + 4))
    assert (r, g, b) != (0x1F, 0x1F, 0x1F)      # not the page background
    assert max(r, g, b) < 40                    # the dark panel we asked for


# ---------------------------------------------------------------------------
# --highlight-color and .theme files
# ---------------------------------------------------------------------------
def test_resolve_style_args_validates_the_highlight_color():
    assert resolve_style_args("monokai", None, "#2A2D2E")[2] == "#2A2D2E"
    assert resolve_style_args("monokai", None, BG_COLOR_NONE)[2] is None
    with pytest.raises(ValueError) as e:
        resolve_style_args("monokai", None, "teal")
    assert "--highlight-color" in str(e.value)


def test_resolve_style_overrides_highlight_without_touching_the_base_style():
    base = sc.get_style_by_name("monokai")
    resolved = sc._resolve_style("monokai", None, "#2A2D2E")
    assert resolved.highlight_color == "#2A2D2E"
    assert resolved.background_color == base.background_color  # bg untouched
    assert base.highlight_color == "#49483e"


def test_resolve_style_none_highlight_keeps_the_styles_own(monkeypatch):
    monkeypatch.setattr(sc, "HIGHLIGHT_COLOR", "#ABCDEF")
    assert sc._resolve_style("monokai", None).highlight_color == "#ABCDEF"
    assert sc._resolve_style("monokai", None, None).highlight_color == "#49483e"


def test_highlight_color_env_var_resolves_like_every_other_option(monkeypatch):
    monkeypatch.setenv("SNIPPET_CAST_HIGHLIGHT_COLOR", "#2A2D2E")

    class Args:
        style = None
        bg_color = None
        highlight_color = None

    args = resolve_env_defaults(Args(), style="monokai", bg_color="#1F1F1F",
                                highlight_color=None)
    assert resolve_style_args(args.style, args.bg_color, args.highlight_color)[2] \
        == "#2A2D2E"


@pytest.mark.skipif(not _rendering_available(), reason="requires ffmpeg and a resolvable FONT_NAME")
def test_highlight_color_reaches_the_band(tmp_path):
    """One override has to satisfy BOTH consumers — pygments draws the band
    from the style's highlight_color, and _tighten_highlight() repaints its
    edges from the same value; a mismatch would leave two-tone edges."""
    from PIL import Image, ImageChops

    code = "a = 1\nb = 2"
    style = sc._resolve_style("monokai", None, "#2A2D2E")
    img = sc._render_code(code, hl_lines=[1], style=style)
    band = img.crop((0, 0, img.width, round(img.height / 2)))
    # Every pixel that isn't text must be exactly the requested band color, so
    # nothing is left over from the style's own highlight.
    assert ImageChops.difference(
        band, Image.new("RGB", band.size, "#49483e")).getbbox() is not None
    hist = band.convert("RGB").getcolors(maxcolors=1 << 16)
    dominant = max(hist)[1]
    assert dominant == (0x2A, 0x2D, 0x2E)


THEME = Path(__file__).parent.parent / "data" / "numpy.theme"


@pytest.mark.skipif(not THEME.exists(), reason="needs data/numpy.theme")
def test_load_theme_maps_a_ksyntax_theme_onto_pygments_tokens():
    style = sc.load_theme(str(THEME))
    assert style.background_color == "#F3F4F5"
    resolved = dict(style)

    def color(token):
        # pygments keeps whatever case the source used, so compare lowered.
        return resolved[token]["color"].lower()

    assert color(sc.Token) == "000000"                  # top-level text-color
    assert color(sc.Comment) == "6d6d6d"
    assert color(sc.Keyword) == "6730c5"                # the theme's "Keyword"
    assert color(sc.Keyword.Namespace) == "6730c5"      # Import
    assert color(sc.Operator) == "00622f"
    assert color(sc.Name.Builtin) == "912583"           # print / range / len
    assert color(sc.String) == "008000"
    assert resolved[sc.Error]["bold"] is True           # bold flag honored


@pytest.mark.skipif(not THEME.exists(), reason="needs data/numpy.theme")
def test_load_theme_derives_a_highlight_color():
    """The format carries none, and pygments' unset default is a pale
    '#ffffcc' that reads badly on almost any background."""
    style = sc.load_theme(str(THEME))
    assert style.highlight_color == sc._mix("#F3F4F5", "#000000", sc.THEME_HL_MIX)
    assert style.highlight_color != "#ffffcc"


@pytest.mark.skipif(not THEME.exists(), reason="needs data/numpy.theme")
def test_load_theme_is_cached_per_path():
    """_render_code() resolves the style once per frame; re-reading and
    re-classing the file each time would also defeat _with_colors()' cache."""
    assert sc.load_theme(str(THEME)) is sc.load_theme(str(THEME))


@pytest.mark.skipif(not THEME.exists(), reason="needs data/numpy.theme")
def test_style_accepts_a_theme_file_path():
    assert resolve_style_args(str(THEME), None)[0] == str(THEME)
    assert sc._resolve_style(str(THEME), None).background_color == "#F3F4F5"


def test_unknown_style_that_is_not_a_file_still_lists_valid_names():
    with pytest.raises(ValueError) as e:
        resolve_style_args("./no-such.theme", None)
    assert ".theme file" in str(e.value) and "monokai" in str(e.value)


def test_unreadable_theme_file_fails_at_parse_time(tmp_path):
    """Better here than as a JSONDecodeError from inside the first frame
    render, after the trace has already executed the user's snippet."""
    bad = tmp_path / "bad.theme"
    bad.write_text('{"broken":')
    with pytest.raises(ValueError) as e:
        resolve_style_args(str(bad), None)
    assert "not a readable" in str(e.value)


@pytest.mark.skipif(not (THEME.exists() and _rendering_available()),
                    reason="needs data/numpy.theme, ffmpeg and a resolvable FONT_NAME")
def test_build_renders_from_a_theme_file(tmp_path):
    src = tmp_path / "s.py"
    src.write_text("x = 1 #: Assign one.\n")
    out = tmp_path / "themed.mp4"
    build(str(src), str(out), tts="silent", style=str(THEME), bg_color=None)

    frame = tmp_path / "f.png"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(out),
                    "-frames:v", "1", str(frame)], check=True)
    from PIL import Image
    r, g, b = Image.open(frame).convert("RGB").getpixel((2, 2))
    assert min(r, g, b) > 230        # the theme's own light background


def test_numpy_theme_is_packaged_and_reachable_by_bare_name():
    """BUILTIN_THEMES must resolve from package data, not the working
    directory, or --style numpy would only work inside a checkout."""
    packaged = Path(sc.THEME_DIR) / sc.BUILTIN_THEMES["numpy"]
    assert packaged.is_file()
    style = sc._resolve_style("numpy", None)
    assert style.background_color == "#F3F4F5"
    assert style is sc.load_theme(str(packaged))    # same cached class


def test_builtin_theme_names_are_listed_and_accepted():
    assert "numpy" in sc.style_names()
    assert resolve_style_args("numpy", None)[0] == "numpy"


def test_shipped_defaults_are_the_light_numpy_theme():
    """The default look: the packaged numpy theme's own light background (so
    BG_COLOR must stay None), with a panel and captions to match."""
    assert sc.STYLE == "numpy"
    assert sc.BG_COLOR is None
    resolved = sc._resolve_style()
    assert resolved.background_color == "#F3F4F5"
    assert sc._is_light(resolved.background_color)
    # the panel has to stay a visible step off that background, not blend in
    assert sc.PANEL_BG != resolved.background_color
    assert sc._is_light(sc.PANEL_BG)
    assert not sc._is_light(sc.COL_VALUE)        # dark text on a light box


@pytest.mark.skipif(not _rendering_available(), reason="requires ffmpeg and a resolvable FONT_NAME")
def test_default_canvas_picks_light_caption_colors():
    beat = Beat(frozenset({1}), 1, "n", {})
    cv = plan_canvas(["x = 1"], [beat], show_panel=False, subtitles=True)
    assert (cv.cap_fg, cv.cap_rule) == (sc.COL_CAPTION_LIGHT, sc.COL_RULE_LIGHT)


def test_a_theme_file_cannot_shadow_a_registered_style_name(tmp_path, monkeypatch):
    """_style_by_name() checks the pygments registry BEFORE the filesystem, so
    a stray 'monokai' file in the working directory is ignored."""
    decoy = tmp_path / "monokai"
    decoy.write_text('{"background-color": "#ff0000"}')
    monkeypatch.chdir(tmp_path)
    assert sc._resolve_style("monokai", None).background_color == "#272822"


@pytest.mark.skipif(not THEME.exists(), reason="needs data/numpy.theme")
def test_theme_keywords_use_the_themes_keyword_color_not_controlflow():
    """Regression: THEME_TOKEN_MAP sent Token.Keyword to the theme's
    "ControlFlow" entry, so `def`/`for`/`return`/`as` all came out #aa0000.
    pygments emits plain Token.Keyword for declaration AND control-flow
    keywords alike, so the union has to land on the theme's more GENERAL
    "Keyword" entry. `in`/`is`/`and`/`or`/`not` are Operator.Word in pygments
    and belong there too."""
    resolved = dict(sc.load_theme(str(THEME)))
    for token in (sc.Keyword, sc.Operator.Word):
        assert resolved[token]["color"].lower() == "6730c5"


@pytest.mark.skipif(not THEME.exists(), reason="needs data/numpy.theme")
def test_theme_leaves_user_written_names_as_plain_text():
    """Regression: Name.Function was mapped to the theme's "Function" entry,
    so the name after `def` came out #aa0000. KSyntaxHighlighting's Python
    definition doesn't classify identifiers the user writes, so these must
    fall through to the theme's plain text color — mapping them invents a
    color the theme never asked for."""
    from pygments.token import Punctuation

    resolved = dict(sc.load_theme(str(THEME)))
    plain = resolved[sc.Token]["color"].lower()
    for token in (sc.Name, sc.Name.Function, sc.Name.Class, sc.Name.Namespace,
                  Punctuation):
        assert resolved[token]["color"].lower() == plain, token
    # ...while language-provided names keep their own color.
    assert resolved[sc.Name.Builtin]["color"].lower() != plain


@pytest.mark.skipif(not THEME.exists(), reason="needs data/numpy.theme")
def test_theme_colors_a_real_snippet_token_by_token():
    """End-to-end through the lexer, which is the only way to catch a mapping
    that is individually plausible but wrong for the token pygments actually
    emits (e.g. `in` being Operator.Word, not Keyword)."""
    from pygments.lexers import PythonLexer

    resolved = dict(sc.load_theme(str(THEME)))
    code = "def fib(n):\n    for _ in range(n):\n        pass\nimport numpy as np\n"
    got = {}
    for token, value in PythonLexer().get_tokens(code):
        value = value.strip()
        if value:
            got.setdefault(value, resolved[token]["color"].lower())

    assert got == {
        "def": "6730c5", "fib": "000000", "(": "000000", "n": "000000",
        ")": "000000", ":": "000000", "for": "6730c5", "_": "000000",
        "in": "6730c5", "range": "912583", "pass": "6730c5",
        "import": "6730c5", "numpy": "000000", "as": "6730c5", "np": "000000",
    }
