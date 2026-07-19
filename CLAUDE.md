# Project Configuration for Claude

This file contains preferences and guidelines for working in this project.

## What this repository is

**snippet-cast** is a distributable Python library and CLI (`snippet-cast`) that
turns an **annotated Python snippet** into a **narrated screencast video**.
Narration is written as trailing `#:` comments on the snippet's own lines, so
the input stays valid, runnable Python. The tool renders syntax-highlighted
code frames with a progressive reveal, a Python-Tutor-style live variable
panel, optional burned-in captions and a typing-in animation, synthesises
speech per line, and stitches everything into an MP4 with ffmpeg. There is no
framework and no web server — it is a plain library + CLI, packaged with the
repo's usual pixi/setuptools/conda/PyPI scaffolding.

### Commands

Requires **Python 3.10+** (uses `int | None` annotations at runtime) and
**ffmpeg + ffprobe on PATH** (declared as a `[tool.pixi.dependencies]` conda
package). Python deps `pillow`/`pygments` are declared in `[project.dependencies]`.

```bash
# environment (pixi is this project's env manager)
pixi install                     # installs ffmpeg + pillow + pygments + snippet-cast (editable)

# run — proofing loop (no audio backend needed, fast)
pixi run snippet-cast test/data/fib.py  -o out.mp4 --tts silent --subtitles

# run — feature combinations
pixi run snippet-cast test/data/fib.py  -o out.mp4 --typing --subtitles      # first-exec + typing
pixi run snippet-cast test/data/loop.py -o out.mp4 --every  --subtitles      # per-iteration walkthrough
pixi run snippet-cast test/data/fib.py  -o out.mp4 --no-trace                # code + highlight only

# real voices (see SETUP.md)
pixi run snippet-cast test/data/fib.py  -o out.mp4 --tts piper
pixi run snippet-cast test/data/fib.py  -o out.mp4 --tts elevenlabs

# programmatic use
python -c "from snippet_cast import build; build('test/data/fib.py', 'out.mp4', tts='silent')"

# smoke-verify an output
ffprobe -v error -show_entries format=duration \
        -show_entries stream=codec_type,width,height -of default=nw=1 out.mp4
```

