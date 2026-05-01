from __future__ import annotations

import cgi
import json
import threading
import uuid
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from .config import AppConfig
from .pipeline import IngestRequest, extract_prefill, run_ingest_pipeline
from .zotero_api import (
    ZoteroAPIError,
    ZoteroClient,
    ZoteroDesktopClient,
    ZoteroDesktopError,
)


DEFAULT_CONFIG_PATH = Path("research-flow.config.json")
WORKSPACE_IMPORT_DIR = Path("imports")
SECRET_CONFIG_FIELDS = (
    "zotero_api_key",
    "openai_api_key",
    "gemini_api_key",
    "deepseek_api_key",
    "obsidian_rest_api_key",
)


APP_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Research Flow</title>
  <style>
    :root {
      --bg: #f7f1e7;
      --panel: #fffdf8;
      --ink: #201c17;
      --muted: #6d645b;
      --line: #d3c2ac;
      --accent: #b76635;
      --accent-2: #e8d1bd;
      --good: #2f6f4f;
      --bad: #983c2f;
      --shadow: 0 10px 30px rgba(63, 40, 19, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background:
        radial-gradient(circle at top left, #fff4df 0, transparent 28rem),
        linear-gradient(180deg, #f9f5ee 0%, #f3eadc 100%);
      color: var(--ink);
      font-family: "Avenir Next", "Helvetica Neue", sans-serif;
    }
    .shell {
      max-width: 1240px;
      margin: 0 auto;
      padding: 28px 22px 40px;
    }
    .hero {
      display: grid;
      grid-template-columns: 1.2fr 0.8fr;
      gap: 18px;
      align-items: stretch;
      margin-bottom: 18px;
    }
    .hero-card, .status-card, .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 22px;
      box-shadow: var(--shadow);
    }
    .hero-card {
      padding: 26px;
      background:
        linear-gradient(145deg, rgba(232, 209, 189, 0.55), rgba(255, 253, 248, 0.95)),
        var(--panel);
    }
    .eyebrow {
      font-size: 12px;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      color: var(--accent);
      margin-bottom: 12px;
      font-weight: 700;
    }
    h1 {
      margin: 0 0 10px;
      font-family: "Iowan Old Style", "Baskerville", serif;
      font-size: clamp(2rem, 4vw, 3.2rem);
      line-height: 1.02;
    }
    .hero p {
      margin: 0;
      color: var(--muted);
      line-height: 1.55;
      font-size: 15px;
    }
    .status-card {
      padding: 22px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      gap: 16px;
    }
    .status-pill {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      font-size: 13px;
      font-weight: 700;
      color: var(--good);
      background: #eef8f1;
      border: 1px solid #c7e0cf;
      border-radius: 999px;
      padding: 8px 12px;
      width: fit-content;
    }
    .status-pill[data-kind="error"] {
      color: var(--bad);
      background: #fbefec;
      border-color: #ebc2b9;
    }
    .status-line {
      font-size: 15px;
      color: var(--ink);
      line-height: 1.45;
      min-height: 3.2em;
    }
    .status-meta {
      font-size: 13px;
      color: var(--muted);
      line-height: 1.5;
    }
    .grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 18px;
      align-items: start;
    }
    .panel {
      padding: 18px;
    }
    .panel h2 {
      margin: 0 0 14px;
      font-family: "Iowan Old Style", "Baskerville", serif;
      font-size: 1.5rem;
    }
    .panel h3 {
      margin: 0 0 10px;
      font-size: 1rem;
    }
    .stack { display: grid; gap: 12px; }
    .field, .field-row {
      display: grid;
      gap: 6px;
    }
    .field-row {
      grid-template-columns: 1fr 1fr;
      gap: 12px;
    }
    label {
      font-size: 13px;
      font-weight: 700;
      color: var(--muted);
      letter-spacing: 0.02em;
    }
    input, textarea, select {
      width: 100%;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: #fffdfa;
      color: var(--ink);
      padding: 12px 13px;
      font: inherit;
    }
    textarea {
      min-height: 120px;
      resize: vertical;
      line-height: 1.5;
    }
    .dropzone {
      border: 1.5px dashed #d9b78f;
      border-radius: 18px;
      padding: 18px;
      background: linear-gradient(180deg, #fff8ef 0%, #fffdf9 100%);
    }
    .dropzone strong {
      display: block;
      margin-bottom: 8px;
      font-size: 1rem;
    }
    .dropzone p {
      margin: 0 0 14px;
      color: var(--muted);
      line-height: 1.5;
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 10px;
    }
    button {
      border: 0;
      border-radius: 999px;
      padding: 11px 16px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      background: var(--accent);
      color: white;
    }
    button.secondary {
      background: var(--accent-2);
      color: var(--ink);
    }
    button.ghost {
      background: white;
      color: var(--ink);
      border: 1px solid var(--line);
    }
    button:disabled {
      opacity: 0.6;
      cursor: wait;
    }
    .path-box, .log-box {
      border: 1px solid var(--line);
      border-radius: 14px;
      background: #fffdfa;
      padding: 12px 14px;
      color: var(--ink);
      line-height: 1.55;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .path-box {
      min-height: 3.2em;
    }
    .log-box {
      min-height: 280px;
      max-height: 380px;
      overflow: auto;
      font-family: "SF Mono", "Menlo", monospace;
      font-size: 13px;
    }
    .results {
      display: grid;
      gap: 10px;
      margin-top: 12px;
    }
    .result-item {
      border-left: 4px solid var(--accent);
      background: #fff8ef;
      padding: 10px 12px;
      border-radius: 12px;
    }
    .muted {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.55;
    }
    .footer-actions {
      display: flex;
      justify-content: flex-end;
      gap: 10px;
      margin-top: 14px;
    }
    @media (max-width: 960px) {
      .hero, .grid, .field-row {
        grid-template-columns: 1fr;
      }
      .shell { padding: 18px 14px 30px; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <div class="hero-card">
        <div class="eyebrow">Research Flow</div>
        <h1>PDF in. Zotero saved. Notes out.</h1>
        <p>
          This local browser app replaces the broken native Tk window on macOS.
          Upload one paper PDF, review the metadata, and run the full
          Zotero -> packet -> LLM -> Obsidian workflow from one place.
        </p>
      </div>
      <aside class="status-card">
        <div class="status-pill" id="status-pill">Ready</div>
        <div class="status-line" id="status-line">Waiting for a PDF upload.</div>
        <div class="status-meta">
          The selected PDF is imported into this project's <code>imports/</code> folder,
          then used as the source file for the pipeline.
        </div>
      </aside>
    </section>

    <section class="grid">
      <div class="panel stack">
        <h2>1. Connections</h2>
        <div class="field">
          <label for="config-path">Config File</label>
          <input id="config-path" />
        </div>
        <div class="field-row">
          <div class="field"><label>Zotero User ID</label><input id="zotero_user_id" /></div>
          <div class="field"><label>Zotero API Key</label><input id="zotero_api_key" type="password" /></div>
        </div>
        <div class="field-row">
          <div class="field"><label>Library Type</label><input id="zotero_library_type" /></div>
          <div class="field"><label>Zotero Desktop URL</label><input id="zotero_connector_url" /></div>
        </div>
        <input id="zotero_desktop_target_id" type="hidden" />
        <div class="field-row">
          <div class="field">
            <label>LLM Provider</label>
            <select id="llm_provider">
              <option value="openai">OpenAI</option>
              <option value="gemini">Gemini / Google AI Studio</option>
              <option value="deepseek">DeepSeek</option>
            </select>
          </div>
          <div class="field"><label>Cloud Collection Key (Optional Fallback)</label><input id="zotero_collection_key" /></div>
        </div>
        <div class="field-row">
          <div class="field llm-openai-field"><label>OpenAI API Key</label><input id="openai_api_key" type="password" /></div>
          <div class="field llm-openai-field"><label>OpenAI Model</label><input id="openai_model" /></div>
        </div>
        <div class="field-row">
          <div class="field llm-gemini-field"><label>Gemini / Google AI Studio API Key</label><input id="gemini_api_key" type="password" /></div>
          <div class="field llm-gemini-field"><label>Gemini Model</label><input id="gemini_model" /></div>
        </div>
        <div class="field-row">
          <div class="field llm-deepseek-field"><label>DeepSeek API Key</label><input id="deepseek_api_key" type="password" /></div>
          <div class="field llm-deepseek-field"><label>DeepSeek Model</label><input id="deepseek_model" /></div>
        </div>
        <div class="field-row">
          <div class="field"><label>Obsidian Vault Path</label><input id="obsidian_vault_path" /></div>
          <div class="field"><label>Packet Directory</label><input id="packet_dir" /></div>
        </div>
        <div class="field-row">
          <div class="field"><label>Obsidian REST URL</label><input id="obsidian_rest_url" /></div>
          <div class="field"><label>Obsidian REST API Key</label><input id="obsidian_rest_api_key" type="password" /></div>
        </div>
        <div class="field-row">
          <div class="field"><label>Note Subdirectory</label><input id="note_subdir" /></div>
          <div class="field"><label>Default Status</label><input id="default_status" /></div>
        </div>
        <div class="field"><label>Default Zotero Item Type</label><input id="default_item_type" /></div>
        <div class="actions">
          <button class="secondary" id="load-config-btn" type="button">Reload Config</button>
          <button id="save-config-btn" type="button">Save Config</button>
        </div>
      </div>

      <div class="panel stack">
        <h2>2. Zotero Desktop</h2>
        <div class="field">
          <label>Selected Zotero Library / Collection</label>
          <select id="zotero-target-select"></select>
        </div>
        <div class="path-box" id="zotero-target-summary">Open Zotero Desktop, then click “Load Zotero Libraries”.</div>
        <div class="actions">
          <button class="secondary" id="zotero-targets-btn" type="button">Load Zotero Libraries</button>
          <button id="zotero-import-btn" type="button">Import Into Zotero & Autofill</button>
        </div>
        <div class="muted">
          This reads Zotero Desktop’s own library tree. After you choose a target, the app can import the PDF into Zotero Desktop, let Zotero recognize the paper metadata, and use the recognized parent item to autofill this form.
        </div>
        <div class="dropzone">
          <strong>Choose one PDF to import into the workspace</strong>
          <p>
            This uses the browser's native file picker, then copies the file into this project's
            <code>imports/</code> folder automatically. If a Zotero target is selected, the app will also try to import it into Zotero Desktop right after upload.
          </p>
          <input id="pdf-file" type="file" accept="application/pdf,.pdf" />
          <div class="actions">
            <button id="upload-pdf-btn" type="button">Upload PDF</button>
            <button class="ghost" id="prefill-btn" type="button">Refresh Metadata</button>
            <button class="ghost" id="zotero-lookup-btn" type="button">Search Existing Library</button>
          </div>
        </div>
        <div class="field">
          <label>Imported PDF Path</label>
          <div class="path-box" id="pdf-path-box">No PDF uploaded yet.</div>
        </div>
        <div class="muted">
          The metadata order is now: PDF heuristics first, then Zotero Desktop recognition if available, and finally an existing-library cloud search as a fallback when you ask for it.
        </div>
      </div>
    </section>

    <section class="grid" style="margin-top: 18px;">
      <div class="panel stack" style="grid-column: 1 / -1;">
        <h2>Zotero Library Browser</h2>
        <div class="field-row">
          <div class="field" style="flex:1;">
            <input id="zotero-browse-query" placeholder="Search your Zotero library (leave empty for recent items)..." />
          </div>
          <button class="secondary" id="zotero-browse-btn" type="button" style="align-self:flex-end; margin-bottom: 2px;">Search Library</button>
        </div>
        <div id="zotero-duplicate-banner" style="display:none; padding:10px 14px; margin:8px 0; border-radius:6px; background:#fdf0e6; border:1px solid var(--accent); color:var(--ink); font-size:13px;">
          <strong style="color:var(--accent);">⚠ Possible duplicate detected</strong>
          <span id="zotero-duplicate-detail"></span>
          <button class="ghost" id="zotero-duplicate-use-btn" type="button" style="margin-left:8px; font-size:12px;">Use Existing Item</button>
          <button class="ghost" id="zotero-duplicate-dismiss-btn" type="button" style="margin-left:4px; font-size:12px;">Dismiss</button>
        </div>
        <div id="zotero-browse-results" style="max-height:320px; overflow-y:auto; border:1px solid var(--line); border-radius:6px; background:var(--panel);">
          <div style="padding:12px; color:var(--muted); font-size:13px;">Click "Search Library" to browse your Zotero papers. Requires Zotero credentials in Config.</div>
        </div>
        <div class="muted" style="margin-top:4px; font-size:12px;">
          Select a paper to auto-fill metadata and skip duplicate uploads. The browser tries Zotero Desktop's local API first, then falls back to the cloud API.
        </div>
      </div>
    </section>

    <section class="grid" style="margin-top: 18px;">
      <div class="panel stack">
        <h2>3. Paper Metadata</h2>
        <div class="field"><label>Title</label><input id="title" /></div>
        <div class="field"><label>Authors (comma-separated)</label><input id="authors" /></div>
        <div class="field-row">
          <div class="field"><label>Year</label><input id="year" /></div>
          <div class="field"><label>Journal / Venue</label><input id="journal" /></div>
        </div>
        <div class="field-row">
          <div class="field"><label>DOI</label><input id="doi" /></div>
          <div class="field"><label>URL</label><input id="url" /></div>
        </div>
        <div class="field-row">
          <div class="field"><label>Tags (comma-separated)</label><input id="tags" /></div>
          <div class="field"><label>Status</label><input id="status" /></div>
        </div>
        <div class="field"><label>Item Type</label><input id="item_type" /></div>
      </div>

      <div class="panel stack">
        <h2>4. Understanding Input</h2>
        <div class="field">
          <label>Abstract</label>
          <textarea id="abstract"></textarea>
        </div>
        <div class="field">
          <label>Annotation Summary</label>
          <textarea id="annotation_text"></textarea>
        </div>
      </div>
    </section>

    <section class="grid" style="margin-top: 18px;">
      <div class="panel stack">
        <h2>5. Run Pipeline</h2>
        <p class="muted">
          If you already imported and recognized the PDF through Zotero Desktop, this reuses that Zotero item instead of creating a duplicate. Then it writes the <code>.paper.json</code> packet,
          calls the LLM, and generates the final Obsidian note.
        </p>
        <div class="field">
          <label for="reading_mode">Reading Mode</label>
          <select id="reading_mode">
            <option value="legacy">Single-Pass (Legacy)</option>
            <option value="three-phase" selected>Three-Phase (粗读 → 精读 → 讨论)</option>
          </select>
          <p class="muted" style="margin-top:4px; font-size:12px;">
            Three-Phase mode produces a deeper analysis with algorithm decomposition, structured experiment results, and Socratic open questions.
          </p>
        </div>
        <div class="actions">
          <button id="run-btn" type="button">Run Pipeline</button>
        </div>
        <div class="results" id="results"></div>
      </div>

      <div class="panel stack">
        <h2>Progress Log</h2>
        <div class="log-box" id="log-box">Ready.</div>
      </div>
    </section>
  </div>

  <script>
    const configFields = [
      "zotero_user_id", "zotero_api_key", "zotero_library_type", "zotero_collection_key",
      "zotero_connector_url", "zotero_desktop_target_id",
      "llm_provider", "openai_api_key", "openai_model", "gemini_api_key", "gemini_model",
      "deepseek_api_key", "deepseek_model",
      "obsidian_vault_path", "obsidian_rest_url",
      "obsidian_rest_api_key", "packet_dir", "note_subdir", "default_item_type", "default_status"
    ];
    const secretFields = ["zotero_api_key", "openai_api_key", "gemini_api_key", "deepseek_api_key", "obsidian_rest_api_key"];
    const paperFields = [
      "title", "authors", "year", "journal", "doi", "url", "tags", "status", "item_type", "abstract", "annotation_text"
    ];
    let currentPdfPath = "";
    let currentJobId = null;
    let pollTimer = null;
    let currentZoteroItemKey = "";
    let currentZoteroAttachmentKey = "";
    let currentZoteroTargetId = "";
    let currentZoteroTargets = [];
    let zoteroLocalApiEnabled = false;
    const rememberedSecrets = {};

    function el(id) { return document.getElementById(id); }

    function setStatus(text, kind = "info") {
      el("status-line").textContent = text;
      const pill = el("status-pill");
      pill.textContent = kind === "error" ? "Needs Attention" : kind === "running" ? "Working" : "Ready";
      pill.dataset.kind = kind === "error" ? "error" : "";
    }

    function appendLog(text) {
      const box = el("log-box");
      const previous = box.textContent.trim();
      box.textContent = previous ? previous + "\\n" + text : text;
      box.scrollTop = box.scrollHeight;
    }

    function escapeHtml(text) {
      return String(text)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
    }

    function setTargetId(targetId) {
      currentZoteroTargetId = targetId || "";
      el("zotero_desktop_target_id").value = currentZoteroTargetId;
      if (el("zotero-target-select")) {
        el("zotero-target-select").value = currentZoteroTargetId;
      }
    }

    function updateTargetSummary(message = "") {
      const summary = el("zotero-target-summary");
      const selected = currentZoteroTargets.find((target) => target.id === currentZoteroTargetId);
      const localApiLabel = zoteroLocalApiEnabled ? "Local API ready for instant metadata reads." : "Local API not enabled; fallback metadata reads may depend on cloud sync.";
      if (selected) {
        const libraryMode = selected.id.startsWith("L") ? "Library root" : "Collection";
        summary.innerHTML = `<strong>${escapeHtml(selected.name)}</strong><br>${libraryMode}. ${localApiLabel}${message ? `<br>${escapeHtml(message)}` : ""}`;
        return;
      }
      summary.textContent = message || "Open Zotero Desktop, then click “Load Zotero Libraries”.";
    }

    function renderZoteroTargets(payload) {
      currentZoteroTargets = payload.targets || [];
      zoteroLocalApiEnabled = Boolean(payload.local_api_enabled);
      const select = el("zotero-target-select");
      select.innerHTML = "";

      if (!currentZoteroTargets.length) {
        const option = document.createElement("option");
        option.value = "";
        option.textContent = "No editable Zotero libraries found";
        select.appendChild(option);
        setTargetId("");
        updateTargetSummary("Zotero is running, but no editable libraries or collections were returned.");
        return;
      }

      for (const target of currentZoteroTargets) {
        const option = document.createElement("option");
        option.value = target.id;
        const indent = "  ".repeat(target.level || 0);
        const recent = target.recent ? " • recent" : "";
        option.textContent = `${indent}${target.name}${recent}`;
        select.appendChild(option);
      }

      const savedTargetId = el("zotero_desktop_target_id").value.trim();
      const preferredTargetId = currentZoteroTargets.some((target) => target.id === savedTargetId)
        ? savedTargetId
        : currentZoteroTargets.some((target) => target.id === payload.selected_target_id)
          ? payload.selected_target_id
          : currentZoteroTargets[0].id;
      setTargetId(preferredTargetId);
      updateTargetSummary();
    }

    function clearResults() {
      el("results").innerHTML = "";
    }

    function refreshProviderFields() {
      const provider = el("llm_provider").value || "openai";
      const openaiFields = document.querySelectorAll(".llm-openai-field");
      const geminiFields = document.querySelectorAll(".llm-gemini-field");
      const deepseekFields = document.querySelectorAll(".llm-deepseek-field");
      for (const field of openaiFields) {
        field.style.display = provider === "openai" ? "" : "none";
      }
      for (const field of geminiFields) {
        field.style.display = provider === "gemini" ? "" : "none";
      }
      for (const field of deepseekFields) {
        field.style.display = provider === "deepseek" ? "" : "none";
      }
    }

    function applyPrefill(prefill) {
      el("title").value = prefill.title || "";
      el("authors").value = (prefill.authors || []).join(", ");
      el("year").value = prefill.year || "";
      el("journal").value = prefill.journal || "";
      el("doi").value = prefill.doi || "";
      el("url").value = prefill.url || "";
      if (Object.prototype.hasOwnProperty.call(prefill, "zotero_item_key")) {
        currentZoteroItemKey = prefill.zotero_item_key || "";
      }
      if (Object.prototype.hasOwnProperty.call(prefill, "zotero_attachment_key")) {
        currentZoteroAttachmentKey = prefill.zotero_attachment_key || "";
      }
      if (!el("abstract").value.trim() && prefill.abstract) {
        el("abstract").value = prefill.abstract;
      } else if (prefill.abstract) {
        el("abstract").value = prefill.abstract;
      }
    }

    function showResults(result) {
      const entries = [
        ["Citekey", result.citekey],
        ["Mode", result.reading_mode === "three-phase" ? "Three-Phase (粗读 → 精读 → 讨论)" : "Single-Pass (Legacy)"],
        ["Packet", result.packet_path],
        ["Analysis", result.analysis_path],
        ["Note", result.note_path || result.obsidian_target]
      ];
      if (result.skim_path) entries.push(["Skim Result", result.skim_path]);
      if (result.deep_read_path) entries.push(["Deep Read Result", result.deep_read_path]);
      if (result.discussion_path) entries.push(["Discussion Result", result.discussion_path]);
      el("results").innerHTML = entries.map(([label, value]) => `
        <div class="result-item"><strong>${label}</strong><br>${value || ""}</div>
      `).join("");
    }

    function getConfigPayload() {
      el("zotero_desktop_target_id").value = currentZoteroTargetId;
      const config = {};
      for (const field of configFields) {
        const value = el(field).value.trim();
        if (secretFields.includes(field)) {
          if (value !== "") {
            rememberedSecrets[field] = value;
            config[field] = value;
          } else if (rememberedSecrets[field]) {
            config[field] = rememberedSecrets[field];
          } else {
            config[field] = null;
          }
          continue;
        }
        config[field] = value === "" ? null : value;
      }
      return {
        config_path: el("config-path").value.trim() || "research-flow.config.json",
        config
      };
    }

    function getRunPayload() {
      const configPayload = getConfigPayload();
      const paper = {};
      for (const field of paperFields) {
        paper[field] = el(field).value.trim();
      }
      paper.pdf_path = currentPdfPath;
      paper.zotero_item_key = currentZoteroItemKey || "";
      paper.zotero_attachment_key = currentZoteroAttachmentKey || "";
      paper.zotero_target_id = currentZoteroTargetId || "";
      paper.reading_mode = el("reading_mode").value || "legacy";
      return { ...configPayload, paper };
    }

    function hasZoteroCredentials() {
      return Boolean(el("zotero_user_id").value.trim() && el("zotero_api_key").value.trim());
    }

    async function loadZoteroTargets() {
      setStatus("Loading Zotero Desktop libraries...", "running");
      const response = await fetch("/api/zotero_targets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(getConfigPayload())
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "Failed to load Zotero Desktop libraries");
      }
      renderZoteroTargets(payload);
      setStatus("Zotero Desktop libraries loaded.");
      appendLog(`Loaded ${currentZoteroTargets.length} Zotero target(s) from Zotero Desktop.`);
    }

    async function loadConfig() {
      setStatus("Loading config...");
      const response = await fetch("/api/config");
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "Failed to load config");
      }
      el("config-path").value = payload.config_path;
      for (const field of configFields) {
        const value = payload.config[field] || "";
        el(field).value = value;
        if (secretFields.includes(field) && value) {
          rememberedSecrets[field] = value;
        }
      }
      if (!el("llm_provider").value) {
        el("llm_provider").value = "openai";
      }
      refreshProviderFields();
      setTargetId(payload.config.zotero_desktop_target_id || "");
      if (!el("status").value) {
        el("status").value = payload.config.default_status || "inbox";
      }
      if (!el("item_type").value) {
        el("item_type").value = payload.config.default_item_type || "journalArticle";
      }
      setStatus("Config loaded.");
      appendLog("Config loaded.");
    }

    async function saveConfig() {
      setStatus("Saving config...");
      const response = await fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(getConfigPayload())
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "Failed to save config");
      }
      setStatus(`Config saved to ${payload.config_path}`);
      appendLog(`Config saved to ${payload.config_path}`);
    }

    async function importIntoZoteroDesktop(isAutomatic = false) {
      if (!currentPdfPath) {
        throw new Error("Upload a PDF first.");
      }
      if (!currentZoteroTargetId) {
        throw new Error("Load Zotero Desktop libraries and choose a target first.");
      }

      const label = isAutomatic
        ? "Importing PDF into Zotero Desktop and waiting for recognition..."
        : "Importing into Zotero Desktop and waiting for recognition...";
      setStatus(label, "running");
      appendLog(label);

      const response = await fetch("/api/zotero_import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(getRunPayload())
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "Zotero Desktop import failed");
      }

      if (payload.target_id) {
        setTargetId(payload.target_id);
      }
      applyPrefill(payload.prefill || {});
      updateTargetSummary(
        payload.local_api_enabled
          ? ""
          : "Enable Zotero Local API in Zotero’s Advanced preferences for immediate full metadata reads."
      );

      if (payload.recognized) {
        const recognizedTitle = payload.recognized_item?.title || el("title").value || "Untitled item";
        appendLog(`Zotero Desktop recognized: ${recognizedTitle}`);
      } else {
        appendLog("Zotero Desktop imported the PDF, but no recognized parent item was returned yet.");
      }

      if (currentZoteroItemKey) {
        appendLog(`Using Zotero item ${currentZoteroItemKey} from ${payload.metadata_source}.`);
      } else {
        appendLog(`Metadata source: ${payload.metadata_source}.`);
      }

      if (payload.metadata_source === "zotero_local_api") {
        setStatus("Metadata updated from Zotero Desktop.");
      } else if (payload.metadata_source === "zotero_web_api") {
        setStatus("Metadata updated from Zotero via synced library search.");
      } else if (payload.recognized) {
        setStatus("PDF imported into Zotero Desktop; only the recognized title is available right now.");
      } else {
        setStatus("PDF imported into Zotero Desktop. Metadata is still using the local PDF prefill.");
      }
    }

    async function uploadPdf() {
      const fileInput = el("pdf-file");
      if (!fileInput.files.length) {
        throw new Error("Choose a PDF first.");
      }
      const formData = new FormData();
      formData.append("file", fileInput.files[0]);
      setStatus("Uploading PDF into workspace...", "running");
      const response = await fetch("/api/upload", {
        method: "POST",
        body: formData
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "Upload failed");
      }
      currentPdfPath = payload.pdf_path;
      currentZoteroItemKey = "";
      currentZoteroAttachmentKey = "";
      el("pdf-path-box").textContent = payload.pdf_path;
      applyPrefill(payload.prefill);
      if (!el("status").value) el("status").value = el("default_status").value || "inbox";
      if (!el("item_type").value) el("item_type").value = el("default_item_type").value || "journalArticle";
      setStatus("PDF uploaded and metadata prefilled.");
      appendLog(`PDF imported to ${payload.pdf_path}`);
      // Check for duplicates in Zotero before importing
      const prefillTitle = el("title").value.trim();
      const prefillAuthors = el("authors").value.trim() ? el("authors").value.trim().split(",").map(a => a.trim()) : [];
      const prefillYear = el("year").value.trim();
      const prefillDoi = el("doi").value.trim();
      const prefillFilename = payload.pdf_path ? payload.pdf_path.split("/").pop() : "";
      await checkZoteroDuplicate(prefillTitle, prefillAuthors, prefillYear, prefillDoi, prefillFilename);
      if (currentZoteroTargetId) {
        try {
          await importIntoZoteroDesktop(true);
        } catch (error) {
          appendLog(`Zotero Desktop import skipped: ${error.message || String(error)}`);
          setStatus("PDF uploaded. Zotero Desktop import needs attention.");
        }
      } else if (hasZoteroCredentials()) {
        await tryZoteroLookup(true);
      } else {
        appendLog("Zotero import skipped because no Zotero Desktop target is selected.");
      }
    }

    async function refreshPrefill() {
      if (!currentPdfPath) {
        throw new Error("Upload a PDF first.");
      }
      setStatus("Refreshing metadata...", "running");
      const response = await fetch("/api/prefill", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pdf_path: currentPdfPath })
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "Prefill failed");
      }
      const rememberedItemKey = currentZoteroItemKey;
      const rememberedAttachmentKey = currentZoteroAttachmentKey;
      applyPrefill(payload.prefill);
      currentZoteroItemKey = rememberedItemKey;
      currentZoteroAttachmentKey = rememberedAttachmentKey;
      setStatus("Metadata refreshed from PDF.");
      appendLog("Metadata refreshed from PDF.");
      if (hasZoteroCredentials()) {
        await tryZoteroLookup(true);
      }
    }

    async function tryZoteroLookup(isAutomatic = false) {
      if (!currentPdfPath) {
        throw new Error("Upload a PDF first.");
      }
      if (!hasZoteroCredentials()) {
        if (!isAutomatic) {
          throw new Error("Fill in Zotero User ID and Zotero API Key first.");
        }
        return;
      }
      const label = isAutomatic ? "Trying Zotero metadata lookup..." : "Looking up metadata in Zotero...";
      setStatus(label, "running");
      appendLog(label);
      const response = await fetch("/api/zotero_lookup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(getRunPayload())
      });
      const payload = await response.json();
      if (!response.ok) {
        if (isAutomatic) {
          appendLog(`Zotero lookup skipped: ${payload.error || "unknown error"}`);
          setStatus("Using local PDF metadata because Zotero lookup failed.");
          return;
        }
        throw new Error(payload.error || "Zotero lookup failed");
      }
      if (!payload.found) {
        const reason = payload.reason || "No match found in Zotero.";
        appendLog(reason);
        setStatus(isAutomatic ? "Using local PDF metadata." : reason);
        return;
      }
      applyPrefill(payload.prefill);
      if (payload.zotero_item_key) {
        appendLog(`Matched Zotero item ${payload.zotero_item_key}.`);
      } else {
        appendLog("Matched metadata from Zotero.");
      }
      setStatus("Metadata updated from Zotero.");
    }

    let lastDuplicateMatch = null;

    function renderBrowseResults(items) {
      const container = el("zotero-browse-results");
      if (!items.length) {
        container.innerHTML = '<div style="padding:12px; color:var(--muted); font-size:13px;">No items found.</div>';
        return;
      }
      const rows = items.map((item, index) => {
        const authorsStr = (item.authors || []).slice(0, 3).join(", ") + ((item.authors || []).length > 3 ? " et al." : "");
        const yearStr = item.year ? ` (${escapeHtml(item.year)})` : "";
        const journalStr = item.journal ? `<span style="color:var(--muted); font-size:12px;"> — ${escapeHtml(item.journal)}</span>` : "";
        const hasPdf = item.filename ? '<span style="color:var(--good); font-size:11px; margin-left:6px;" title="Has PDF attachment">📎 PDF</span>' : "";
        return `<div class="zotero-browse-item" data-index="${index}" style="padding:8px 12px; border-bottom:1px solid var(--line); cursor:pointer; transition:background .15s;" onmouseenter="this.style.background='var(--accent-2)'" onmouseleave="this.style.background=''">
          <div style="font-size:14px; font-weight:500;">${escapeHtml(item.title || "Untitled")}${hasPdf}</div>
          <div style="font-size:12px; color:var(--muted);">${escapeHtml(authorsStr)}${yearStr}${journalStr}</div>
        </div>`;
      }).join("");
      container.innerHTML = rows;

      container.querySelectorAll(".zotero-browse-item").forEach((row) => {
        row.addEventListener("click", async () => {
          const idx = parseInt(row.dataset.index, 10);
          const item = items[idx];
          if (!item || !item.zotero_item_key) return;

          // Visual feedback
          container.querySelectorAll(".zotero-browse-item").forEach(r => {
            r.style.background = "";
            r.style.borderLeft = "";
          });
          row.style.background = "var(--accent-2)";
          row.style.borderLeft = "3px solid var(--accent)";

          setStatus("Fetching paper & PDF from Zotero...", "running");
          appendLog(`Selecting: ${item.title || "Untitled"}...`);

          try {
            const configPayload = getConfigPayload();
            const response = await fetch("/api/zotero_select_paper", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ ...configPayload, item_key: item.zotero_item_key })
            });
            const payload = await response.json();
            if (!response.ok) {
              throw new Error(payload.error || "Failed to select paper from Zotero");
            }

            const meta = payload.metadata || {};
            applyPrefill({
              title: meta.title,
              authors: meta.authors,
              year: meta.year,
              journal: meta.journal,
              doi: meta.doi,
              url: meta.url,
              abstract: meta.abstract,
              zotero_item_key: meta.zotero_item_key,
            });
            currentZoteroItemKey = meta.zotero_item_key || "";

            if (payload.pdf_path) {
              currentPdfPath = payload.pdf_path;
              el("pdf-path-box").textContent = payload.pdf_path;
              setStatus(`Ready: ${meta.title || "Untitled"} (PDF downloaded from Zotero)`);
              appendLog(`PDF downloaded from Zotero → ${payload.pdf_path}`);
            } else {
              setStatus(`Selected: ${meta.title || "Untitled"} (no PDF in Zotero — upload one manually to run pipeline)`);
              appendLog("No PDF attachment found in Zotero for this item.");
            }

            if (!el("status").value) el("status").value = el("default_status").value || "inbox";
            if (!el("item_type").value) el("item_type").value = meta.item_type || el("default_item_type").value || "journalArticle";
          } catch (err) {
            setStatus(err.message || String(err), "error");
            appendLog(`Error: ${err.message || String(err)}`);
          }
        });
      });
    }

    async function browseZoteroLibrary() {
      const query = el("zotero-browse-query").value.trim();
      setStatus("Searching Zotero library...", "running");
      const configPayload = getConfigPayload();
      const response = await fetch("/api/zotero_browse", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...configPayload, query, limit: 25 })
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "Failed to browse Zotero library");
      }
      renderBrowseResults(payload.items || []);
      setStatus(`Found ${payload.count || 0} item(s) in Zotero.`);
      appendLog(`Zotero library search: ${payload.count || 0} result(s) for "${query || "(recent items)"}".`);
    }

    async function checkZoteroDuplicate(title, authors, year, doi, pdfFilename) {
      if (!hasZoteroCredentials()) return;
      if (!title) return;
      try {
        const configPayload = getConfigPayload();
        const response = await fetch("/api/zotero_check_duplicate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            ...configPayload,
            title,
            authors: (authors || []).join(", "),
            year,
            doi,
            pdf_filename: pdfFilename
          })
        });
        const payload = await response.json();
        if (!response.ok || !payload.duplicate) {
          el("zotero-duplicate-banner").style.display = "none";
          lastDuplicateMatch = null;
          return;
        }
        lastDuplicateMatch = payload.match;
        const matchTitle = payload.match.title || "Untitled";
        const matchYear = payload.match.year ? ` (${payload.match.year})` : "";
        el("zotero-duplicate-detail").textContent = ` — "${matchTitle}"${matchYear} already exists in your Zotero library.`;
        el("zotero-duplicate-banner").style.display = "block";
        appendLog(`Duplicate detected: "${matchTitle}" (item key: ${payload.match.zotero_item_key || "?"}).`);
      } catch (err) {
        // Silent failure for duplicate check — non-critical
      }
    }

    function useExistingDuplicate() {
      if (!lastDuplicateMatch) return;
      applyPrefill({
        title: lastDuplicateMatch.title,
        authors: lastDuplicateMatch.authors,
        year: lastDuplicateMatch.year,
        journal: lastDuplicateMatch.journal,
        doi: lastDuplicateMatch.doi,
        zotero_item_key: lastDuplicateMatch.zotero_item_key,
      });
      currentZoteroItemKey = lastDuplicateMatch.zotero_item_key || "";
      el("zotero-duplicate-banner").style.display = "none";
      setStatus("Using existing Zotero item instead of creating a duplicate.");
      appendLog(`Using existing Zotero item ${lastDuplicateMatch.zotero_item_key || "?"}.`);
      lastDuplicateMatch = null;
    }

    async function runPipeline() {
      if (!currentPdfPath) {
        throw new Error("Upload a PDF first.");
      }
      clearResults();
      setStatus("Starting pipeline...", "running");
      appendLog("Starting pipeline...");
      el("run-btn").disabled = true;
      const response = await fetch("/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(getRunPayload())
      });
      const payload = await response.json();
      if (!response.ok) {
        el("run-btn").disabled = false;
        throw new Error(payload.error || "Pipeline failed to start");
      }
      currentJobId = payload.job_id;
      pollJob();
    }

    async function pollJob() {
      if (!currentJobId) return;
      const response = await fetch(`/api/job?id=${encodeURIComponent(currentJobId)}`);
      const payload = await response.json();
      if (!response.ok) {
        setStatus(payload.error || "Failed to poll job", "error");
        el("run-btn").disabled = false;
        return;
      }
      el("log-box").textContent = payload.logs.join("\\n") || "Waiting for logs...";
      el("log-box").scrollTop = el("log-box").scrollHeight;
      if (payload.status === "done") {
        setStatus("Pipeline complete.");
        showResults(payload.result);
        el("run-btn").disabled = false;
        currentJobId = null;
        return;
      }
      if (payload.status === "error") {
        setStatus(payload.error || "Pipeline failed", "error");
        el("run-btn").disabled = false;
        currentJobId = null;
        return;
      }
      setStatus("Pipeline is running...", "running");
      pollTimer = setTimeout(pollJob, 1200);
    }

    function withErrorHandling(fn) {
      return async () => {
        try {
          await fn();
        } catch (error) {
          setStatus(error.message || String(error), "error");
          appendLog(`Error: ${error.message || String(error)}`);
          el("run-btn").disabled = false;
        }
      };
    }

    window.addEventListener("load", async () => {
      for (const field of secretFields) {
        el(field).addEventListener("input", () => {
          const value = el(field).value.trim();
          if (value) {
            rememberedSecrets[field] = value;
          }
        });
      }
      el("llm_provider").addEventListener("change", refreshProviderFields);
      el("load-config-btn").addEventListener("click", withErrorHandling(loadConfig));
      el("save-config-btn").addEventListener("click", withErrorHandling(saveConfig));
      el("zotero-targets-btn").addEventListener("click", withErrorHandling(loadZoteroTargets));
      el("zotero-import-btn").addEventListener("click", withErrorHandling(() => importIntoZoteroDesktop(false)));
      el("zotero-target-select").addEventListener("change", (event) => {
        setTargetId(event.target.value);
        updateTargetSummary();
      });
      el("upload-pdf-btn").addEventListener("click", withErrorHandling(uploadPdf));
      el("prefill-btn").addEventListener("click", withErrorHandling(refreshPrefill));
      el("zotero-lookup-btn").addEventListener("click", withErrorHandling(() => tryZoteroLookup(false)));
      el("run-btn").addEventListener("click", withErrorHandling(runPipeline));
      el("zotero-browse-btn").addEventListener("click", withErrorHandling(browseZoteroLibrary));
      el("zotero-browse-query").addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          withErrorHandling(browseZoteroLibrary)();
        }
      });
      el("zotero-duplicate-use-btn").addEventListener("click", useExistingDuplicate);
      el("zotero-duplicate-dismiss-btn").addEventListener("click", () => {
        el("zotero-duplicate-banner").style.display = "none";
        lastDuplicateMatch = null;
      });
      try {
        refreshProviderFields();
        await loadConfig();
        try {
          await loadZoteroTargets();
        } catch (targetError) {
          appendLog(`Zotero Desktop libraries not loaded yet: ${targetError.message || String(targetError)}`);
          updateTargetSummary("Open Zotero Desktop and click “Load Zotero Libraries”.");
        }
      } catch (error) {
        setStatus(error.message || String(error), "error");
        appendLog(`Error: ${error.message || String(error)}`);
      }
    });
  </script>
