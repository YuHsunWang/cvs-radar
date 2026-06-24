Implemented tasks A-E.

Changed:
- [config.py](/home/user/github-work/YuHsunWang/cvs-radar/cvs_radar/config.py): updated suspicion weights, renamed `repeated_text` to `template_like`, added burst config.
- [preference.py](/home/user/github-work/YuHsunWang/cvs-radar/cvs_radar/preference.py): added template-like detection with bigram Jaccard + union-find, short-text exclusion, burst ratio detection, and profile timestamp collection.
- [reporting.py](/home/user/github-work/YuHsunWang/cvs-radar/cvs_radar/reporting.py): added `render_suspicion_detail(...)`.
- [test_suspicion.py](/home/user/github-work/YuHsunWang/cvs-radar/tests/test_suspicion.py): added burst, template, detail rendering, and credibility regression tests.

Verification:
` .venv/bin/python -m pytest tests/ -v`

Result: `58 passed, 2 warnings in 31.51s`

Warnings are from `snownlp` using deprecated `codecs.open()` under Python 3.14.

I did not push to git. I also did not commit. Beads issue `cvs-radar-l53` was created and closed locally, so `.beads/*` changed.