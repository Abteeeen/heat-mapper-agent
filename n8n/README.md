# ShadeScout — n8n workflow

An n8n version of the same pipeline implemented in `../shadescout/` (Python
CLI). Same steps, same providers, same filtering logic — pick whichever
fits your infrastructure. This is not a copy that will drift silently: the
Code nodes intentionally mirror the Python modules function-for-function
(`shadescout/clients/realty.py` → node 2, `shadescout/pipeline.py` → node 4)
so a fix in one place is easy to port to the other.

## Import

1. In n8n: **Workflows → Import from File** → select `shadescout-workflow.json`.
2. Paste your three keys directly where they're used — this workflow does
   **not** rely on `$env`/`$vars` (those require self-hosted n8n with
   process env vars, or the Variables feature, and don't work on every
   plan/setup):
   - **RealtyAPI key**: open node **1. RealtyAPI Search By Zip** → Headers
     tab → replace the `x-realtyapi-key` value's
     `PASTE_YOUR_REALTYAPI_KEY_HERE` placeholder with your real key.
   - **Google Maps key**: open node **3. Imagery, Vision, Filter &
     Postcard** → find `const GOOGLE_MAPS_API_KEY = 'PASTE_...'` near the
     top of the code and replace the placeholder.
   - **OpenRouter key**: same node, `const OPENROUTER_API_KEY = 'PASTE_...'`.

   Trade-off: the keys now live in the workflow JSON in plain text. That's
   fine for a private workflow only you can see, but **never export or
   share this file once the keys are filled in** — export a fresh copy
   from this repo (with placeholders) if you need to share it. If your n8n
   instance does support environment variables and you'd rather use those,
   swap the `const X = 'PASTE_...'` lines back to `$env.X` (self-hosted) or
   `$vars.X` ([n8n Variables](https://docs.n8n.io/environments/variables/),
   Cloud-compatible) instead.
3. Open the **Config** node and edit `location` (must be a 5-digit ZIP —
   see the caveat below) and `limit`.
4. Click **Execute workflow**.

## What each node does

| # | Node | Mirrors (Python) | Notes |
|---|------|-------------------|-------|
| — | Manual Trigger | — | Swap for a Cron/Schedule Trigger to run this daily/weekly per target ZIP. |
| — | Config | CLI `--location` / `--limit` args + `REALTYAPI_SEARCH_TYPE` / `REALTYAPI_PROPERTY_TYPE` | Plain values, not secret — fine to edit in the UI. |
| 1 | RealtyAPI Search By Zip | `clients/realty.py: RealtyAPIClient` | Native HTTP Request node. Request/response shape confirmed against live calls. |
| 2 | Normalize & Filter Properties | `clients/realty.py: _extract_records/_to_listings_realtyapi` | Code node, runs once, outputs one n8n item per qualifying property (age-filtered by `maxDaysSinceSale`, sorted, limited), including the lat/lng embedded in each RealtyAPI record. |
| 3 | Imagery, Vision, Filter & Postcard | `pipeline.py: process_property` + `build_postcard_text` + `clients/geocoding.py` + `clients/weather.py` | One Code node doing Steps 3-7: resolves coordinates (embedded lat/lng preferred; Google Geocoding only as per-property fallback), fetches satellite + street view images, calls OpenRouter with the exact required vision prompt, applies the has_patio/already_covered filter, and builds postcard copy (with a best-effort Open-Meteo forecast for the temperature line). Runs once for all items and loops with a per-property try/catch, matching the Python pipeline's "one bad property doesn't abort the batch" behavior. |
| 4 | Qualified Leads (Postcard-Ready) | CLI `--output` | End of the pipeline — attach whatever you want here: Google Sheets, Airtable, a print/mail-house API, Slack notification, etc. |

### Node 3 observability

- **Missing credentials fail loudly**: if the `GOOGLE_MAPS_API_KEY` /
  `OPENROUTER_API_KEY` placeholders at the top of node 3 weren't replaced
  with real keys, the node throws immediately and tells you which one,
  instead of silently producing an empty result.
- **Per-property run log**: every property's outcome (`QUALIFIED` /
  `DISQUALIFIED` / `SKIP` / `ERROR` with the reason) is written via
  `console.log` and, when *zero* leads qualify, thrown as the node error —
  so an empty run always tells you why.
- **Per-call error detail**: each of the four external HTTP calls (Google
  Static Maps, Google Street View, OpenRouter vision, and the Google
  Geocoding fallback) is wrapped so a failure names the specific endpoint,
  method, URL, HTTP status, and up to 300 chars of the response body —
  e.g. `OpenRouter vision (POST https://openrouter.ai/...) failed:
  status=404 body={"error":{"message":"No endpoints found for
  anthropic/claude-3.5-sonnet"}}`. Without this, n8n's HTTP helper only
  surfaces a bare `"Request failed with status code 404"` with no way to
  tell which of the four calls failed or why. If you see a 404 naming the
  OpenRouter model, check [openrouter.ai/models](https://openrouter.ai/models)
  for a currently valid vision-capable slug and update `visionModel` in
  the Config node — no code changes needed.
- **The analyzed images are attached as binary data** (`satellite` and
  `street_view` properties) on each qualified lead. View them in the
  execution panel's Output → Binary tab, or feed them to downstream nodes
  (email attachment, Drive upload, the postcard print API).

## RealtyAPI request/response (confirmed against the OpenAPI spec + live calls)

`/search/byzip` params (per `https://realtor.realtyapi.io/openapi.json`):
`zipCode` (required), `searchType` (`For_Sale` — the default if omitted —
`For_Rent`, `Sold`; comma-separated combos allowed), `resultCount` (per
page, default 50, max 200), `sortOrder` (`Most_Recently_Sold` is only
meaningful with `searchType=Sold`), and `propertyType` (`House, Condo,
Townhome, Multi_Family, Mobile, Farm, Land, Co-op`). Unknown param names
are silently ignored — not rejected — so typos degrade to default
(for-sale) results rather than an error.

The response wraps results as `[{"searchResults": [...], "total": N, ...}]`.
Each record carries realtor.com-style fields: a nested `address` object
(`line`, `city`, `state_code`, `postal_code`, `latitude`, `longitude`),
plus `last_sold_date`, `last_sold_price`, `list_price`, and `status`.
Node 2 parses exactly this, with alternate key names kept as fallbacks.

The Config node defaults to `searchType=Sold` (the whole pitch targets
recent buyers) and `propertyType=House` (condos/apartments have no backyard
for a pergola) — both editable in the UI.

## Cost / rate-limit awareness

- RealtyAPI free tier: 250 requests/month.
- Every qualifying property costs 2 Static Maps/Street View calls + 1
  OpenRouter vision call (the priciest part — vision models are billed per
  image token), plus 1 Geocoding call only if the record lacked embedded
  coordinates. Keep `limit` small while testing.
- Open-Meteo (weather) is free and unlimited for reasonable use, no key.
