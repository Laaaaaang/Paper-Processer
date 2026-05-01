# Research Flow GUI

Desktop workflow for:

`PDF -> Zotero -> .paper.json -> LLM -> Obsidian note`

This project is meant to feel like a simple operator tool, not a manual developer pipeline. The main entrypoint is now a local browser UI:

```bash
python3 -m research_flow gui
```

That command starts a local server and opens a browser tab on `http://127.0.0.1:8765` or the next available port.

You upload a PDF, review the metadata, and the app will:

- let you choose a real Zotero Desktop library / collection target
- import the PDF into Zotero Desktop and reuse Zotero's own PDF recognition flow
- save a normalized `.paper.json` packet automatically
- send that packet to the LLM for structured understanding
- save a `.analysis.json` result file
- generate a polished Markdown literature note in Obsidian

## Reading Modes

The app supports two reading modes, selectable from the GUI or CLI:

### Single-Pass (Legacy)

One LLM call produces a flat analysis covering summary, methods, findings, strengths, limitations, quotes, and next actions. Fast and sufficient for papers you only need a quick overview of.

### Three-Phase (粗读 → 精读 → 讨论)

Three sequential LLM calls that mimic a real research reading workflow:

| Phase | Focus | Output |
|-------|-------|--------|
| **Phase 1: 粗读 (Skim)** | Abstract + conclusion | Research type, core question, TL;DR, reading priority |
| **Phase 2: 精读 (Deep Read)** | Methods + algorithms | Step-by-step algorithm decomposition with inputs/outputs/formulas, design choices, technical novelty, Socratic open questions |
| **Phase 3: 讨论 (Discussion)** | Experiments + limitations | Structured baselines, quantitative results table, evidence-based limitations, future directions, critical assessment |

Each phase receives the output of previous phases as context. This produces significantly deeper analysis, especially for algorithm-heavy papers.

The three phases can also be run independently via CLI if you only need one aspect.

## What The GUI Does

The GUI version is designed for a semi-automatic research-note workflow:

1. Put a PDF into the app
2. Load the Zotero Desktop collection tree and choose the exact library / collection target
3. Autofill metadata from the PDF first, then let Zotero Desktop recognition improve it when possible
3. Review or edit title, authors, year, DOI, abstract, tags, and note summary
4. Choose reading mode: **Single-Pass** or **Three-Phase**
5. Click `Run Pipeline`

After that, the app handles the rest:

- Zotero becomes the paper database
- the `.paper.json` file becomes the handoff record
- the LLM produces structured understanding
- Obsidian receives the final literature note

## Before You Start

You need:

- Python 3.9+
- a Zotero account with an API key
- an LLM API key for OpenAI, Gemini / Google AI Studio, or DeepSeek
- an Obsidian vault path, or Obsidian Local REST API

Recommended supporting tools:

- Better BibTeX in Zotero
- Obsidian Zotero Integration
- Obsidian Dataview (for querying paper metadata, tags, and concepts across your vault)
- Obsidian Local REST API if you want REST-based write-back

The previous native Tk window was unreliable on macOS, so the browser UI is now the supported path.

## Setup

1. Copy [research-flow.config.example.json](research-flow.config.example.json) to `research-flow.config.json`
2. Fill in the required settings
3. Launch the GUI

Minimal config fields:

- `zotero_user_id`
- `zotero_api_key`
- `zotero_connector_url`
- `llm_provider`
- either `openai_api_key`, `gemini_api_key`, or `deepseek_api_key`
- `obsidian_vault_path`

Useful optional fields:

- `zotero_collection_key`
- `zotero_desktop_target_id`
- `packet_dir`
- `obsidian_rest_url`
- `obsidian_rest_api_key`
- `note_subdir`

Example:

```json
{
  "zotero_user_id": "1234567",
  "zotero_api_key": "your-zotero-api-key",
  "zotero_library_type": "users",
  "zotero_connector_url": "http://127.0.0.1:23119",
  "zotero_desktop_target_id": "",
  "zotero_collection_key": "",
  "llm_provider": "openai",
  "openai_api_key": "your-openai-api-key",
  "openai_model": "gpt-5.4",
  "gemini_api_key": "your-gemini-api-key",
  "gemini_model": "gemini-2.5-flash",
  "deepseek_api_key": "your-deepseek-api-key",
  "deepseek_model": "deepseek-chat",
  "obsidian_vault_path": "/absolute/path/to/your/Obsidian vault",
  "obsidian_rest_url": "",
  "obsidian_rest_api_key": "",
  "packet_dir": "",
  "note_subdir": "Literature",
  "default_item_type": "journalArticle",
  "default_status": "inbox"
}
```

