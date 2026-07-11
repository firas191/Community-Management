"""Analytics package: KPI formulas, temporal aggregation, and the query service.

Layering (kept strict so the formulas stay trivially testable):
  kpi.py          pure math. Numbers in, Metric out. No DB, no pandas, no I/O.
  aggregation.py  pure pandas. DataFrame in, chart-ready structures out. No DB.
  service.py      the only layer that touches the database. It loads rows, hands
                  them to the pure layers, and assembles API-ready dictionaries.

Everything a recommendation or dashboard number rests on lives in kpi.py and is
unit-tested against hand-computed fixtures (brief Sections 8, 13).
"""
