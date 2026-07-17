"""Fine-tune the Tunisian Arabizi sentiment model, Model B (brief Section 9.2).

Runs on a free Colab/Kaggle GPU (see notebooks/finetune_tunizi.ipynb). Needs the
training extras: ``pip install -e ".[nlp,train]"``.

Protocol (brief): stratified 70/10/20 split with a pinned seed, max length 128,
lr 2e-5, AdamW, up to 4 epochs with early stopping on validation macro-F1, class
weights for imbalance, MLflow logging, and a saved model card. The label id order
matches cardiffnlp (0=negative, 1=neutral, 2=positive) so the app loads the
fine-tuned model with no change to the inference layer.

Example:
  python -m app.nlp.training.finetune_tunizi \
      --csv data/tunizi.csv --base-model cardiffnlp/twitter-xlm-roberta-base \
      --output-dir models/arabizi --epochs 4
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path

from app.core.logging import configure_logging, get_logger
from app.nlp.preprocessing import preprocess
from app.nlp.training import metrics
from app.nlp.training.data import class_weights, normalize_label, stratified_split

# Use only the PyTorch backend. Hosted GPU envs (Kaggle/Colab) often ship a
# TensorFlow/Flax that is ABI-incompatible with the pinned protobuf, and
# transformers auto-imports whichever backends are present. We never use TF/Flax.
# Set before main() imports transformers (the app imports above do not).
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_FLAX", "0")

log = get_logger("training.finetune")

LABEL_ORDER = ["negative", "neutral", "positive"]
LABEL2ID = {label: i for i, label in enumerate(LABEL_ORDER)}
ID2LABEL = {i: label for label, i in LABEL2ID.items()}


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Fine-tune the Arabizi sentiment model.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv", help="Local CSV with text and label columns.")
    src.add_argument("--dataset", help="HuggingFace dataset id (e.g. a TUNIZI mirror).")
    ap.add_argument("--split", default="train", help="HF dataset split to load.")
    ap.add_argument("--text-col", default="text")
    ap.add_argument("--label-col", default="label")
    ap.add_argument("--base-model", default="cardiffnlp/twitter-xlm-roberta-base")
    ap.add_argument("--output-dir", default="models/arabizi")
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--max-length", type=int, default=128)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--seed", type=int, default=42)
    return ap.parse_args()


def load_rows(args: argparse.Namespace) -> list[dict]:
    """Load (text, canonical-label) rows from a CSV or a HuggingFace dataset."""
    raw: list[dict] = []
    if args.csv:
        with open(args.csv, encoding="utf-8") as f:
            raw = list(csv.DictReader(f))
    else:
        from datasets import load_dataset

        raw = list(load_dataset(args.dataset, split=args.split))

    rows: list[dict] = []
    for r in raw:
        label = normalize_label(r.get(args.label_col))
        text = str(r.get(args.text_col) or "").strip()
        if label and text:
            rows.append({"text": text, "label": label})
    if not rows:
        raise SystemExit("No labeled rows loaded. Check --text-col / --label-col.")
    return rows


def main() -> None:
    configure_logging()
    args = _parse_args()

    import numpy as np
    import torch
    from datasets import Dataset
    from torch import nn
    from transformers import (
        AutoModelForSequenceClassification,
        AutoTokenizer,
        DataCollatorWithPadding,
        EarlyStoppingCallback,
        Trainer,
        TrainingArguments,
    )

    rows = load_rows(args)
    for r in rows:
        r["text"] = preprocess(r["text"])  # identical cleaning to inference
    split = stratified_split(rows, seed=args.seed)
    log.info("data_loaded", train=len(split.train), val=len(split.val), test=len(split.test))

    weights = class_weights([r["label"] for r in split.train])
    weight_tensor = torch.tensor([weights[label] for label in LABEL_ORDER], dtype=torch.float)

    tokenizer = AutoTokenizer.from_pretrained(args.base_model)

    def to_dataset(part: list[dict]) -> Dataset:
        ds = Dataset.from_list([{"text": r["text"], "labels": LABEL2ID[r["label"]]} for r in part])
        return ds.map(
            lambda b: tokenizer(b["text"], truncation=True, max_length=args.max_length), batched=True
        )

    ds_train, ds_val, ds_test = to_dataset(split.train), to_dataset(split.val), to_dataset(split.test)

    model = AutoModelForSequenceClassification.from_pretrained(
        args.base_model, num_labels=3, id2label=ID2LABEL, label2id=LABEL2ID
    )

    def compute_metrics(eval_pred) -> dict:
        logits, labels = eval_pred
        preds = np.argmax(logits, axis=1)
        y_true = [ID2LABEL[int(i)] for i in labels]
        y_pred = [ID2LABEL[int(i)] for i in preds]
        return {"macro_f1": metrics.macro_f1(y_true, y_pred), "accuracy": metrics.accuracy(y_true, y_pred)}

    class WeightedTrainer(Trainer):
        def compute_loss(self, model, inputs, return_outputs=False, **kwargs):
            labels = inputs.pop("labels")
            outputs = model(**inputs)
            loss = nn.CrossEntropyLoss(weight=weight_tensor.to(outputs.logits.device))(
                outputs.logits, labels
            )
            return (loss, outputs) if return_outputs else loss

    training_args = TrainingArguments(
        output_dir=f"{args.output_dir}/checkpoints",
        num_train_epochs=args.epochs,
        learning_rate=args.lr,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=64,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="macro_f1",
        greater_is_better=True,
        seed=args.seed,
        logging_steps=20,
        report_to=["mlflow"] if _mlflow_available() else [],
    )
    trainer = WeightedTrainer(
        model=model,
        args=training_args,
        train_dataset=ds_train,
        eval_dataset=ds_val,
        tokenizer=tokenizer,
        data_collator=DataCollatorWithPadding(tokenizer),
        compute_metrics=compute_metrics,
        callbacks=[EarlyStoppingCallback(early_stopping_patience=2)],
    )
    trainer.train()

    # Held-out test set: overall metrics + the per-language table (the money slide).
    from app.nlp.language import detect_language

    logits = trainer.predict(ds_test).predictions
    y_pred = [ID2LABEL[int(i)] for i in np.argmax(logits, axis=1)]
    y_true = [r["label"] for r in split.test]
    languages = [detect_language(r["text"]).language for r in split.test]
    report = metrics.summary(y_true, y_pred)
    report["per_language"] = metrics.per_language_f1(y_true, y_pred, languages)
    log.info("test_metrics", macro_f1=report["macro_f1"], accuracy=report["accuracy"])

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    trainer.save_model(str(out))
    tokenizer.save_pretrained(str(out))
    (out / "metrics.json").write_text(json.dumps(report, indent=2))
    _write_model_card(out, args, report)
    log.info("model_saved", path=str(out))


def _mlflow_available() -> bool:
    try:
        import mlflow  # noqa: F401

        return True
    except ImportError:
        return False


def _write_model_card(out: Path, args: argparse.Namespace, report: dict) -> None:
    lines = [
        "# Model card: Tunisian Arabizi sentiment (Model B)",
        "",
        f"Base model: {args.base_model}",
        f"Fine-tuned on: {args.csv or args.dataset}",
        "Labels: negative / neutral / positive",
        f"Max length: {args.max_length}, epochs: {args.epochs}, lr: {args.lr}, seed: {args.seed}",
        "",
        "## Test-set metrics",
        f"- Accuracy: {report['accuracy']}",
        f"- Macro-F1: {report['macro_f1']}",
        "",
        "## Per-language macro-F1",
    ]
    for lang, m in sorted(report["per_language"].items()):
        lines.append(f"- {lang}: F1={m['macro_f1']} (n={m['support']})")
    (out / "MODEL_CARD.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
