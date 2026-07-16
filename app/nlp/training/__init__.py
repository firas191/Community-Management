"""Fine-tuning and evaluation for the Tunisian Arabizi model (brief Section 9.2).

  data.py       pure: label normalization, seeded stratified split, class weights.
  metrics.py    pure: precision/recall/F1, macro-F1, per-language table, confusion.
  finetune_tunizi.py  the training script (transformers Trainer + MLflow). GPU job.
  evaluate.py         load a model, predict a test set, print the per-language table.

The pure modules are unit-tested against hand-computed values. Training itself
runs on a free Colab/Kaggle GPU (see notebooks/finetune_tunizi.ipynb); the base
models are small (110-270M params), so a T4 handles it in minutes.
"""
