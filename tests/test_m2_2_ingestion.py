"""M2.2 knowledge ingestion tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from backend.knowledge import ingestion

SAMPLE_ITEMS = [
    {
        "knowledge_id": "us_2026_standard_deduction",
        "topic": "standard_deduction",
        "jurisdiction": "US",
        "effective_date": "2026-01-01",
        "summary": "For 2026, the standard deduction is adjusted annually by filing status.",
        "trigger_conditions": {"tax_year": 2026},
        "source_ids": ["irs_rp_2025_32"],
        "status": "effective",
    },
    {
        "knowledge_id": "us_2026_ca_top_rate",
        "topic": "state_income_tax",
        "jurisdiction": "CA",
        "effective_date": "2026-01-01",
        "summary": "California taxes ordinary income under progressive rate schedules.",
        "trigger_conditions": {"state": "CA"},
        "source_ids": ["ca_ftb_rate_schedule"],
        "status": "effective",
    },
]

SAMPLE_SOURCES = {
    "irs_rp_2025_32": {
        "source_id": "irs_rp_2025_32",
        "title": "Revenue Procedure 2025-32",
        "source_url": "https://www.irs.gov/pub/irs-drop/rp-25-32.pdf",
        "publisher": "Internal Revenue Service",
        "jurisdiction": "US",
    },
    "ca_ftb_rate_schedule": {
        "source_id": "ca_ftb_rate_schedule",
        "title": "California Tax Rate Schedules",
        "source_url": "https://www.ftb.ca.gov/forms/misc/1001.html",
        "publisher": "California Franchise Tax Board",
        "jurisdiction": "CA",
    },
}


class TestValidation(unittest.TestCase):
    def test_valid_items_pass(self):
        self.assertEqual(ingestion.validate_items(SAMPLE_ITEMS), [])

    def test_missing_source_ids_fails(self):
        item = {**SAMPLE_ITEMS[0], "source_ids": []}
        errors = ingestion.validate_items([item])
        self.assertTrue(any("source_ids" in error for error in errors))

    def test_missing_knowledge_id_fails(self):
        item = {k: v for k, v in SAMPLE_ITEMS[0].items() if k != "knowledge_id"}
        errors = ingestion.validate_items([item])
        self.assertTrue(any("knowledge_id" in error for error in errors))

    def test_duplicate_knowledge_id_fails(self):
        errors = ingestion.validate_items([SAMPLE_ITEMS[0], SAMPLE_ITEMS[0]])
        self.assertTrue(any("duplicate" in error.lower() for error in errors))

    def test_missing_summary_fails(self):
        item = {**SAMPLE_ITEMS[0], "summary": ""}
        errors = ingestion.validate_items([item])
        self.assertTrue(any("summary" in error for error in errors))

    def test_unknown_source_id_fails_when_sources_provided(self):
        item = {**SAMPLE_ITEMS[0], "source_ids": ["missing_source"]}
        errors = ingestion.validate_items([item], sources=SAMPLE_SOURCES)
        self.assertTrue(any("missing_source" in error for error in errors))


class TestIngestionNeo4j(unittest.TestCase):
    def test_ingest_creates_nodes(self):
        with (
            patch.object(ingestion.neo4j_client, "is_neo4j_available", return_value=True),
            patch.object(ingestion.neo4j_client, "run_query", return_value=[]) as run_query,
        ):
            count = ingestion.ingest_to_neo4j(SAMPLE_ITEMS, SAMPLE_SOURCES)

        self.assertEqual(count, len(SAMPLE_ITEMS))
        self.assertGreaterEqual(run_query.call_count, len(SAMPLE_ITEMS) * 4)

    def test_ingest_uses_merge_not_create(self):
        with (
            patch.object(ingestion.neo4j_client, "is_neo4j_available", return_value=True),
            patch.object(ingestion.neo4j_client, "run_query", return_value=[]) as run_query,
        ):
            ingestion.ingest_to_neo4j(SAMPLE_ITEMS[:1], SAMPLE_SOURCES)

        cypher = "\n".join(call.args[0] for call in run_query.call_args_list)
        self.assertIn("MERGE", cypher)
        self.assertNotIn("CREATE ", cypher)

    def test_ingest_creates_relationships(self):
        with (
            patch.object(ingestion.neo4j_client, "is_neo4j_available", return_value=True),
            patch.object(ingestion.neo4j_client, "run_query", return_value=[]) as run_query,
        ):
            ingestion.ingest_to_neo4j(SAMPLE_ITEMS[:1], SAMPLE_SOURCES)

        cypher = "\n".join(call.args[0] for call in run_query.call_args_list)
        self.assertIn("APPLIES_TO", cypher)
        self.assertIn("ABOUT", cypher)
        self.assertIn("CITED_FROM", cypher)

    def test_neo4j_unavailable_returns_zero(self):
        with patch.object(ingestion.neo4j_client, "is_neo4j_available", return_value=False):
            self.assertEqual(ingestion.ingest_to_neo4j(SAMPLE_ITEMS, SAMPLE_SOURCES), 0)

    def test_jurisdiction_type_inference(self):
        self.assertEqual(ingestion.jurisdiction_type("US"), "federal")
        self.assertEqual(ingestion.jurisdiction_type("CA"), "state")


class TestIngestionChroma(unittest.TestCase):
    def test_ingest_upserts_documents(self):
        collection = Mock()
        with (
            patch.object(ingestion.vector_store, "is_chroma_available", return_value=True),
            patch.object(ingestion.vector_store, "get_collection", return_value=collection),
            patch.object(ingestion.embedder, "is_embedder_available", return_value=True),
            patch.object(ingestion.embedder, "embed_batch", return_value=[[0.1], [0.2]]),
        ):
            count = ingestion.ingest_to_chroma(SAMPLE_ITEMS)

        self.assertEqual(count, len(SAMPLE_ITEMS))
        collection.upsert.assert_called_once()

    def test_chroma_unavailable_returns_zero(self):
        with patch.object(ingestion.vector_store, "is_chroma_available", return_value=False):
            self.assertEqual(ingestion.ingest_to_chroma(SAMPLE_ITEMS), 0)

    def test_metadata_includes_required_fields(self):
        collection = Mock()
        with (
            patch.object(ingestion.vector_store, "is_chroma_available", return_value=True),
            patch.object(ingestion.vector_store, "get_collection", return_value=collection),
            patch.object(ingestion.embedder, "is_embedder_available", return_value=True),
            patch.object(ingestion.embedder, "embed_batch", return_value=[[0.1]]),
        ):
            ingestion.ingest_to_chroma(SAMPLE_ITEMS[:1])

        metadata = collection.upsert.call_args.kwargs["metadatas"][0]
        self.assertEqual(metadata["jurisdiction"], "US")
        self.assertEqual(metadata["topic"], "standard_deduction")
        self.assertEqual(metadata["tax_year"], 2026)
        self.assertEqual(json.loads(metadata["source_ids"]), ["irs_rp_2025_32"])

    def test_document_text_format(self):
        collection = Mock()
        with (
            patch.object(ingestion.vector_store, "is_chroma_available", return_value=True),
            patch.object(ingestion.vector_store, "get_collection", return_value=collection),
            patch.object(ingestion.embedder, "is_embedder_available", return_value=True),
            patch.object(ingestion.embedder, "embed_batch", return_value=[[0.1]]),
        ):
            ingestion.ingest_to_chroma(SAMPLE_ITEMS[:1])

        self.assertEqual(
            collection.upsert.call_args.kwargs["documents"][0],
            "standard_deduction: For 2026, the standard deduction is adjusted annually by filing status.",
        )


class TestIngestAll(unittest.TestCase):
    def test_ingest_all_returns_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge_dir = root / "knowledge"
            knowledge_dir.mkdir()
            (knowledge_dir / "sample.json").write_text(json.dumps({"items": SAMPLE_ITEMS}), encoding="utf-8")
            manifest = root / "source_manifest.json"
            manifest.write_text(json.dumps({"sources": list(SAMPLE_SOURCES.values())}), encoding="utf-8")

            with (
                patch.object(ingestion, "ingest_to_neo4j", return_value=2),
                patch.object(ingestion, "ingest_to_chroma", return_value=2),
            ):
                stats = ingestion.ingest_all(knowledge_dir, manifest)

        self.assertEqual(stats["neo4j_count"], 2)
        self.assertEqual(stats["chroma_count"], 2)
        self.assertEqual(stats["total_items"], 2)
        self.assertEqual(stats["errors"], [])

    def test_ingest_all_validation_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge_dir = root / "knowledge"
            knowledge_dir.mkdir()
            (knowledge_dir / "sample.json").write_text(json.dumps({"items": [{"topic": "bad"}]}), encoding="utf-8")
            manifest = root / "source_manifest.json"
            manifest.write_text(json.dumps({"sources": []}), encoding="utf-8")

            with self.assertRaises(ValueError):
                ingestion.ingest_all(knowledge_dir, manifest)

    def test_ingest_all_empty_directory_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge_dir = root / "knowledge"
            knowledge_dir.mkdir()
            manifest = root / "source_manifest.json"
            manifest.write_text(json.dumps({"sources": list(SAMPLE_SOURCES.values())}), encoding="utf-8")

            with self.assertRaises(ValueError):
                ingestion.ingest_all(knowledge_dir, manifest)

    def test_idempotent_double_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge_dir = root / "knowledge"
            knowledge_dir.mkdir()
            (knowledge_dir / "sample.json").write_text(json.dumps({"items": SAMPLE_ITEMS}), encoding="utf-8")
            manifest = root / "source_manifest.json"
            manifest.write_text(json.dumps({"sources": list(SAMPLE_SOURCES.values())}), encoding="utf-8")

            with (
                patch.object(ingestion, "ingest_to_neo4j", return_value=2),
                patch.object(ingestion, "ingest_to_chroma", return_value=2),
            ):
                first = ingestion.ingest_all(knowledge_dir, manifest)
                second = ingestion.ingest_all(knowledge_dir, manifest)

        self.assertEqual(first, second)

    def test_cli_initializes_and_closes_optional_stores(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge_dir = root / "knowledge"
            knowledge_dir.mkdir()
            (knowledge_dir / "sample.json").write_text(json.dumps({"items": SAMPLE_ITEMS}), encoding="utf-8")
            manifest = root / "source_manifest.json"
            manifest.write_text(json.dumps({"sources": list(SAMPLE_SOURCES.values())}), encoding="utf-8")

            with (
                patch.object(ingestion.neo4j_client, "init_neo4j") as init_neo4j,
                patch.object(ingestion.vector_store, "init_chroma") as init_chroma,
                patch.object(ingestion.embedder, "init_embedder") as init_embedder,
                patch.object(ingestion.embedder, "close_embedder") as close_embedder,
                patch.object(ingestion.vector_store, "close_chroma") as close_chroma,
                patch.object(ingestion.neo4j_client, "close_neo4j") as close_neo4j,
                patch.object(
                    ingestion,
                    "ingest_all",
                    return_value={"total_items": 2, "neo4j_count": 2, "chroma_count": 2},
                ),
            ):
                exit_code = ingestion.main(
                    ["--knowledge-dir", str(knowledge_dir), "--source-manifest", str(manifest)]
                )

        self.assertEqual(exit_code, 0)
        init_neo4j.assert_called_once()
        init_chroma.assert_called_once()
        init_embedder.assert_called_once()
        close_embedder.assert_called_once()
        close_chroma.assert_called_once()
        close_neo4j.assert_called_once()


class TestKnowledgeDataIntegrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.knowledge_path = Path("data/knowledge/us/2026/us_core_knowledge.json")
        cls.manifest_path = Path("data/sources/us/2026/source_manifest.json")
        cls.knowledge = json.loads(cls.knowledge_path.read_text(encoding="utf-8"))
        cls.items = cls.knowledge["items"]
        cls.manifest = json.loads(cls.manifest_path.read_text(encoding="utf-8"))
        cls.source_ids = {source["source_id"] for source in cls.manifest["sources"]}

    def test_all_items_have_source_ids(self):
        self.assertFalse(ingestion.validate_items(self.items))

    def test_no_duplicate_knowledge_ids(self):
        ids = [item["knowledge_id"] for item in self.items]
        self.assertEqual(len(ids), len(set(ids)))

    def test_minimum_item_count(self):
        self.assertGreaterEqual(len(self.items), 60)

    def test_jurisdiction_coverage(self):
        jurisdictions = {item["jurisdiction"] for item in self.items}
        states = {code for code in jurisdictions if code != "US"}
        self.assertIn("US", jurisdictions)
        self.assertGreaterEqual(len(states), 5)

    def test_topic_coverage(self):
        topics = {item["topic"] for item in self.items}
        self.assertGreaterEqual(len(topics), 8)

    def test_source_manifest_covers_all_source_ids(self):
        referenced = {source_id for item in self.items for source_id in item["source_ids"]}
        self.assertLessEqual(referenced, self.source_ids)

    def test_referenced_sources_are_archived_or_verified(self):
        allowed_statuses = {"archived", "archived_redacted", "source_verified_raw_fetch_blocked"}
        sources = {source["source_id"]: source for source in self.manifest["sources"]}
        referenced = {source_id for item in self.items for source_id in item["source_ids"]}
        bad_sources = [
            source_id
            for source_id in sorted(referenced)
            if sources[source_id].get("status", "archived") not in allowed_statuses
        ]
        self.assertEqual(bad_sources, [])


if __name__ == "__main__":
    unittest.main()