## Running The GUI

Start the app:

```bash
cd "/path/to/Paper-Processer"
python3 -m research_flow gui
```

Then use the browser UI:

1. Load or save the config in the `Connections` section
2. Click `Load Zotero Libraries`
3. Choose the exact Zotero Desktop library / collection target from the tree
4. Choose a PDF in the `Zotero Desktop` section
5. Click `Upload PDF`
6. The app will try PDF extraction first and then import into Zotero Desktop automatically if a target is selected
7. You can also click `Import Into Zotero & Autofill` manually to retry the Zotero Desktop step
8. Review and fix metadata
9. Paste the abstract and any annotation summary
10. Click `Run Pipeline`

For the best immediate autofill experience, enable Zotero's Local API in Zotero:

1. Open Zotero Desktop
2. Go to `Settings` -> `Advanced`
3. Enable the Local API option

The app can still work without the Local API, but immediate metadata read-back may fall back to synced library search instead of the local desktop database.

## Where Files Go

### Zotero

- If you use the Zotero Desktop import flow, the app:

- imports the PDF as a standalone attachment into Zotero Desktop
- lets Zotero create or recognize the parent item
- moves the recognized item into the collection you selected in the GUI

- During `Run Pipeline`, the app then reuses that recognized Zotero item instead of creating a duplicate.

- If you skip the Zotero Desktop import flow, the app falls back to creating:

- a Zotero parent item for the paper
- a Zotero PDF attachment under that item

If `zotero_collection_key` is set, the new item is also added to that collection.

### The JSON packet

By default, the normalized packet is written next to the source PDF:

```text
<same folder as pdf>/<pdf-name>.paper.json
```

Example:

```text
/Users/you/Papers/my-paper.pdf
/Users/you/Papers/my-paper.paper.json
```

If `packet_dir` is set in the config, the packet is written there instead.

When you upload a PDF in the browser UI, it is first copied into:

```text
<repo>/imports/
```

and the packet is then generated from that imported copy.

### The analysis file

The structured LLM result is saved beside the packet:

```text
<pdf-name>.paper.analysis.json
```

In three-phase mode, additional files are generated:

```text
<pdf-name>.paper.skim.json         # Phase 1 skim result
<pdf-name>.paper.deep-read.json    # Phase 2 algorithm decomposition
<pdf-name>.paper.discussion.json   # Phase 3 experiments + critique
```

### The Obsidian note

If you set `obsidian_vault_path`, the final note is written directly into your vault:

```text
<your vault>/<note_subdir>/<citekey> - <short-title>.md
```

Typical example:

```text
/Users/you/Documents/MyVault/Literature/smith2025retrieval - retrieval-augmented-reasoning-for-scientific-cla.md
```

If you use Obsidian Local REST API instead, the target path inside the vault is:

```text
<note_subdir>/<citekey> - <short-title>.md
```

## What Metadata Is Automatic vs Manual

Automatic or best-effort:

- PDF path
- title from PDF metadata, extracted text, or filename
- authors from embedded PDF metadata or extracted text
- year from filename/title heuristic or looked-up metadata
- DOI when detected in the PDF text
- URL when available in PDF metadata
- journal and abstract when recovered from DOI lookup, Zotero Desktop recognition, or library search

Still best entered or reviewed by you:

- abstract
- DOI
- journal / venue
- tags
- annotation summary

This is still intentional. PDF metadata is often incomplete or wrong, so the browser UI now prefers Zotero Desktop recognition when available, but you should still review the result before the paper is pushed through the full pipeline.

## Note Structure

### Single-Pass Mode (Legacy)

Each generated note uses this shape:

- frontmatter with `citekey`, `zotero_key`, `title`, `authors`, `year`, `journal`, `doi`, `url`, `tags`, `concepts`, `status`
- `中文摘要`
- `English Abstract Snapshot`
- `Core Question`
- `Methods`
- `Key Findings`
- `Strengths`
- `Limitations`
- `Useful Quotes`
- `Key Concepts` — `[[wiki-links]]` to key methods, models, and datasets
- `My Connections`
- `Next Actions`

### Three-Phase Mode

The three-phase note has a richer structure:

- frontmatter (same as above, plus `reading_mode`, `research_type`, `reading_priority`, `concepts`)
- **Phase 1: 粗读**
  - `Core Question`
  - `TL;DR 摘要` — dense Chinese summary
  - `Conclusion Takeaways`
  - `Initial Impression`
  - `Key Concepts` — `[[wiki-links]]` to key methods, models, and datasets
