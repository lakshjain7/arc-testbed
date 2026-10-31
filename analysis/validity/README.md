# Validity tests of the damage labels (dataset v1.0)

Run on the released tables (`arc-release/hf`) and, for test 4, the raw archives (`arc-release/zenodo`). Paths at the top of each script point to the
release folder on the author's laptop; change `D` to run elsewhere. Values in the tables are fractions; the scripts convert to percentage points.

| Script | Test |
|---|---|
| `t123.py` | 1 negative control (no fault + no-op), 2 dose-response (fault level vs bad-request share before the action), 3 service counters vs the load generator's log |
| `diag.py` | where test 3 disagrees; test 2 within each target service |
| `t4.py` | 4 mechanism: damage of each action by position relative to the target (call graph from `edges.csv.gz`), minus the no-op of the same block |

Results are written to the report (Chapter 4, section 4.9, Table 4.5).
