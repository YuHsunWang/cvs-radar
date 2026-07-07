# CVS Sentiment Backend Upgrade Report

## Scope

Implemented the e9d/j1g sentiment upgrade:

- Added selectable sentiment backends: `lexicon`, `snownlp`, and `llm`.
- Preserved PRD F3.2: the PTT push/boo tag prior remains the primary signal via `SENTIMENT["tag_prior_weight"]`; text backends only score the comment text portion.
- Added an LLM backend interface that is default-off and falls back locally when no API key or client is configured. It does not call the network without a key.
- Generated `outputs/eval/backend_comparison.csv`.
- Generated `data/labels/to_label_v1.csv` from demo data for human labeling, with label fields intentionally blank.

## Existing Gold Evaluation

Gold file: `data/labels/gold_smoke.csv`

Rows: 8

This is a smoke test only. Eight rows is statistically insufficient for representative validation.

| Backend | Sentiment polarity accuracy | Meets >=80% target on smoke set |
| --- | ---: | --- |
| lexicon | 1.0000 | yes |
| snownlp | 1.0000 | yes |

LLM was skipped in the comparison because no API key is configured. With the current default config, `SENTIMENT["backend"] = "llm"` falls back to the configured local backend instead of erroring.

## Target Status

The current smoke-set result reaches the >=80% polarity target numerically, but it is not representative evidence. Reaching and verifying the PRD target requires:

- User-provided human labels on a larger dataset, starting with `data/labels/to_label_v1.csv`.
- A real PTT crawl. This sandbox cannot access `ptt.cc`, so crawl-backed validation must be run by the user in an environment with network access.
- Re-running the evaluation harness on the larger human-labeled gold CSV.

No gold labels were fabricated. `data/labels/to_label_v1.csv` is for human labeling only.

## Verification

- Installed `snownlp>=0.12.3` into the existing `.venv` with `uv pip install -p .venv snownlp`.
- `pytest` is not installed in the venv, so the existing unittest suite was used.
- Command run: `.venv/bin/python -m unittest discover -s tests -v`
- Result: 45 tests passed.
