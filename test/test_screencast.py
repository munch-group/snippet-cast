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
    TYPE_SPEED,
    Beat,
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
    resolve_output_path,
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
    loop — pass 1 had no pause logic at all. Uses a minimal 2-marker
    snippet, both markers narrated in both passes, so the gap count is
    unambiguous by construction: 1 internal gap within pass 1 (between its
    2 beats) + 1 within pass 2 = 2 gaps total, none after the very last beat
    of the whole video. pause=P should add exactly 2*P seconds vs. pause=0."""
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
    assert round(d2 - d0, 1) == 4.0  # exactly 2 gaps * 2.0s — no more, no fewer
