"""Tests for the M4.3 LoRA pipeline.

CI exercises the dependency-free parts: SFT loading/validation, config defaults,
and the loud-failure behavior when the optional training deps are absent. The
actual fine-tune is an opt-in smoke test (needs the extras + a model download),
guarded so it never runs in CI or a normal local test pass.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from backend.training.lora_finetune import (
    DEFAULT_BASE_MODEL,
    LoraConfigSpec,
    build_peft_config,
    finetune,
    load_sft_examples,
    missing_training_deps,
    require_training_deps,
)

_DEPS_MISSING = bool(missing_training_deps())


def _write_jsonl(lines: list[dict], path: Path) -> None:
    path.write_text("\n".join(json.dumps(line, ensure_ascii=False) for line in lines), encoding="utf-8")


_GOOD = {
    "messages": [
        {"role": "system", "content": "classify"},
        {"role": "user", "content": "加州年薪15万要交多少税"},
        {"role": "assistant", "content": "income_tax"},
    ]
}


class SftLoadingTests(unittest.TestCase):
    def test_loads_valid_jsonl(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sft.jsonl"
            _write_jsonl([_GOOD, _GOOD], p)
            examples = load_sft_examples(p)
            self.assertEqual(len(examples), 2)
            self.assertEqual(examples[0]["messages"][2]["content"], "income_tax")

    def test_blank_lines_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sft.jsonl"
            p.write_text(json.dumps(_GOOD) + "\n\n", encoding="utf-8")
            self.assertEqual(len(load_sft_examples(p)), 1)

    def test_missing_messages_raises(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sft.jsonl"
            _write_jsonl([{"messages": []}], p)
            with self.assertRaises(ValueError):
                load_sft_examples(p)

    def test_malformed_message_raises(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sft.jsonl"
            _write_jsonl([{"messages": [{"role": "user"}]}], p)  # no content
            with self.assertRaises(ValueError):
                load_sft_examples(p)

    def test_empty_file_raises(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sft.jsonl"
            p.write_text("", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_sft_examples(p)


class ConfigTests(unittest.TestCase):
    def test_defaults(self):
        spec = LoraConfigSpec()
        self.assertEqual(spec.base_model, DEFAULT_BASE_MODEL)
        self.assertEqual(spec.epochs, 1.0)
        self.assertIn("q_proj", spec.target_modules)


class DependencyGuardTests(unittest.TestCase):
    @unittest.skipIf(_DEPS_MISSING is False, "training deps installed; absence-path not applicable")
    def test_require_training_deps_raises_with_hint(self):
        with self.assertRaises(ImportError) as ctx:
            require_training_deps()
        self.assertIn("requirements-training.txt", str(ctx.exception))

    @unittest.skipIf(_DEPS_MISSING is False, "training deps installed; absence-path not applicable")
    def test_finetune_fails_loudly_without_deps(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sft.jsonl"
            _write_jsonl([_GOOD], p)
            with self.assertRaises(ImportError):
                finetune(p, Path(d) / "out")

    @unittest.skipIf(_DEPS_MISSING is False, "training deps installed; absence-path not applicable")
    def test_build_peft_config_requires_deps(self):
        with self.assertRaises(ImportError):
            build_peft_config(LoraConfigSpec())


@unittest.skipUnless(
    not _DEPS_MISSING and os.environ.get("TAXGLOBAL_RUN_LORA_SMOKE") == "1",
    "opt-in LoRA smoke (set TAXGLOBAL_RUN_LORA_SMOKE=1 with training deps installed)",
)
class LoraSmokeTest(unittest.TestCase):
    def test_one_step_finetune_runs(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sft.jsonl"
            _write_jsonl([_GOOD] * 4, p)
            summary = finetune(p, Path(d) / "out", spec=LoraConfigSpec(epochs=1.0), run_gate=False)
            self.assertEqual(summary["trained_examples"], 4)
            self.assertTrue((Path(d) / "out").exists())


if __name__ == "__main__":
    unittest.main()
