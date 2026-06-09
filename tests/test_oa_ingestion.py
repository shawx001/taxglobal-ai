"""Tests for the OpenAccountants GraphRAG ingestion script."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.knowledge.ingestion import validate_items
from scripts.ingest_openaccountants import (
    build_knowledge_and_manifest,
    chunk_by_h2,
    extract_citations,
    main,
    map_jurisdiction,
    parse_frontmatter,
    source_id_for_path,
    topic_for_file,
)


class TestFrontmatterParsing(unittest.TestCase):
    def test_parse_with_frontmatter(self) -> None:
        text = "---\nname: test-skill\nversion: 0.1\n---\n\n# Title\n\nContent"
        meta, body = parse_frontmatter(text)
        self.assertEqual(meta["name"], "test-skill")
        self.assertIn("# Title", body)
        self.assertNotIn("name: test-skill", body)

    def test_parse_without_frontmatter(self) -> None:
        text = "# Just a title\n\nSome content here"
        meta, body = parse_frontmatter(text)
        self.assertEqual(meta, {})
        self.assertEqual(body, text)

    def test_parse_invalid_yaml_frontmatter_falls_back(self) -> None:
        text = "---\nname: state-skill\ndescription: NOTE: unquoted colon\n---\n\n# Title\n\nContent"
        meta, body = parse_frontmatter(text)
        self.assertEqual(meta["name"], "state-skill")
        self.assertEqual(meta["description"], "NOTE: unquoted colon")
        self.assertIn("# Title", body)


class TestChunking(unittest.TestCase):
    def test_basic_h2_split(self) -> None:
        md = "Preamble text\n\n## Section 1\n\nContent 1\n\n## Section 2\n\nContent 2"
        chunks = chunk_by_h2(md)
        self.assertEqual(len(chunks), 3)
        self.assertEqual(chunks[1]["heading"], "Section 1")
        self.assertIn("Content 1", chunks[1]["content"])

    def test_h3_not_split(self) -> None:
        md = "## Main\n\nText\n\n### Sub\n\nMore text"
        chunks = chunk_by_h2(md)
        self.assertEqual(len(chunks), 1)
        self.assertIn("### Sub", chunks[0]["content"])


class TestJurisdictionMapping(unittest.TestCase):
    def test_us_federal(self) -> None:
        self.assertEqual(map_jurisdiction({"jurisdiction": "US-FEDERAL"}, Path("federal/x.md")), "US")

    def test_us_state(self) -> None:
        self.assertEqual(map_jurisdiction({"jurisdiction": "US-CA"}, Path("us-states/ca/x.md")), "CA")

    def test_directory_fallback(self) -> None:
        self.assertEqual(map_jurisdiction({}, Path("us-states/ny/x.md")), "NY")

    def test_cross_border(self) -> None:
        self.assertEqual(map_jurisdiction({"jurisdiction": "cross-border"}, Path("cross-border/x.md")), "INTL")


class TestCitationExtraction(unittest.TestCase):
    def test_irc_section(self) -> None:
        citations = extract_citations("See IRC section 199A(a)(1) for details")
        self.assertTrue(any("199A" in citation for citation in citations))

    def test_treas_reg(self) -> None:
        citations = extract_citations("Per Treas. Reg. section 1.199A-5.")
        self.assertTrue(any("1.199A-5" in citation for citation in citations))

    def test_public_law(self) -> None:
        citations = extract_citations("The One Big Beautiful Bill Act (P.L. 119-21).")
        self.assertTrue(any("119-21" in citation for citation in citations))


class TestSourceIds(unittest.TestCase):
    def test_readme_source_ids_include_path(self) -> None:
        self.assertEqual(
            source_id_for_path(Path("us-states/ca/README.md")),
            "oa_us_states_ca_readme",
        )
        self.assertEqual(
            source_id_for_path(Path("federal/us-qbi-deduction.md")),
            "oa_federal_us_qbi_deduction",
        )

    def test_topic_fallback_uses_source_id(self) -> None:
        self.assertEqual(topic_for_file({}, "oa_us_states_ca_readme"), "us-states-ca-readme")
        self.assertEqual(
            topic_for_file({"name": "ca-income-tax"}, "oa_us_states_ca_ca_income_tax"),
            "ca-income-tax",
        )


class TestEndToEnd(unittest.TestCase):
    def test_build_from_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            federal = root / "federal"
            california = root / "us-states" / "ca"
            federal.mkdir(parents=True)
            california.mkdir(parents=True)
            (federal / "us-qbi-deduction.md").write_text(
                "---\n"
                "name: us-qbi-deduction\n"
                "version: 0.2\n"
                "jurisdiction: US-FEDERAL\n"
                "depends_on: [us-tax-workflow-base]\n"
                "validation_status: ai-drafted-q3\n"
                "---\n\n"
                "# US QBI Deduction Skill v0.2\n\n"
                "Intro text that is long enough to become a preamble section for indexing.\n\n"
                "## Section 1 -- Scope statement\n\n"
                "This section covers IRC section 199A(a)(1) and has enough text to pass filtering.\n\n"
                "### H3 should stay here\n\n"
                "More detailed content remains in the same chunk.\n",
                encoding="utf-8",
            )
            (california / "README.md").write_text(
                "# California Skills\n\n"
                "## Overview\n\n"
                "California state skill index with enough descriptive text to be retained.",
                encoding="utf-8",
            )

            knowledge, manifest = build_knowledge_and_manifest(root)
            items = knowledge["items"]
            sources = manifest["sources"]

            self.assertEqual(len(sources), 2)
            self.assertGreaterEqual(len(items), 2)
            self.assertEqual(len({source["source_id"] for source in sources}), 2)
            self.assertTrue(all(item["source"] == "openaccountants" for item in items))
            self.assertTrue(any(item["jurisdiction"] == "CA" for item in items))
            self.assertTrue(any(item["topic"] == "us-states-ca-readme" for item in items))
            self.assertTrue(any("199A" in citation for item in items for citation in item["citations"]))

            source_map = {source["source_id"]: source for source in sources}
            self.assertEqual(validate_items(items, sources=source_map), [])

    def test_full_build_when_oa_skills_are_available(self) -> None:
        oa_root = Path(".claude/skills/openaccountants")
        if not oa_root.exists():
            self.skipTest("OA skills not installed")

        knowledge, manifest = build_knowledge_and_manifest(oa_root)
        items = knowledge["items"]
        sources = manifest["sources"]

        self.assertEqual(len(sources), 215)
        self.assertGreaterEqual(len(items), 400)
        self.assertLessEqual(len(items), 2500)

        ids = [item["knowledge_id"] for item in items]
        self.assertEqual(len(ids), len(set(ids)))
        source_ids = {source["source_id"] for source in sources}
        for item in items:
            self.assertTrue(item["source_ids"])
            self.assertIn(item["source_ids"][0], source_ids)

        jurisdictions = {item["jurisdiction"] for item in items}
        self.assertIn("US", jurisdictions)
        self.assertIn("CA", jurisdictions)
        self.assertIn("NY", jurisdictions)

        errors = validate_items(items, sources={source["source_id"]: source for source in sources})
        self.assertEqual(errors, [])

    def test_ingest_without_generate_writes_json_before_ingest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "oa"
            output_root = Path(temp_dir) / "out"
            federal = root / "federal"
            federal.mkdir(parents=True)
            (federal / "us-qbi-deduction.md").write_text(
                "---\nname: us-qbi-deduction\njurisdiction: US-FEDERAL\n---\n\n"
                "# US QBI Deduction\n\n"
                "## Section 1\n\n"
                "This section covers IRC section 199A(a)(1) and has enough content.",
                encoding="utf-8",
            )
            knowledge_output = output_root / "knowledge" / "oa_knowledge.json"
            manifest_output = output_root / "sources" / "source_manifest.json"

            with (
                patch("backend.knowledge.neo4j_client.init_neo4j"),
                patch("backend.knowledge.neo4j_client.close_neo4j"),
                patch("backend.knowledge.vector_store.init_chroma"),
                patch("backend.knowledge.vector_store.close_chroma"),
                patch("backend.knowledge.embedder.init_embedder"),
                patch("backend.knowledge.embedder.close_embedder"),
                patch("backend.knowledge.ingestion.ingest_all", return_value={"total_items": 1, "errors": []})
                as ingest_all,
            ):
                exit_code = main(
                    [
                        "--ingest",
                        "--oa-root",
                        str(root),
                        "--knowledge-output",
                        str(knowledge_output),
                        "--manifest-output",
                        str(manifest_output),
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertTrue(knowledge_output.exists())
            self.assertTrue(manifest_output.exists())
            ingest_all.assert_called_once_with(knowledge_output.parent, manifest_output)