</body>
</html>
"""


@dataclass
class JobState:
    job_id: str
    status: str = "queued"
    logs: List[str] = field(default_factory=list)
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


def _dedupe_destination(workspace_dir: Path, filename: str) -> Path:
    safe_name = Path(filename).name or "paper.pdf"
    destination = workspace_dir / safe_name
    if not destination.exists():
        return destination
    stem = destination.stem
    suffix = destination.suffix or ".pdf"
    counter = 2
    while True:
        candidate = workspace_dir / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def save_uploaded_pdf(filename: str, content: bytes, workspace_dir: Path = WORKSPACE_IMPORT_DIR) -> Path:
    workspace_dir.mkdir(parents=True, exist_ok=True)
    destination = _dedupe_destination(workspace_dir, filename)
    destination.write_bytes(content)
    return destination.resolve()


def _find_existing_import(filename: str, expected_size: int, workspace_dir: Path = WORKSPACE_IMPORT_DIR) -> Optional[Path]:
    """Return the path of an already-imported PDF if one with the same name and size exists."""
    safe_name = Path(filename).name or "paper.pdf"
    candidate = workspace_dir / safe_name
    if candidate.is_file():
        try:
            if candidate.stat().st_size == expected_size:
                return candidate.resolve()
        except OSError:
            pass
    # Also check dedupe variants like filename-2.pdf, filename-3.pdf
    stem = Path(safe_name).stem
    suffix = Path(safe_name).suffix or ".pdf"
    for counter in range(2, 20):
        variant = workspace_dir / f"{stem}-{counter}{suffix}"
        if not variant.exists():
            break
        try:
            if variant.stat().st_size == expected_size:
                return variant.resolve()
        except OSError:
            continue
    return None


def request_from_payload(payload: Dict[str, Any], config: AppConfig) -> IngestRequest:
    paper = payload.get("paper")
    if not isinstance(paper, dict):
        raise ValueError("paper payload must be an object")
    pdf_path = Path(str(paper.get("pdf_path") or "")).expanduser().resolve()
    return IngestRequest(
        pdf_path=pdf_path,
        title=str(paper.get("title") or "").strip(),
        authors=_split_csv(str(paper.get("authors") or "")),
        year=_optional_string(paper.get("year")),
        journal=_optional_string(paper.get("journal")),
        doi=_optional_string(paper.get("doi")),
        url=_optional_string(paper.get("url")),
        abstract=_optional_string(paper.get("abstract")),
        annotation_text=_optional_string(paper.get("annotation_text")),
        tags=_split_csv(str(paper.get("tags") or "")),
        status=_optional_string(paper.get("status")) or config.default_status,
        item_type=_optional_string(paper.get("item_type")) or config.default_item_type,
        zotero_item_key=_optional_string(paper.get("zotero_item_key")),
        zotero_attachment_key=_optional_string(paper.get("zotero_attachment_key")),
        zotero_target_id=_optional_string(paper.get("zotero_target_id"))
        or config.zotero_desktop_target_id,
        reading_mode=_optional_string(paper.get("reading_mode")) or "legacy",
    )


def _optional_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _split_csv(value: str) -> List[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _prefill_to_dict(request: IngestRequest) -> Dict[str, Any]:
    return {
        "pdf_path": str(request.pdf_path),
        "title": request.title,
        "authors": request.authors,
        "year": request.year,
        "journal": request.journal,
        "doi": request.doi,
        "url": request.url,
        "abstract": request.abstract,
        "zotero_item_key": request.zotero_item_key,
        "zotero_attachment_key": request.zotero_attachment_key,
    }


def _merge_request_with_metadata(request: IngestRequest, metadata: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "pdf_path": str(request.pdf_path),
        "zotero_item_key": metadata.get("zotero_item_key"),
        "zotero_attachment_key": metadata.get("zotero_attachment_key"),
        "title": metadata.get("title") or request.title,
        "authors": metadata.get("authors") or request.authors,
        "year": metadata.get("year") or request.year,
        "journal": metadata.get("journal") or request.journal,
        "doi": metadata.get("doi") or request.doi,
        "url": metadata.get("url") or request.url,
        "abstract": metadata.get("abstract") or request.abstract,
    }


def lookup_zotero_prefill(config: AppConfig, request: IngestRequest) -> Optional[Dict[str, Any]]:
    config.require_zotero()
    client = ZoteroClient(config)
    match = client.lookup_best_metadata(
        title=request.title,
        authors=request.authors,
        year=request.year,
        doi=request.doi,
    )
    if not match:
        return None
    return _merge_request_with_metadata(request, match)


def browse_zotero_library(config: AppConfig, query: str = "", limit: int = 25) -> List[Dict[str, Any]]:
    """Browse / search items in the Zotero library.

    Tries the local Desktop API first (faster), falls back to web API.
    """
    try:
        desktop = ZoteroDesktopClient(config)
        desktop.ping()
        items = desktop.browse_local_items(query, limit=limit)
        if items:
            return items
    except (ZoteroDesktopError, Exception):
        pass

    if config.zotero_user_id and config.zotero_api_key:
        client = ZoteroClient(config)
        return client.browse_items(query, limit=limit)

    return []


def check_zotero_duplicate(
    config: AppConfig,
    *,
    title: Optional[str],
    authors: Optional[List[str]] = None,
    year: Optional[str] = None,
    doi: Optional[str] = None,
    pdf_filename: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Check if a paper already exists in the Zotero library."""
    if not config.zotero_user_id or not config.zotero_api_key:
        return None
    client = ZoteroClient(config)
    return client.check_duplicate(
        title=title, authors=authors, year=year, doi=doi, pdf_filename=pdf_filename,
    )


