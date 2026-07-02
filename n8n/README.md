# ShadeScout — n8n workflow

An n8n version of the same pipeline implemented in `../shadescout/` (Python
CLI). Same steps, same providers, same filtering logic — pick whichever
fits your infrastructure. This is not a copy that will drift silently: the
Code nodes intentionally mirror the Python modules function-for-function
(`shadescout/clients/realty.py` → node 2, `shadescout/pipeline.py` → node 4)
so a fix in one place is easy to port to the other.

## Import

1. In n8n: **Workflows → Import from File** → select `shadescout-workflow.json`.
2. Set three environment variables on the n8n instance itself (not inside
   the workflow — never paste real keys into node parameters, they get
   saved into the workflow JSON in plain text):
   - `REALTYAPI_KEY`
   - `GOOGLE_MAPS_API_KEY`
   - `OPENROUTER_API_KEY`

   Self-hosted (Docker Compose example):
   ```yaml
   environment:
     - REALTYAPI_KEY=your_key
     - GOOGLE_MAPS_API_KEY=your_key
     - OPENROUTER_API_KEY=your_key
   ```
   Or export them before `n8n start` if running the CLI directly.

   n8n Cloud does not expose custom process env vars to workflows. If
   you're on Cloud, the workaround is to replace the `$env.XXX` references
   in nodes **1**, **3**, and **4** with n8n's built-in
   [Variables](https://docs.n8n.io/environments/variables/) feature
   (`$vars.XXX`) instead — functionally identical, just a different
   secret-storage mechanism.
3. Open the **Config** node and edit `location` (must be a 5-digit ZIP —
   see the caveat below) and `limit`.
4. Click **Execute workflow**.

## What each node does

| # | Node | Mirrors (Python) | Notes |
|---|------|-------------------|-------|
| — | Manual Trigger | — | Swap for a Cron/Schedule Trigger to run this daily/weekly per target ZIP. |
| — | Config | CLI `--location` / `--limit` args | Plain values, not secret — fine to edit in the UI. |
| 1 | RealtyAPI Search By Zip | `clients/realty.py: RealtyAPIClient` | Native HTTP Request node. |
| 2 | Normalize & Filter Properties | `clients/realty.py: _extract_records/_to_listings_realtyapi` | Code node, runs once, outputs one n8n item per qualifying property (age-filtered by `maxDaysSinceSale`, sorted, limited). |
| 3 | Geocode Address | `clients/geocoding.py` | Native HTTP Request node, `continueOnFail` on — a bad address doesn't kill the run, node 4 just skips it. |
| 4 | Imagery, Vision, Filter & Postcard | `pipeline.py: process_property` + `build_postcard_text` + `clients/weather.py` | One Code node doing Steps 4-7: fetches satellite + street view images, calls OpenRouter with the exact required vision prompt, applies the has_patio/already_covered filter, and builds postcard copy (with a best-effort Open-Meteo forecast for the temperature line). Runs once for all items and loops with a per-property try/catch, matching the Python pipeline's "one bad property doesn't abort the batch" behavior. |
| 5 | Qualified Leads (Postcard-Ready) | CLI `--output` | End of the pipeline — attach whatever you want here: Google Sheets, Airtable, a print/mail-house API, Slack notification, etc. |

## Caveat: RealtyAPI field names are unverified

Same caveat as the Python client: realtyapi.io's docs site blocks automated
fetching, so the `/search/byzip` endpoint and its response field names
(node 1 and the top of node 2's code) were assembled from third-party
sources, not a verified live response. Node 2 tries several plausible
field-name variants defensively. If a real execution returns zero
properties, open node 2's execution data, inspect the raw input JSON from
node 1, and adjust `ADDRESS_KEYS` / `SALE_DATE_KEYS` / `PRICE_KEYS` /
`CONTAINER_KEYS` at the top of node 2's code to match — then port the same
fix to `shadescout/clients/realty.py` in the Python version.

## Cost / rate-limit awareness

- RealtyAPI free tier: 250 requests/month.
- Every qualifying property costs 1 Geocoding call + 2 Static Maps/Street
  View calls + 1 OpenRouter vision call (the priciest part — vision models
  are billed per image token). Keep `limit` small while testing.
- Open-Meteo (weather) is free and unlimited for reasonable use, no key.
