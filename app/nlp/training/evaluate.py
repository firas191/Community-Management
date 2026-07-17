"""Evaluate a sentiment model and print the per-language table (brief Section 9.2).

Run the same labeled set through Model A and the fine-tuned Model B to get the
before/after per-language macro-F1 table (the delta on aeb-latn is the headline).
Needs the NLP extras.

  python -m app.nlp.training.evaluate --csv data/gold.csv --model models/arabizi
  python -m app.nlp.training.evaluate --csv data/gold.csv \
      --model cardiffnlp/twitter-xlm-roberta-base-sentiment   # baseline (Model A)
"""

from __future__ import annotations

import argparse
import csv
import json
import os

from app.core.logging import configure_logging, get_logger
from app.nlp.language import detect_language
from app.nlp.preprocessing import preprocess
from app.nlp.training import metrics
from app.nlp.training.data import normalize_label

# Use only the PyTorch backend (hosted GPU envs ship a TF/Flax that clashes with
# the pinned protobuf; transformers auto-imports whatever backends are present).
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_FLAX", "0")

log = get_logger("training.evaluate")


def load_rows(csv_path: str, text_col: str, label_col: str) -> list[dict]:
    rows: list[dict] = []
    with open(csv_path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            label = normalize_label(r.get(label_col))
            text = (r.get(text_col) or "").strip()
            if label and text:
                rows.append({"text": text, "label": label})
    if not rows:
        raise SystemExit("No labeled rows loaded. Check --text-col / --label-col.")
    return rows


def predict(model_name: str, texts: list[str], max_length: int = 128) -> list[str]:
    from transformers import pipeline

    from app.nlp.sentiment import normalize_label as to_canonical

    pipe = pipeline("text-classification", model=model_name, tokenizer=model_name, top_k=1)
    cleaned = [preprocess(t) for t in texts]
    out: list[str] = []
    for item in pipe(cleaned, truncation=True, max_length=max_length, batch_size=32):
        top = item[0] if isinstance(item, list) else item
        out.append(to_canonical(top["label"]))
    return out


def main() -> None:
    configure_logging()
    ap = argparse.ArgumentParser(description="Evaluate a sentiment model per language.")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--model", required=True, help="Local path or HuggingFace id.")
    ap.add_argument("--text-col", default="text")
    ap.add_argument("--label-col", default="label")
    args = ap.parse_args()

    rows = load_rows(args.csv, args.text_col, args.label_col)
    y_true = [r["label"] for r in rows]
    y_pred = predict(args.model, [r["text"] for r in rows])
    languages = [detect_language(r["text"]).language for r in rows]

    report = metrics.summary(y_true, y_pred)
    report["per_language"] = metrics.per_language_f1(y_true, y_pred, languages)

    print(json.dumps(report, indent=2))
    print("\nPer-language macro-F1:")
    for lang, m in sorted(report["per_language"].items()):
        print(f"  {lang:8s} F1={m['macro_f1']:.4f}  acc={m['accuracy']:.4f}  n={m['support']}")


if __name__ == "__main__":
    main()