def select_zotero_paper(config: AppConfig, item_key: str) -> Dict[str, Any]:
    """Select a paper from Zotero: fetch metadata and download the PDF attachment.

    Tries the local Desktop API first (works even before cloud sync),
    then falls back to the Web API.
    """
    metadata: Optional[Dict[str, Any]] = None
    pdf_result: Optional[tuple] = None
    source = "web_api"

    # --- Try local Desktop API first ---
    try:
        desktop = ZoteroDesktopClient(config)
        desktop.ping()
        metadata = desktop.get_local_item_metadata(item_key)
        if metadata:
            source = "local_api"
        pdf_result = desktop.get_local_item_pdf(item_key)
    except (ZoteroDesktopError, Exception):
        pass

    # --- Fall back to Web API for metadata ---
    if not metadata and config.zotero_user_id and config.zotero_api_key:
        client = ZoteroClient(config)
        metadata = client.get_item_metadata(item_key)
        source = "web_api"

    if not metadata:
        raise ValueError(f"Could not fetch metadata for Zotero item {item_key}")

    # --- Fall back to Web API for PDF ---
    if not pdf_result and config.zotero_user_id and config.zotero_api_key:
        try:
            client = ZoteroClient(config)
            pdf_result = client.get_item_pdf(item_key)
        except (ZoteroAPIError, Exception):
            pass

    pdf_path: Optional[str] = None
    if pdf_result:
        filename, content = pdf_result
        # Check if the same file already exists in imports/ to avoid duplicates
        existing = _find_existing_import(filename, len(content))
        if existing:
            pdf_path = str(existing)
        else:
            saved = save_uploaded_pdf(filename, content)
            pdf_path = str(saved)

    return {
        "metadata": metadata,
        "pdf_path": pdf_path,
        "has_pdf": pdf_path is not None,
        "source": source,
    }