- **Phase 2: 精读**
  - `算法总览` — bird's-eye view of the method
  - `算法流程拆解` — numbered steps, each with inputs, outputs, formulas, and rationale
  - `Key Design Choices`
  - `技术新颖性`
  - `Implementation Details`
  - `Open Questions (苏格拉底式追问)` — critical questions for further investigation
- **Phase 3: 讨论**
  - `Experimental Setup`
  - `Baselines`
  - `定量结果` — structured markdown table with metrics, values, comparisons
  - `局限性分析`
  - `Future Directions`
  - `我的批判性评价`
  - `Vault Connections`

## CLI Commands

The GUI is the main path, but these CLI commands are also available:

### Legacy commands

```bash
python3 -m research_flow gui
python3 -m research_flow from-pdf "/absolute/path/to/paper.pdf"
python3 -m research_flow ingest "/absolute/path/to/paper.pdf" --config research-flow.config.json --title "Paper Title" --authors "Author One, Author Two"
python3 -m research_flow validate examples/annotated_paper.json
python3 -m research_flow prepare examples/annotated_paper.json --output generated/annotated.prompt.md
python3 -m research_flow finalize examples/annotated_paper.json examples/annotated_analysis.json --output-dir generated
python3 -m research_flow synthesize examples/annotated_paper.json --output-dir generated
```

### Three-phase reading commands

```bash
# Run all three phases sequentially (recommended)
python3 -m research_flow full-read examples/annotated_paper.json --config research-flow.config.json

# Run individual phases
python3 -m research_flow skim examples/annotated_paper.json --config research-flow.config.json
python3 -m research_flow deep-read examples/annotated_paper.json --config research-flow.config.json --skim-input examples/annotated_paper.skim.json
python3 -m research_flow discuss examples/annotated_paper.json --config research-flow.config.json --skim-input examples/annotated_paper.skim.json --deep-read-input examples/annotated_paper.deep-read.json

# Extract text from PDF into sections (for inspection or reuse)
python3 -m research_flow extract-text "/absolute/path/to/paper.pdf"
```

Each phase saves its output as a JSON file:
- `*.skim.json` — Phase 1 result
- `*.deep-read.json` — Phase 2 result (algorithm decomposition)
- `*.discussion.json` — Phase 3 result (experiments + critique)

Later phases accept earlier results as `--skim-input` / `--deep-read-input` for better context, but can also run standalone.

## Current Limitations

- full immediate metadata read-back is best when Zotero Desktop Local API is enabled
- if Local API is off, read-back may fall back to synced library search and can lag behind local Zotero changes
- the GUI does not yet read highlights directly out of Zotero
- full end-to-end live use requires your real Zotero/LLM/Obsidian credentials
- `llm_provider` currently supports `openai`, `gemini`, and `deepseek`
- three-phase mode makes 3 LLM calls per paper (higher cost, better depth)
- PDF full text extraction requires `pymupdf` (`pip install pymupdf`) or `pdftotext` (poppler); without either, three-phase mode still works but relies on abstract + annotations only
- section segmentation uses heuristic heading detection — non-standard paper formats may segment imprecisely

## Recommended Usage Model

- Use Zotero as the source of truth for papers and PDF storage
- Let this app generate the `.paper.json` and `.analysis.json` files automatically
- Keep polished long-form research notes in Obsidian
- Use the generated note path as your stable literature-note location

## Using Obsidian Graph View

The generated notes are designed to work with Obsidian's Graph View:

- **Tags** in frontmatter merge Zotero tags with LLM-generated semantic tags. Use Graph View's tag-based color groups to see domain clusters.
- **Key Concepts** are rendered as `[[wiki-links]]` (e.g. `[[Transformer]]`, `[[GNN]]`). When multiple papers share a concept, they form connected clusters in Graph View.
- **Vault Connections** (three-phase mode) link to related papers, methods, and theories using `[[wikilink]]` format.
- **Dataview** can query frontmatter fields like `tags`, `concepts`, `research_type`, and `reading_priority` across all literature notes.

Example Dataview query to list all papers mentioning a concept:

````markdown
```dataview
TABLE authors, year, reading_priority
FROM "Literature"
WHERE contains(concepts, "GNN")
SORT year DESC
```
````

## More Detail

- [docs/SETUP.md](docs/SETUP.md)
- [research-flow.config.example.json](research-flow.config.example.json)
- [examples/annotated_paper.json](examples/annotated_paper.json)
- [examples/annotated_analysis.json](examples/annotated_analysis.json)
