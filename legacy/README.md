# legacy/

Archived, non-deployed code. Kept for reference only — **not** part of the live
product. Do not read these files when reasoning about current behavior.

## streamlit/

The original Streamlit prototype UI. The live product is the **Next.js app in
`web/`** (deployed to <https://cvs-radar.vercel.app/>); this Streamlit app is no
longer built or served.

- `app.py` — Streamlit entry point.
- `.streamlit/` — Streamlit theme/config.
- `Dockerfile`, `docker-compose.yml` — container that ran `streamlit run app.py`
  on port 8501. Superseded by the Vercel/Next.js deployment.

Still shared and **kept in the package** (imported by `cvs_radar/api.py` and the
test suite), so *not* moved here:

- `cvs_radar/app_helpers.py` — query-shape / formatting helpers used by the API.

The Streamlit-only tests (`import app`: `_load_results_cached`,
`_order_brand_options`, `_product_row_html`) were removed from
`tests/test_core.py` when the app was archived; the shared `app_helpers` tests
remain.

To run the archived app locally (from the repo root):

```bash
streamlit run legacy/streamlit/app.py
```
