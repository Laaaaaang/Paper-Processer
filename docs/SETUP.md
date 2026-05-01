# Setup Guide

## 1. Install the reuse-first tools

In Zotero:

- Install Better BibTeX for stable citekeys.
- Keep Zotero as the canonical paper database.
- Optionally install PapersGPT if you want Zotero-side chat or MCP later.

In Obsidian:

- Install Obsidian Zotero Integration if you want to import annotations or bibliographic data into raw notes.
- Optionally install Obsidian Local REST API if you want this toolkit to write notes directly into the vault.

## 2. Configure the automated pipeline

Copy [research-flow.config.example.json](/Users/lang/Documents/New%20project/research-flow.config.example.json) to `research-flow.config.json` and fill in:

- `zotero_user_id`
- `zotero_api_key`
- `llm_provider`
- either `openai_api_key` or `gemini_api_key`
- `obsidian_vault_path` if you want direct vault writes

Optional fields:

- `zotero_collection_key` to place imported items into one collection
- `packet_dir` if you do not want `.paper.json` files next to the source PDFs
- `obsidian_rest_url` and `obsidian_rest_api_key` if you prefer REST-based writes
- `note_subdir` if you want notes somewhere other than `Literature`

## 3. Build the normalized paper packet

This repo treats the normalized JSON packet as the contract between Zotero and Codex.

Minimal required fields:

```json
{
  "citekey": "smith2025retrieval",
  "zotero_item_key": "ABCD1234",
  "title": "Retrieval-Augmented Reasoning for Scientific Claim Verification",
  "authors": ["Jane Smith", "Wei Chen"]
}
```

Recommended practice:

- Add the paper abstract from Zotero.
- Add `annotation_text` from your highlights or notes.
- Add structured `annotations` when you want better quotes in the final note.
- Add `pdf_path` when you want the packet to remember where the source file lives.

## 4. Use Codex as the synthesis layer

Generate the synthesis prompt:

```bash
python3 -m research_flow prepare examples/annotated_paper.json --output generated/annotated.prompt.md
```

Then use that prompt in one of two ways:

- Paste it into Codex and save the JSON response to a file.
- Run `synthesize` and let the tool call OpenAI or Gemini directly.

## 5. Render the final Obsidian note

```bash
python3 -m research_flow finalize \
  examples/annotated_paper.json \
  examples/annotated_analysis.json \
  --output-dir generated
```

This writes a deterministic Markdown file under `generated/Literature/`.

## 6. Optional direct vault write

If Obsidian Local REST API is running:

```bash
python3 -m research_flow synthesize \
  examples/annotated_paper.json \
  --obsidian-url https://127.0.0.1:27124 \
  --obsidian-api-key YOUR_KEY
```

## Suggested operating model

- Keep Zotero collections and PDFs in Zotero.
- Use this toolkit only for normalized packets plus final literature notes.
- Store polished notes in Obsidian under `Literature/`.
- Re-run the same packet when you want a deterministic update to the same note path.

## GUI-first automated workflow

Launch:

```bash
python3 -m research_flow gui
```

Then:

1. Drop or select a PDF
2. Click `Autofill` to prefill metadata from the PDF and filename
3. Fix the metadata fields as needed
4. Paste the abstract and any annotation summary
5. Click `Run Pipeline`

Outputs:

- Zotero receives a metadata item plus uploaded PDF attachment
- `<pdf stem>.paper.json` is written next to the source PDF unless `packet_dir` is set
- `<pdf stem>.paper.analysis.json` is written beside the packet
- The final note is written into your Obsidian vault under `<note_subdir>/`
