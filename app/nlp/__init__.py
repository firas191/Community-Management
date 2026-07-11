"""NLP package: preprocessing, language detection, and sentiment (brief Section 9).

The multilingual sentiment pipeline is the project differentiator. Tunisian
social comments mix French, English, Modern Standard Arabic, and Tunisian
Arabizi (dialect in Latin letters and digits). Generic sentiment tools fail on
Arabizi. This package handles all four registers with measured, traceable output.

Layering (kept strict, like the analytics package):
  preprocessing.py  pure text cleaning. str in, str/features out. No models.
  language.py       pure language routing incl. the Arabizi rule layer. No models.
  sentiment.py      the model boundary: a backend Protocol, a lazy transformers
                    implementation, and an analyzer that wires preprocessing +
                    language + inference. The backend is injectable, so the whole
                    pipeline is unit-tested without downloading model weights.
  service.py        the only layer with a database. Batch-analyzes comments and
                    aggregates sentiment summaries.
"""
