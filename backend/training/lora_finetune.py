"""M4.3 LoRA fine-tune of the conversational model (Qwen2.5-0.5B, CPU-runnable).

The fine-tune is gated by the M4.1 eval harness: after training, the adapter's
intent classifier is scored and the model is admitted only if ``overall`` clears
the deploy gate (project plan v3.1 §6.6). Numbers still come from the rule
engine — this only improves the model's *intent classification and phrasing*,
never its arithmetic.

Training dependencies (``peft`` / ``trl`` / ``datasets`` / ``accelerate``) are
OPTIONAL and imported lazily, so this module — and the serving runtime and CI —
never require them. Install them to actually train:

    pip install -r backend/requirements-training.txt

The base model is downloaded from Hugging Face on first run (needs network).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.eval.harness import DEFAULT_GATE, run_eval_harness
from backend.orchestrator.intent import _INTENT_SYSTEM_PROMPT, _VALID_INTENTS, INTENT_CLARIFY

DEFAULT_BASE_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"
_TRAINING_DEPS = ("peft", "trl", "datasets", "accelerate")
_INSTALL_HINT = "pip install -r backend/requirements-training.txt"


@dataclass(frozen=True)
class LoraConfigSpec:
    """Hyper-parameters for the LoRA fine-tune (small, CPU-friendly defaults)."""

    base_model: str = DEFAULT_BASE_MODEL
    r: int = 8
    alpha: int = 16
    dropout: float = 0.05
    # Qwen2.5 attention projections — the standard minimal LoRA target set.
    target_modules: tuple[str, ...] = ("q_proj", "k_proj", "v_proj", "o_proj")
    epochs: float = 1.0
    learning_rate: float = 2e-4
    max_seq_length: int = 1024
    per_device_batch_size: int = 1
    gradient_accumulation_steps: int = 8


def missing_training_deps() -> list[str]:
    """Return any optional training dependency that is not importable."""

    import importlib.util

    return [name for name in _TRAINING_DEPS if importlib.util.find_spec(name) is None]


def require_training_deps() -> None:
    missing = missing_training_deps()
    if missing:
        raise ImportError(f"missing optional training deps {missing}; install with: {_INSTALL_HINT}")


def load_sft_examples(path: str | Path) -> list[dict[str, Any]]:
    """Load a chat-format SFT JSONL produced by M4.2 and validate its shape."""

    lines = Path(path).read_text(encoding="utf-8").splitlines()
    examples: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        messages = record.get("messages")
        if not isinstance(messages, list) or not messages:
            raise ValueError(f"line {index}: SFT example missing non-empty 'messages' list")
        for message in messages:
            if not (isinstance(message, dict) and message.get("role") and "content" in message):
                raise ValueError(f"line {index}: each message needs 'role' and 'content'")
        examples.append(record)
    if not examples:
        raise ValueError(f"no SFT examples found in {path}")
    return examples


def build_peft_config(spec: LoraConfigSpec):  # noqa: ANN201 - lazy peft type
    """Build a ``peft.LoraConfig`` (lazy import)."""

    require_training_deps()
    from peft import LoraConfig  # noqa: PLC0415 - optional dep, imported on demand

    return LoraConfig(
        r=spec.r,
        lora_alpha=spec.alpha,
        lora_dropout=spec.dropout,
        target_modules=list(spec.target_modules),
        bias="none",
        task_type="CAUSAL_LM",
    )


def make_model_intent_classifier(model_dir: str | Path, base_model: str | None = None) -> Callable[[str], str]:
    """Load the fine-tuned model and return a ``query -> intent`` classifier.

    Used to score the adapter through the M4.1 harness. Generated text is mapped
    to a known intent; anything off-label degrades to ``clarify`` rather than
    inventing a label.
    """

    require_training_deps()
    import torch  # noqa: PLC0415
    from peft import PeftModel  # noqa: PLC0415
    from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: PLC0415

    model_dir = str(model_dir)
    base = base_model or DEFAULT_BASE_MODEL
    tokenizer = AutoTokenizer.from_pretrained(base)
    model = AutoModelForCausalLM.from_pretrained(base)
    model = PeftModel.from_pretrained(model, model_dir)
    model.eval()

    def classify(query: str) -> str:
        messages = [
            {"role": "system", "content": _INTENT_SYSTEM_PROMPT},
            {"role": "user", "content": query},
        ]
        prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer(prompt, return_tensors="pt")
        with torch.no_grad():
            generated = model.generate(**inputs, max_new_tokens=16, do_sample=False)
        text = tokenizer.decode(generated[0][inputs["input_ids"].shape[1] :], skip_special_tokens=True).lower()
        for intent in _VALID_INTENTS:
            if intent in text:
                return intent
        return INTENT_CLARIFY

    return classify


def finetune(
    train_path: str | Path,
    output_dir: str | Path,
    *,
    spec: LoraConfigSpec | None = None,
    gate: float = DEFAULT_GATE,
    run_gate: bool = True,
) -> dict[str, Any]:
    """Run the LoRA SFT, save the adapter, then apply the M4.1 deploy gate.

    Returns a summary dict. Raises ``ImportError`` (with an install hint) if the
    optional training deps are absent, so callers fail loudly rather than
    silently skipping training.
    """

    require_training_deps()
    spec = spec or LoraConfigSpec()
    output_dir = str(output_dir)

    from datasets import Dataset  # noqa: PLC0415
    from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: PLC0415
    from trl import SFTConfig, SFTTrainer  # noqa: PLC0415

    examples = load_sft_examples(train_path)
    dataset = Dataset.from_list(examples)

    tokenizer = AutoTokenizer.from_pretrained(spec.base_model)
    model = AutoModelForCausalLM.from_pretrained(spec.base_model)

    sft_config = SFTConfig(
        output_dir=output_dir,
        num_train_epochs=spec.epochs,
        per_device_train_batch_size=spec.per_device_batch_size,
        gradient_accumulation_steps=spec.gradient_accumulation_steps,
        learning_rate=spec.learning_rate,
        max_length=spec.max_seq_length,
        logging_steps=1,
        save_strategy="no",
        report_to=[],
    )
    trainer = SFTTrainer(
        model=model,
        args=sft_config,
        train_dataset=dataset,
        peft_config=build_peft_config(spec),
        processing_class=tokenizer,
    )
    trainer.train()
    trainer.save_model(output_dir)
    tokenizer.save_pretrained(output_dir)

    summary: dict[str, Any] = {
        "output_dir": output_dir,
        "trained_examples": len(examples),
        "base_model": spec.base_model,
        "eval": None,
        "passed": None,
    }
    if run_gate:
        classifier = make_model_intent_classifier(output_dir, base_model=spec.base_model)
        report = run_eval_harness(intent_classifier=classifier, gate=gate)
        summary["eval"] = report.as_dict()
        summary["passed"] = report.passed
    return summary