def get_zotero_desktop_targets(config: AppConfig) -> Dict[str, Any]:
    client = ZoteroDesktopClient(config)
    payload = client.get_targets()
    selected_collection_id = payload.get("id")
    selected_target_id = (
        f"C{selected_collection_id}"
        if selected_collection_id is not None
        else f"L{payload.get('libraryID')}"
    )
    payload["selected_target_id"] = selected_target_id
    payload["local_api_enabled"] = client.get_local_library_version() is not None
    return payload


def import_pdf_via_zotero_desktop(config: AppConfig, request: IngestRequest) -> Dict[str, Any]:
    client = ZoteroDesktopClient(config)
    targets = client.get_targets()
    target_id = request.zotero_target_id
    if not target_id:
        selected_collection_id = targets.get("id")
        target_id = (
            f"C{selected_collection_id}"
            if selected_collection_id is not None
            else f"L{targets.get('libraryID')}"
        )

    local_version = client.get_local_library_version()
    session_id = uuid.uuid4().hex[:12]
    source_url = request.url or request.pdf_path.resolve().as_uri()
    client.save_standalone_attachment(
        request.pdf_path,
        session_id=session_id,
        title=request.pdf_path.name,
        url=source_url,
    )
    if target_id:
        client.update_session(session_id=session_id, target_id=target_id)

    recognized = client.wait_for_recognized_item(session_id)
    if target_id:
        client.update_session(session_id=session_id, target_id=target_id)

    recognized_title = str((recognized or {}).get("title") or request.title or request.pdf_path.stem)
    metadata: Optional[Dict[str, Any]] = None
    metadata_source: Optional[str] = None

    if local_version is not None:
        metadata = client.find_best_local_item_by_title_and_attachment(
            title=recognized_title,
            pdf_path=request.pdf_path,
            since=local_version,
        )
        if metadata:
            metadata_source = "zotero_local_api"

    if not metadata and config.zotero_user_id and config.zotero_api_key:
        metadata = ZoteroClient(config).find_best_item_by_title_and_attachment(
            title=recognized_title,
            pdf_path=request.pdf_path,
        )
        if metadata:
            metadata_source = "zotero_web_api"

    if metadata:
        prefill = _merge_request_with_metadata(request, metadata)
    else:
        prefill = _prefill_to_dict(request)
        prefill["title"] = recognized_title
        prefill["zotero_item_key"] = None
        prefill["zotero_attachment_key"] = None

    return {
        "target_id": target_id,
        "recognized": bool(recognized),
        "recognized_item": recognized or {},
        "prefill": prefill,
        "metadata_source": metadata_source or ("recognized_title_only" if recognized else "pdf_only"),
        "local_api_enabled": local_version is not None,
    }


