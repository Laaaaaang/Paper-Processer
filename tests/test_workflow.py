import json
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from research_flow.config import AppConfig
from research_flow.gemini_client import build_gemini_request_body, create_analysis as create_gemini_analysis
from research_flow.gui import copy_pdf_into_workspace
from research_flow.llm_client import create_analysis_for_provider
from research_flow.models import AnalysisPacket, PaperPacket
from research_flow.openai_client import build_openai_request_body, create_analysis
from research_flow.pipeline import (
    IngestRequest,
    analysis_path_for_packet,
    extract_prefill,
    generate_citekey,
    packet_path_for_pdf,
    run_ingest_pipeline,
)
from research_flow.prompting import build_prompt
from research_flow.rendering import render_note
from research_flow.webapp import (
    merge_config_with_existing,
    get_zotero_desktop_targets,
    import_pdf_via_zotero_desktop,
    lookup_zotero_prefill,
    request_from_payload,
    save_uploaded_pdf,
)


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


def load_example(name: str):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


class WorkflowTests(unittest.TestCase):
    def test_examples_validate(self):
        for name in [
            "annotated_paper.json",
            "sparse_annotations.json",
            "metadata_only.json",
        ]:
            paper = PaperPacket.from_dict(load_example(name))
            paper.validate()
            self.assertTrue(paper.citekey)
            self.assertTrue(paper.authors)

    def test_prompt_contains_contract(self):
        paper = PaperPacket.from_dict(load_example("annotated_paper.json"))
        prompt = build_prompt(paper)
        self.assertIn("Return JSON only.", prompt)
        self.assertIn("Quality checklist", prompt)
        self.assertIn("at-a-glance bibliographic snapshot", prompt)
        self.assertIn("useful_quotes", prompt)
        self.assertIn(paper.citekey, prompt)

    def test_render_note_contains_required_sections(self):
        paper = PaperPacket.from_dict(load_example("annotated_paper.json"))
        analysis = AnalysisPacket.from_dict(load_example("annotated_analysis.json"))
        note = render_note(paper, analysis)
        for heading in [
            "## 中文摘要",
            "## English Abstract Snapshot",
            "## Core Question",
            "## Methods",
            "## Key Findings",
            "## Strengths",
            "## Limitations",
            "## Useful Quotes",
            "## Key Concepts",
            "## My Connections",
            "## Next Actions",
            "## Provenance",
        ]:
            self.assertIn(heading, note)
        self.assertIn("> [!summary] At a Glance", note)
        self.assertIn('citekey: "smith2025retrieval"', note)
        self.assertIn('note_type: "literature-note"', note)
        self.assertIn("> Hybrid retrieval outperformed dense retrieval on all three datasets.", note)
        # Tags should be YAML list format, not JSON array
        self.assertIn("  - ", note)
        self.assertNotIn('tags: ["', note)
        # Key concepts should render as [[wiki-links]]
        self.assertIn("[[Dense Retrieval]]", note)
        # Concepts should appear in frontmatter
        self.assertIn("concepts:", note)

    def test_note_path_is_deterministic(self):
        paper = PaperPacket.from_dict(load_example("annotated_paper.json"))
        self.assertEqual(
            paper.note_relative_path().as_posix(),
            "Literature/smith2025retrieval - retrieval-augmented-reasoning-for-scientific-cla.md",
        )

    def test_config_defaults_are_preserved_for_missing_fields(self):
        config = AppConfig.from_dict({"zotero_user_id": "123"})
        self.assertEqual(config.zotero_user_id, "123")
        self.assertEqual(config.llm_provider, "openai")
        self.assertEqual(config.note_subdir, "Literature")
        self.assertEqual(config.default_item_type, "journalArticle")
        self.assertEqual(config.gemini_model, "gemini-2.5-flash")

    def test_merge_config_with_existing_keeps_saved_secrets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "research-flow.config.json"
            AppConfig(
                openai_api_key="saved-openai-key",
                gemini_api_key="saved-gemini-key",
                zotero_api_key="saved-zotero-key",
                obsidian_rest_api_key="saved-obsidian-key",
            ).save(config_path)

            incoming = AppConfig.from_dict(
                {
                    "zotero_user_id": "123",
                    "openai_model": "gpt-5.4",
                }
            )
            merged = merge_config_with_existing(config_path, incoming)
            self.assertEqual(merged.openai_api_key, "saved-openai-key")
            self.assertEqual(merged.gemini_api_key, "saved-gemini-key")
            self.assertEqual(merged.zotero_api_key, "saved-zotero-key")
            self.assertEqual(merged.obsidian_rest_api_key, "saved-obsidian-key")

    def test_packet_paths_follow_pdf_location_by_default(self):
        config = AppConfig()
        pdf_path = Path("/tmp/example-paper.pdf")
        packet_path = packet_path_for_pdf(pdf_path, config)
        self.assertEqual(str(packet_path), "/tmp/example-paper.paper.json")
        self.assertEqual(str(analysis_path_for_packet(packet_path)), "/tmp/example-paper.paper.analysis.json")

    @mock.patch("research_flow.pdf_metadata._fetch_crossref_metadata")
    @mock.patch("research_flow.pdf_metadata._run_mdls")
    def test_extract_prefill_uses_pdf_metadata_when_available(self, mdls_mock, crossref_mock):
        mdls_mock.side_effect = [
            "Sample Paper Title",
            None,
            '(\n  "Ada Lovelace",\n  "Grace Hopper"\n)',
            '("https://example.org/sample.pdf")',
        ]
        crossref_mock.return_value = {}
        request = extract_prefill(Path("/tmp/sample-2024.pdf"))
        self.assertEqual(request.title, "Sample Paper Title")
        self.assertEqual(request.authors, ["Ada Lovelace", "Grace Hopper"])
        self.assertEqual(request.year, "2024")
        self.assertEqual(request.url, "https://example.org/sample.pdf")

    @mock.patch("research_flow.pdf_metadata._fetch_crossref_metadata")
    @mock.patch("research_flow.pdf_metadata._run_mdls")
    def test_extract_prefill_uses_doi_lookup_when_embedded_metadata_is_bad(self, mdls_mock, crossref_mock):
        mdls_mock.side_effect = [
            "3551901.3556486",
            None,
            None,
            "3551901.3556486\n10.1234/example.doi\nAbstract\nA helpful abstract.\nIntroduction",
        ]
        crossref_mock.return_value = {
            "title": "Recovered Paper Title",
            "authors": ["Ada Lovelace", "Grace Hopper"],
            "year": "2024",
            "journal": "Journal of Better Metadata",
            "doi": "10.1234/example.doi",
            "url": "https://doi.org/10.1234/example.doi",
            "abstract": "A helpful abstract.",
        }
        request = extract_prefill(Path("/tmp/3551901.3556486.pdf"))
        self.assertEqual(request.title, "Recovered Paper Title")
        self.assertEqual(request.authors, ["Ada Lovelace", "Grace Hopper"])
        self.assertEqual(request.year, "2024")
        self.assertEqual(request.journal, "Journal of Better Metadata")
        self.assertEqual(request.doi, "10.1234/example.doi")
        self.assertEqual(request.abstract, "A helpful abstract.")

    def test_copy_pdf_into_workspace_creates_visible_import(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source = tmp / "paper.pdf"
            source.write_bytes(b"%PDF-1.4 import test")
            workspace_imports = tmp / "imports"
            copied = copy_pdf_into_workspace(source, workspace_imports)
            self.assertTrue(copied.exists())
            self.assertEqual(copied.parent.resolve(), workspace_imports.resolve())
            self.assertEqual(copied.read_bytes(), b"%PDF-1.4 import test")

    def test_save_uploaded_pdf_writes_uploaded_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            saved = save_uploaded_pdf("upload.pdf", b"%PDF-1.4 upload", tmp / "imports")
            self.assertTrue(saved.exists())
            self.assertEqual(saved.read_bytes(), b"%PDF-1.4 upload")

    def test_request_from_payload_builds_ingest_request(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            pdf = tmp / "paper.pdf"
            pdf.write_bytes(b"%PDF-1.4")
            payload = {
                "paper": {
                    "pdf_path": str(pdf),
                    "title": "Test Title",
                    "authors": "Ada Lovelace, Grace Hopper",
                    "year": "2024",
                    "journal": "Test Journal",
                    "doi": "10.1/test",
                    "url": "https://example.org",
                    "abstract": "Abstract",
                    "annotation_text": "Notes",
                    "tags": "one, two",
                    "status": "inbox",
                    "item_type": "journalArticle",
                    "zotero_item_key": "ABCD1234",
                    "zotero_attachment_key": "EFGH5678",
                    "zotero_target_id": "C25",
                }
            }
            config = AppConfig()
            request = request_from_payload(payload, config)
            self.assertEqual(request.title, "Test Title")
            self.assertEqual(request.authors, ["Ada Lovelace", "Grace Hopper"])
            self.assertEqual(request.tags, ["one", "two"])
            self.assertEqual(request.zotero_item_key, "ABCD1234")
            self.assertEqual(request.zotero_attachment_key, "EFGH5678")
            self.assertEqual(request.zotero_target_id, "C25")
            self.assertEqual(request.pdf_path.resolve(), pdf.resolve())

    @mock.patch("research_flow.webapp.ZoteroClient")
    def test_lookup_zotero_prefill_uses_library_metadata_when_available(self, zotero_client_mock):
        zotero_client_mock.return_value.lookup_best_metadata.return_value = {
            "zotero_item_key": "ABCD1234",
            "title": "Recovered Title",
            "authors": ["Ada Lovelace", "Grace Hopper"],
            "year": "2024",
            "journal": "Journal of Better Metadata",
            "doi": "10.1/example",
            "url": "https://example.org",
            "abstract": "Recovered abstract.",
        }
        config = AppConfig(zotero_user_id="123", zotero_api_key="secret")
        request = IngestRequest(
            pdf_path=Path("/tmp/paper.pdf"),
            title="Fallback Title",
            authors=["Unknown"],
            year="2021",
        )
        result = lookup_zotero_prefill(config, request)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["zotero_item_key"], "ABCD1234")
        self.assertEqual(result["title"], "Recovered Title")
        self.assertEqual(result["authors"], ["Ada Lovelace", "Grace Hopper"])
        zotero_client_mock.return_value.lookup_best_metadata.assert_called_once()

    @mock.patch("research_flow.webapp.ZoteroDesktopClient")
    def test_get_zotero_desktop_targets_returns_selected_target(self, desktop_mock):
        desktop_mock.return_value.get_targets.return_value = {
            "libraryID": 1,
            "libraryName": "My Library",
            "id": 25,
            "name": "Inbox",
            "targets": [
                {"id": "L1", "name": "My Library", "level": 0},
                {"id": "C25", "name": "Inbox", "level": 1},
            ],
        }
        desktop_mock.return_value.get_local_library_version.return_value = 321

        payload = get_zotero_desktop_targets(AppConfig())
        self.assertEqual(payload["selected_target_id"], "C25")
        self.assertTrue(payload["local_api_enabled"])

    @mock.patch("research_flow.webapp.ZoteroClient")
    @mock.patch("research_flow.webapp.ZoteroDesktopClient")
    def test_import_pdf_via_zotero_desktop_prefers_local_api_match(self, desktop_mock, zotero_client_mock):
        config = AppConfig(zotero_user_id="123", zotero_api_key="secret")
        request = IngestRequest(
            pdf_path=Path("/tmp/paper.pdf"),
            title="Recovered Title",
            authors=["Unknown"],
            zotero_target_id="C25",
        )
        desktop_mock.return_value.get_targets.return_value = {
            "libraryID": 1,
            "id": 25,
            "targets": [{"id": "C25", "name": "Inbox", "level": 1}],
        }
        desktop_mock.return_value.get_local_library_version.return_value = 99
        desktop_mock.return_value.wait_for_recognized_item.return_value = {
            "title": "Recovered Title",
            "itemType": "journalArticle",
        }
        desktop_mock.return_value.find_best_local_item_by_title_and_attachment.return_value = {
            "zotero_item_key": "ABCD1234",
            "zotero_attachment_key": "EFGH5678",
            "title": "Recovered Title",
            "authors": ["Ada Lovelace"],
            "year": "2024",
            "journal": "Journal",
            "doi": "10.1/example",
            "url": "https://example.org",
            "abstract": "Recovered abstract.",
        }

        result = import_pdf_via_zotero_desktop(config, request)
        self.assertEqual(result["metadata_source"], "zotero_local_api")
        self.assertTrue(result["recognized"])
        self.assertEqual(result["prefill"]["zotero_item_key"], "ABCD1234")
        self.assertEqual(result["prefill"]["zotero_attachment_key"], "EFGH5678")
        desktop_mock.return_value.update_session.assert_called()
        zotero_client_mock.return_value.find_best_item_by_title_and_attachment.assert_not_called()

    @mock.patch("research_flow.pipeline.create_analysis_for_config")
    @mock.patch("research_flow.pipeline.ZoteroClient")
    def test_run_ingest_pipeline_writes_packet_analysis_and_note(self, zotero_mock, create_analysis_mock):
        zotero_mock.return_value.create_item_with_pdf.return_value = {
            "parent_key": "ABCD1234",
            "attachment_key": "EFGH5678",
        }
        create_analysis_mock.return_value = load_example("annotated_analysis.json")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            pdf_path = tmp / "test-paper.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 test")
            vault = tmp / "Vault"
            config = AppConfig(
                zotero_user_id="123",
                zotero_api_key="secret",
                openai_api_key="openai-secret",
                obsidian_vault_path=str(vault),
            )
            request = IngestRequest(
                pdf_path=pdf_path,
                title="Test Paper",
                authors=["Ada Lovelace"],
                year="2024",
                abstract="A short abstract.",
                item_type="journalArticle",
                status="inbox",
                tags=["test"],
            )
            result = run_ingest_pipeline(request, config)

            self.assertTrue(result.packet_path.exists())
            self.assertTrue(result.analysis_path.exists())
            self.assertIsNotNone(result.note_path)
            self.assertTrue(result.note_path.exists())

    @mock.patch("research_flow.pipeline.create_analysis_for_config")
    @mock.patch("research_flow.pipeline.ZoteroClient")
    def test_run_ingest_pipeline_reuses_existing_zotero_item(self, zotero_mock, create_analysis_mock):
        create_analysis_mock.return_value = load_example("annotated_analysis.json")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            pdf_path = tmp / "existing-paper.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 existing")
            vault = tmp / "Vault"
            config = AppConfig(
                zotero_user_id="123",
                zotero_api_key="secret",
                openai_api_key="openai-secret",
                obsidian_vault_path=str(vault),
            )
            request = IngestRequest(
                pdf_path=pdf_path,
                title="Existing Paper",
                authors=["Ada Lovelace"],
                year="2024",
                zotero_item_key="ABCD1234",
                zotero_attachment_key="EFGH5678",
            )
            result = run_ingest_pipeline(request, config)

            zotero_mock.return_value.create_item_with_pdf.assert_not_called()
            self.assertEqual(result.zotero_item_key, "ABCD1234")
            self.assertEqual(result.zotero_attachment_key, "EFGH5678")
            self.assertIn("Literature", str(result.note_path))
            note_text = result.note_path.read_text(encoding="utf-8")
            self.assertIn("## 中文摘要", note_text)
            self.assertIn('citekey: "lovelace2024existing"', note_text)
            create_analysis_mock.assert_called_once()

    @mock.patch("urllib.request.urlopen")
    def test_create_analysis_sends_schema_name(self, urlopen_mock):
        response_payload = {
            "output_text": json.dumps(load_example("annotated_analysis.json"))
        }

        class _FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps(response_payload).encode("utf-8")

        urlopen_mock.return_value = _FakeResponse()
        paper = PaperPacket.from_dict(load_example("annotated_paper.json"))
        create_analysis(paper, model="gpt-5.4", api_key="test-key")

        request = urlopen_mock.call_args.args[0]
        self.assertIsInstance(request, urllib.request.Request)
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["text"]["format"]["type"], "json_schema")
        self.assertEqual(body["text"]["format"]["name"], "literature_note_analysis")
        self.assertEqual(body["input"][0]["content"][0]["type"], "input_text")

    def test_build_openai_request_body_contains_named_schema_and_prompt(self):
        paper = PaperPacket.from_dict(load_example("annotated_paper.json"))
        body = build_openai_request_body(paper, model="gpt-5.4")
        self.assertEqual(body["model"], "gpt-5.4")
        self.assertEqual(body["text"]["format"]["name"], "literature_note_analysis")
        self.assertTrue(body["text"]["format"]["strict"])
        self.assertEqual(body["input"][0]["role"], "user")
        self.assertEqual(body["input"][0]["content"][0]["type"], "input_text")
        self.assertIn(paper.title, body["input"][0]["content"][0]["text"])

    def test_build_gemini_request_body_contains_json_schema(self):
        paper = PaperPacket.from_dict(load_example("annotated_paper.json"))
        body = build_gemini_request_body(paper)
        self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(body["generationConfig"]["responseJsonSchema"]["type"], "object")
        self.assertIn(paper.title, body["contents"][0]["parts"][0]["text"])

    @mock.patch("urllib.request.urlopen")
    def test_create_gemini_analysis_parses_json_candidate(self, urlopen_mock):
        response_payload = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": json.dumps(load_example("annotated_analysis.json"))}
                        ]
                    }
                }
            ]
        }

        class _FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps(response_payload).encode("utf-8")

        urlopen_mock.return_value = _FakeResponse()
        paper = PaperPacket.from_dict(load_example("annotated_paper.json"))
        analysis = create_gemini_analysis(paper, model="gemini-2.5-flash", api_key="test-key")
        self.assertEqual(
            analysis["core_question"],
            load_example("annotated_analysis.json")["core_question"],
        )
        request = urlopen_mock.call_args.args[0]
        self.assertIn("X-goog-api-key", request.headers)

    @mock.patch("research_flow.llm_client.create_gemini_analysis")
    def test_create_analysis_for_provider_dispatches_to_gemini(self, gemini_mock):
        gemini_mock.return_value = load_example("annotated_analysis.json")
        paper = PaperPacket.from_dict(load_example("annotated_paper.json"))
        analysis = create_analysis_for_provider(
            paper,
            provider="gemini",
            model="gemini-2.5-flash",
            api_key="test-key",
        )
        self.assertEqual(
            analysis["english_abstract_snapshot"],
            load_example("annotated_analysis.json")["english_abstract_snapshot"],
        )
        gemini_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