Automated tests live in `test/test_screencast.py` and cover parsing, tracing,
and beat-construction logic without needing ffmpeg; a full-render smoke test
runs only when ffmpeg and the configured `FONT_NAME` are both resolvable on
the host (`pytest -q`). See [Verifying changes](#verifying-changes) for the
manual recipe used to sanity-check rendered video output.

### Repository layout

| Path | Purpose |
|---|---|
| `src/snippet_cast/screencast.py` | The entire tool (~700 lines): parse → trace → beats → render → TTS → assemble. |
| `src/snippet_cast/__init__.py` | Public API: exports `build` (programmatic) and `main` (CLI entry point). |
| `SETUP.md` | How to install/configure the Piper and ElevenLabs TTS backends. |
| `test/data/fib.py`, `test/data/loop.py` | Sample annotated snippets used by tests and for manual verification. |
| `test/test_screencast.py` | Automated tests: parsing, tracing, beat construction, and a full-render smoke test. |
| `*.mp4` | Generated outputs (not source; safe to delete / gitignore). |

### Architecture

Data flows through five stages; each has a clear boundary, so most edits touch
only one. Names below are the actual functions/classes in
`src/snippet_cast/screencast.py`.

```
source.py
  └─ parse()            -> code_lines[], markers[Marker]      # strip #: narration
  └─ trace_run()        -> steps[Step]                        # run under sys.settrace
  └─ build_beats()      -> beats[Beat]                        # mode-specific assembly
  └─ plan_canvas()      -> Canvas   (+ compose(), typing_frames())  # fixed-size frames
  └─ synth_*() + make_clip() + concat()  -> out.mp4           # TTS + ffmpeg
```

Key data structures:

- **`Marker`** `(line_no, text, has_code)` — a parsed `#:` annotation. `has_code`
  is False for comment-only (intro/outro) lines.
- **`Step`** `(line_no, disp, text, frame_id)` — one *execution* of a line, in
  completion order. `disp` = `{name: repr}` for the panel; `text` =
  `{name: str(value)}` for `{var}` interpolation; `frame_id` = `id(frame)`.
- **`Beat`** `(reveal_upto, highlight, narration, state)` — one render-ready unit
  = one frame + one narration clip. `narration` is already interpolated;
  `reveal_upto=None` means "show all code".
- **`Canvas`** — fixed dimensions + per-beat wrapped caption lines, computed once
  so every frame shares one resolution.

#### Two modes (set by `--every`)

- **first-exec (default):** one beat per marked line, using that line's *first*
  execution for state/interpolation. Code is **progressively revealed** up to the
  highlighted line. Typing animation applies here.
- **every-exec (`--every`):** one beat per *execution*, in trace order, so loops
  animate iteration-by-iteration. The **full snippet is shown from the start** and
  the highlight follows execution (progressive reveal is intentionally disabled
  here — a bottom driver call would otherwise make the reveal jump around).

### Critical invariants — do not break these

These are non-obvious and fail *silently* or only under specific flag
combinations:

1. **All frames must share one resolution.** Final assembly uses ffmpeg
   `concat -c copy`, which requires identical stream params. `plan_canvas()`
   fixes W/H once (even numbers, for libx264). Any per-frame content change must
   fit the existing canvas, not resize it.
2. **All audio is normalised to 44.1 kHz stereo AAC** (`AUDIO_AR`/`AUDIO_AC` in
   `make_clip` and `make_typing_clip`). This is what lets silent typing clips
   concat with real-backend clips (mp3/wav/aiff of varying rates). Removing the
   `-ar/-ac` flags reintroduces a concat-copy mismatch that only surfaces when
   `--typing` meets a non-silent backend.
3. **Trace post-state is captured on the *next* same-frame line event** (or the
   frame's return), not on the line itself — see `trace_run`. That deferral is
   why "state after line L runs" is correct, including nested-call side effects.
4. **Loop-header exit beat suppression** (`--every`): a marked `for`/`while` line
   fires one extra time when the loop exhausts. `build_beats` drops it using
   `loop_body_ranges()` (AST) + `frame_id` — the exit check's next same-frame step
   lands outside the loop body. Don't remove this or loops gain a phantom beat.
5. **Parsing uses `tokenize`, not regex**, so a `#` inside a string literal is
   never mistaken for a marker. Keep it that way.
6. **`_render_code` guards empty content** (`code = " "`); PIL cannot encode a
   zero-size image (the intro comment-only beat reveals no code yet).
7. **`--every`/tracing executes the snippet.** `trace_run` runs arbitrary user
   code. This is intended (it's the user's own teaching code) but keep the
   `--no-trace` escape hatch, and never execute untrusted input silently.
8. **Interpolation uses `str(value)` snapshotted at capture time** (not `repr`,
   not a live reference) so `{i}` → `0` not `'0'`, and mutation/aliasing can't
   corrupt earlier beats. `{{`/`}}` escape; unknown `{x}` is left literal.

### TTS backends

A backend is any `synth(text, out_stem) -> path_to_audio_file`; `make_clip`
re-encodes whatever it returns, so the container/rate don't matter. Registered
in the `BACKENDS` dict: `say` (macOS), `silent` (timing stand-in), `piper`
(local, `pip install piper-tts` or the `piper` pixi optional-dependency group),
`elevenlabs` (REST via stdlib urllib). Config and setup live in **SETUP.md**.
Note: `build()` **caches audio per unique narration string** — matters for
ElevenLabs billing and for repeated loop lines.

### Verifying changes

After any edit, run this sequence and eyeball a couple of frames:

```bash
pixi run python -c "import ast; ast.parse(open('src/snippet_cast/screencast.py').read())"  # syntax
pixi run snippet-cast test/data/fib.py  -o /tmp/a.mp4 --tts silent --typing --subtitles
pixi run snippet-cast test/data/loop.py -o /tmp/b.mp4 --tts silent --every --subtitles
for f in /tmp/a.mp4 /tmp/b.mp4; do ffprobe -v error -show_entries \
  format=duration -show_entries stream=width,height -of csv=p=0 "$f"; done
ffmpeg -y -ss 2 -i /tmp/b.mp4 -frames:v 1 /tmp/frame.png   # inspect visually
pixi run python -m pytest -q                               # automated checks
```

For trace/interpolation logic, prefer a fast unit check over rendering video:

```bash
pixi run python -c "import snippet_cast.screencast as s; src=open('test/data/loop.py').read();
cl,mk=s.parse(src); st=s.trace_run(src,'test/data/loop.py'); lr=s.loop_body_ranges(src);
[print(b.highlight, b.state, '::', b.narration)
 for b in s.build_beats(cl,mk,st,every=True,loop_ranges=lr)]"
```

### Conventions

- **Single file, stdlib-first.** Only third-party deps are Pillow and Pygments;
  everything else (HTTP for ElevenLabs, AST, tokenize) is stdlib. Keep new deps
  out unless there's a strong reason.
- **Tunables are module-level constants** at the top (`MARKER`, `STYLE`, `FONT_*`,
  `FPS`, `TYPE_*`, `AUDIO_*`, colours). Add config there, not as magic numbers.
- **ffmpeg is called via `subprocess.run`** with stdout/stderr to DEVNULL and
  `check=True`. Follow that pattern; surface real errors (see `synth_piper`).
- Private helpers are `_prefixed`. Rendering is split: `_render_code` (pygments)
  vs `render_panel`/`_draw_caption` (hand-drawn PIL).

### Common changes

- **Add a TTS backend:** write `synth_x(text, out)->path`, add to `BACKENDS`. Done.
- **Change theme/font:** edit `STYLE` (any pygments style) and `FONT_NAME` /
  `FONT_SIZE`; panel/caption colours are constants. Both the hand-drawn panel
  (`_mono_font`) and the pygments code frame (`_render_code`) resolve a font
  file via `_mono_font_path()`/`_FONT_CANDIDATES` first, falling back to
  `FONT_NAME`'s by-name OS lookup only if none of those paths exist — add
  paths to `_FONT_CANDIDATES` for a new platform/font rather than relying on
  `FONT_NAME` alone, since pygments resolves bare names against the OS's
  installed fonts (e.g. "DejaVu Sans Mono" isn't a stock macOS font).
- **Change the narration marker:** `MARKER` (keep it a valid `#` comment prefix).
- **Adjust typing speed:** `TYPE_CPF` (chars/frame), `TYPE_MAXFRAMES` (cap).

### Known limitations / candidate next steps

- **`--every` on large loops** makes very long videos (one beat per iteration).
  The mooted fix is `--max-iters N` in `build_beats`: keep the first N iteration
  beats, then a single "… and so on" beat.
- **Live TTS is untested in CI** (no network in sandbox); the request shapes
  match current Piper CLI / ElevenLabs REST as of the SETUP.md date — re-verify
  against their docs if a call starts failing.

## MCP Server Usage Guidelines

This project has several MCP (Model Context Protocol) servers available. Use them according to these guidelines:

**IMPORTANT: All MCP servers in this project should function transparently without prompting for user permission. Use them freely and directly when needed.**

The following servers are configured to work without permission prompts:
- `paper-search`: Scientific literature searches
- `string-db`: Protein interaction analysis
- `ensembl-db`: Genomic data queries
- `desktop-commander`: System operations and development tasks

### Scientific Literature & Research

#### paper-search MCP Server

**IMPORTANT: Always use `paper-search` MCP for scientific literature searches.**

**Use paper-search for searching and downloading academic papers from multiple scientific databases.**

Supported databases:
- **arXiv**: Preprints in physics, mathematics, computer science
- **PubMed**: Biomedical and life sciences literature
- **bioRxiv**: Biology preprints
- **medRxiv**: Medical preprints
- **Google Scholar**: Broad academic search
- **IACR ePrint**: Cryptography research
- **Semantic Scholar**: AI-powered academic search

Available functions:
- `search_arxiv()`: Search papers on arXiv
- `download_arxiv()`: Download PDFs from arXiv
- Similar search/download functions for other platforms

Features:
- Returns papers in standardized format
- Asynchronous requests for efficiency
- Supports API keys for enhanced access (e.g., Semantic Scholar)

**Use paper-search when:**
- Finding scientific papers, articles, and publications
- Searching by author names, keywords, or topics
- Academic research queries
- Citation lookups
- Literature reviews
- Downloading research papers

**Never use web search or other tools for scientific literature - always use paper-search.**

### Bioinformatics & Genomics

#### string-db MCP Server

**Use string-db for protein-protein interaction analysis and functional enrichment.**

Available tools:

- **Identifier Mapping:**
  - `get_string_ids`: Map protein names/IDs to STRING identifiers across species
  - `resolve_proteins`: Standardize protein names to canonical STRING names

- **Network Analysis:**
  - `get_network`: Retrieve protein-protein interaction networks with confidence filtering
  - `get_interaction_partners`: Find interaction partners for given proteins (with confidence thresholds)

- **Functional Enrichment:**
  - `get_enrichment`: Perform functional enrichment analysis (GO terms, KEGG pathways, domains)
  - `get_ppi_enrichment`: Test if protein sets have statistically significant interactions

- **Cross-Species Analysis:**
  - `get_homology`: Retrieve protein homology information across species
  - `get_homology_best`: Find best homology matches in target species

- **Utility:**
  - `get_version`: Get current STRING database version

**Supported species (common):**
- Human (9606), Mouse (10090), Rat (10116)
- Fruit fly (7227), C. elegans (6239), Yeast (4932)

**Use string-db when:**
- Analyzing protein interactions and networks
- Performing functional enrichment analysis
- Mapping proteins across species
- Finding interaction partners or homologs
- Testing for PPI enrichment in protein sets

#### ensembl-db MCP Server

**Use ensembl-db for genomic data retrieval and analysis via the Ensembl REST API.**

Available tools (31 endpoints across 11 categories):

- **Gene Lookup:**
  - `lookup_gene_by_symbol`: Find genes by symbol (e.g., BRCA2)
  - `lookup_gene_by_id`: Find genes by Ensembl stable ID

- **Sequence Retrieval:**
  - `get_sequence`: Retrieve DNA/RNA/protein sequences

- **Variant Analysis:**
  - `get_variants_for_region`: Find genetic variants in genomic regions
  - `vep_region`: Predict variant consequences (Variant Effect Predictor)

- **Cross-Species Homology:**
  - `get_homology`: Find homologous genes/proteins across species

- **Phenotype Data:**
  - `get_phenotype_by_gene`: Retrieve phenotype annotations for genes

- **Regulatory Features:**
  - `get_regulatory_features`: Find regulatory elements in genomic regions

- **Overlap Analysis:**
  - `overlap_region`, `overlap_id`, `overlap_translation`: Find overlapping genomic features

- **Cross-References:**
  - `get_xrefs_by_gene`, `get_xrefs_by_symbol`, `get_xrefs_by_name`: External database references

- **Coordinate Mapping:**
  - Tools for mapping between assemblies and genomic/protein coordinates

- **Ontology & Taxonomy:**
  - Search and retrieve ontology terms and taxonomy information

**Use ensembl-db when:**
- Looking up genes by symbol or ID
- Retrieving genomic sequences
- Analyzing genetic variants and their effects
- Finding gene homologs across species
- Exploring phenotype associations
- Identifying regulatory features
- Mapping between genome assemblies

### System Operations

#### desktop-commander MCP Server

**Use desktop-commander for advanced system interaction, terminal control, and development tasks.**

Available capabilities:

- **Terminal Control:**
  - Execute terminal commands with output streaming
  - Run long-running commands in background
  - Manage and kill processes
  - Monitor command output in real-time

- **Filesystem Operations:**
  - Read/write files
  - Create/list directories
  - Move files and directories
  - Search files across filesystem
  - Get file metadata
  - Negative offset reading (like Unix `tail`)

- **Code Editing:**
  - Surgical text replacements in files
  - Full file rewrites
  - Multiple file editing
  - Pattern-based replacements
  - VSCode-ripgrep recursive code/text search

- **Development Environment:**
  - Execute code in memory (Python, Node.js, R)
  - Instant data analysis for CSV/JSON files
  - Interact with development servers and databases

**Use desktop-commander when:**
- Running terminal commands or shell scripts
- Managing processes or background tasks
- Performing filesystem operations
- Editing code or text files
- Searching code across the project
- Executing code snippets for quick analysis
- Interacting with development servers

### General Purpose

- **filesystem**: File operations within the workspace
- **fetch**: Web content fetching for non-scientific content
- **memory**: Persistent memory across conversations

## Project Context

- **Field**: Bioinformatics / Computational Biology
- **Primary Language**: Python
- **Environment**: Devcontainer with pixi package management

## Code Style Preferences

- Follow existing code style in the repository
- Use type hints in Python code
- Include docstrings for functions and classes
- Follow scientific computing best practices

## Citation Format

When adding inline citations to scientific papers, use Author-Year format:
- Up to two authors: (Munch, 2025) or (Munch and Hobolth, 2025)
- Three or more: (Munch et al., 2025)
- Citation labels should be hyperlinks to the paper on the journal website

## Notes

- This project uses MCP servers for enhanced capabilities
- The devcontainer includes pixi for package management
- MCP servers use pixi environments (conda packages + pip when needed)
- PyPI-based servers are installed with pip in the shared pixi environment to ensure Python headers are available