def merge_config_with_existing(config_path: Path, incoming: AppConfig) -> AppConfig:
    try:
        existing = AppConfig.from_path(config_path)
    except Exception:
        existing = AppConfig()

    merged = incoming.as_dict()
    for field in SECRET_CONFIG_FIELDS:
        if not merged.get(field):
            merged[field] = getattr(existing, field)
    return AppConfig.from_dict(merged)


class ResearchFlowHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address, handler_class, config_path: Path):
        super().__init__(server_address, handler_class)
        self.config_path = config_path
        self.jobs: Dict[str, JobState] = {}
        self.jobs_lock = threading.Lock()

    def load_config(self) -> AppConfig:
        return AppConfig.from_path(self.config_path)

    def save_config(self, config_path: Path, config: AppConfig) -> None:
        config.save(config_path)
        self.config_path = config_path

    def start_job(self, config: AppConfig, request: IngestRequest) -> str:
        job_id = uuid.uuid4().hex[:8]
        job = JobState(job_id=job_id, status="running", logs=["Pipeline started."])
        with self.jobs_lock:
            self.jobs[job_id] = job

        def worker() -> None:
            try:
                result = run_ingest_pipeline(
                    request,
                    config,
                    progress=lambda message: self._append_log(job_id, message),
                )
                payload = {
                    "citekey": result.citekey,
                    "zotero_item_key": result.zotero_item_key,
                    "zotero_attachment_key": result.zotero_attachment_key,
                    "packet_path": str(result.packet_path),
                    "analysis_path": str(result.analysis_path),
                    "note_path": str(result.note_path) if result.note_path else None,
                    "obsidian_target": result.obsidian_target,
                    "reading_mode": result.reading_mode,
                    "skim_path": str(result.skim_path) if result.skim_path else None,
                    "deep_read_path": str(result.deep_read_path) if result.deep_read_path else None,
                    "discussion_path": str(result.discussion_path) if result.discussion_path else None,
                }
                with self.jobs_lock:
                    job.status = "done"
                    job.result = payload
                    job.logs.append("Pipeline complete.")
            except Exception as exc:
                with self.jobs_lock:
                    job.status = "error"
                    job.error = str(exc)
                    job.logs.append(f"Pipeline failed: {exc}")

        threading.Thread(target=worker, daemon=True).start()
        return job_id

    def _append_log(self, job_id: str, message: str) -> None:
        with self.jobs_lock:
            job = self.jobs[job_id]
            job.logs.append(message)

    def get_job(self, job_id: str) -> Optional[JobState]:
        with self.jobs_lock:
            return self.jobs.get(job_id)


class ResearchFlowHandler(BaseHTTPRequestHandler):
    server: ResearchFlowHTTPServer

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_html(APP_HTML)
            return
        if parsed.path == "/api/config":
            self._handle_get_config()
            return
        if parsed.path == "/api/job":
            self._handle_get_job(parsed)
            return
        self._send_json({"error": "Not found"}, status=404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/config":
            self._handle_post_config()
            return
        if parsed.path == "/api/zotero_targets":
            self._handle_zotero_targets()
            return
        if parsed.path == "/api/upload":
            self._handle_upload()
            return
        if parsed.path == "/api/prefill":
            self._handle_prefill()
            return
        if parsed.path == "/api/zotero_import":
            self._handle_zotero_import()
            return
        if parsed.path == "/api/zotero_lookup":
            self._handle_zotero_lookup()
            return
        if parsed.path == "/api/zotero_browse":
            self._handle_zotero_browse()
            return
        if parsed.path == "/api/zotero_check_duplicate":
            self._handle_zotero_check_duplicate()
            return
        if parsed.path == "/api/zotero_select_paper":
            self._handle_zotero_select_paper()
            return
        if parsed.path == "/api/run":
            self._handle_run()
            return
        self._send_json({"error": "Not found"}, status=404)

    def log_message(self, format: str, *args) -> None:  # pragma: no cover - noisy server logs
        return

    def _read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        data = json.loads(body.decode("utf-8")) if body else {}
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def _send_html(self, html: str, status: int = 200) -> None:
        payload = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, payload: Dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _config_payload(self, config: AppConfig) -> Dict[str, Any]:
        return {
            "config_path": str(self.server.config_path),
            "config": config.as_dict(),
        }

    def _handle_get_config(self) -> None:
        try:
            config = self.server.load_config()
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        self._send_json(self._config_payload(config))

    def _handle_post_config(self) -> None:
        try:
            payload = self._read_json()
            config_path = Path(str(payload.get("config_path") or DEFAULT_CONFIG_PATH))
            raw_config = AppConfig.from_dict(payload.get("config") or {})
            config = merge_config_with_existing(config_path, raw_config)
            self.server.save_config(config_path, config)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        self._send_json(self._config_payload(config))

    def _handle_zotero_targets(self) -> None:
        try:
            payload = self._read_json()
            config = AppConfig.from_dict(payload.get("config") or {})
            targets = get_zotero_desktop_targets(config)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        self._send_json(targets)

    def _handle_upload(self) -> None:
        try:
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={
                    "REQUEST_METHOD": "POST",
                    "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                },
            )
            if "file" not in form:
                raise ValueError("No file was uploaded")
            field = form["file"]
            if isinstance(field, list):
                field = field[0]
            filename = field.filename or "paper.pdf"
            content = field.file.read()
            if not content:
                raise ValueError("Uploaded PDF was empty")
            saved_path = save_uploaded_pdf(filename, content)
            prefill = extract_prefill(saved_path)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=400)
            return

        self._send_json(
            {
                "pdf_path": str(saved_path),
                "prefill": _prefill_to_dict(prefill),
            }
        )

    def _handle_prefill(self) -> None:
        try:
            payload = self._read_json()
            pdf_path = Path(str(payload.get("pdf_path") or "")).expanduser().resolve()
            prefill = extract_prefill(pdf_path)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        self._send_json({"prefill": _prefill_to_dict(prefill)})

    def _handle_zotero_lookup(self) -> None:
        try:
            payload = self._read_json()
            config = AppConfig.from_dict(payload.get("config") or {})
            request = request_from_payload(payload, config)
            match = lookup_zotero_prefill(config, request)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        except ZoteroAPIError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=400)
            return

        if not match:
            self._send_json({"found": False, "reason": "No matching Zotero item found."})
            return

        self._send_json(
            {
                "found": True,
                "prefill": {
                    "pdf_path": match.get("pdf_path"),
                    "title": match.get("title"),
                    "authors": match.get("authors"),
                    "year": match.get("year"),
                    "journal": match.get("journal"),
                    "doi": match.get("doi"),
                    "url": match.get("url"),
                    "abstract": match.get("abstract"),
                },
                "zotero_item_key": match.get("zotero_item_key"),
            }
        )

    def _handle_zotero_browse(self) -> None:
        try:
            payload = self._read_json()
            config = AppConfig.from_dict(payload.get("config") or {})
            query = str(payload.get("query") or "").strip()
            limit = int(payload.get("limit") or 25)
            if limit < 1:
                limit = 1
            if limit > 100:
                limit = 100
            items = browse_zotero_library(config, query=query, limit=limit)
        except (ZoteroAPIError, ZoteroDesktopError) as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        self._send_json({"items": items, "count": len(items)})

    def _handle_zotero_check_duplicate(self) -> None:
        try:
            payload = self._read_json()
            config = AppConfig.from_dict(payload.get("config") or {})
            title = str(payload.get("title") or "").strip() or None
            authors = payload.get("authors")
            if isinstance(authors, str):
                authors = [a.strip() for a in authors.split(",") if a.strip()]
            year = str(payload.get("year") or "").strip() or None
            doi = str(payload.get("doi") or "").strip() or None
            pdf_filename = str(payload.get("pdf_filename") or "").strip() or None
            match = check_zotero_duplicate(
                config,
                title=title,
                authors=authors,
                year=year,
                doi=doi,
                pdf_filename=pdf_filename,
            )
        except (ZoteroAPIError, ZoteroDesktopError) as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=400)
            return

        if not match:
            self._send_json({"duplicate": False})
            return

        self._send_json({
            "duplicate": True,
            "match": {
                "zotero_item_key": match.get("zotero_item_key"),
                "title": match.get("title"),
                "authors": match.get("authors"),
                "year": match.get("year"),
                "journal": match.get("journal"),
                "doi": match.get("doi"),
                "duplicate_score": match.get("duplicate_score"),
            },
        })

    def _handle_zotero_select_paper(self) -> None:
        try:
            payload = self._read_json()
            config = AppConfig.from_dict(payload.get("config") or {})
            item_key = str(payload.get("item_key") or "").strip()
            if not item_key:
                raise ValueError("item_key is required")
            result = select_zotero_paper(config, item_key)
        except (ZoteroAPIError, ValueError) as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        self._send_json(result)

    def _handle_zotero_import(self) -> None:
        try:
            payload = self._read_json()
            config = AppConfig.from_dict(payload.get("config") or {})
            request = request_from_payload(payload, config)
            if not request.pdf_path.exists():
                raise FileNotFoundError(f"PDF not found: {request.pdf_path}")
            result = import_pdf_via_zotero_desktop(config, request)
        except (ValueError, ZoteroAPIError, ZoteroDesktopError) as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=400)
            return

        self._send_json(result)

    def _handle_run(self) -> None:
        try:
            payload = self._read_json()
            config_path = Path(str(payload.get("config_path") or DEFAULT_CONFIG_PATH))
            raw_config = AppConfig.from_dict(payload.get("config") or {})
            config = merge_config_with_existing(config_path, raw_config)
            self.server.save_config(config_path, config)
            request = request_from_payload(payload, config)
            if not request.pdf_path.exists():
                raise FileNotFoundError(f"PDF not found: {request.pdf_path}")
            if not request.title:
                raise ValueError("Title is required")
            if not request.authors:
                raise ValueError("At least one author is required")
            job_id = self.server.start_job(config, request)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        self._send_json({"job_id": job_id})

    def _handle_get_job(self, parsed) -> None:
        query = parse_qs(parsed.query)
        job_id = (query.get("id") or [""])[0]
        job = self.server.get_job(job_id)
        if not job:
            self._send_json({"error": "Job not found"}, status=404)
            return
        self._send_json(
            {
                "job_id": job.job_id,
                "status": job.status,
                "logs": job.logs,
                "result": job.result,
                "error": job.error,
            }
        )


def launch_web_app(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    config_path: Path = DEFAULT_CONFIG_PATH,
    open_browser: bool = True,
) -> None:
    try:
        server = ResearchFlowHTTPServer((host, port), ResearchFlowHandler, config_path)
    except OSError:
        server = ResearchFlowHTTPServer((host, 0), ResearchFlowHandler, config_path)

    actual_host, actual_port = server.server_address[:2]
    url = f"http://{actual_host}:{actual_port}"
    print(f"Research Flow browser UI running at {url}")
    print("Press Ctrl+C to stop the server.")

    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
