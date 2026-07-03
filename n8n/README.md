# ShadeScout — n8n workflow

An n8n version of the pipeline implemented in `../shadescout/` (Python
CLI), plus one n8n-only extra step (node 4, backyard render/panorama/
video). Steps 1-3 are the same providers/filtering logic in both — pick
whichever fits your infrastructure — and are not a copy that will drift
silently: the Code nodes intentionally mirror the Python modules
function-for-function (`shadescout/clients/realty.py` → node 2,
`shadescout/pipeline.py` → node 3) so a fix in one place is easy to port
to the other. Node 4 (render/panorama/teaser video) has no Python
equivalent yet.

## Import

1. In n8n: **Workflows → Import from File** → select `shadescout-workflow.json`.
2. Paste your keys directly where they're used — this workflow does
   **not** rely on `$env`/`$vars` (those require self-hosted n8n with
   process env vars, or the Variables feature, and don't work on every
   plan/setup), and everything below lives in only three nodes:
   - **RealtyAPI key**: open node **1. RealtyAPI Search By Zip** → Headers
     tab → replace the `x-realtyapi-key` value's
     `PASTE_YOUR_REALTYAPI_KEY_HERE` placeholder with your real key.
   - **Google Maps key, OpenRouter key, and the vision model** all live at
     the top of **3. Imagery, Vision, Filter & Postcard**. Open its code
     and edit the three `const` lines right at the top:
     `GOOGLE_MAPS_API_KEY`, `OPENROUTER_API_KEY`, and `VISION_MODEL`.
   - **OpenRouter key again, plus the image/video model slugs and the
     video toggle**, live at the top of **4. Backyard Render, Panorama &
     Teaser Video**: `OPENROUTER_API_KEY`, `IMAGE_MODEL`, `VIDEO_MODEL`,
     and `GENERATE_VIDEO` (leave it `false` until you're ready to spend
     on a video — see the node's row below).

   Trade-off: the keys now live in the workflow JSON in plain text. That's
   fine for a private workflow only you can see, but **never export or
   share this file once the keys are filled in** — export a fresh copy
   from this repo (with placeholders) if you need to share it. If your n8n
   instance does support environment variables and you'd rather use those,
   swap the `const X = 'PASTE_...'` lines back to `$env.X` (self-hosted) or
   `$vars.X` ([n8n Variables](https://docs.n8n.io/environments/variables/),
   Cloud-compatible) instead.
3. Open the **Config** node and edit `location` (must be a 5-digit ZIP —
   see the caveat below) and `limit`. (This node only holds search
   parameters — `location`, `limit`, `maxDaysSinceSale`, `searchType`,
   `propertyType` — not credentials or model slugs; those are all in
   nodes 3 and 4, see above.)
4. Click **Execute workflow**.

## What each node does

| # | Node | Mirrors (Python) | Notes |
|---|------|-------------------|-------|
| — | Manual Trigger | — | Swap for a Cron/Schedule Trigger to run this daily/weekly per target ZIP. |
| — | Config | CLI `--location` / `--limit` args + `REALTYAPI_SEARCH_TYPE` / `REALTYAPI_PROPERTY_TYPE` | Search parameters only — no credentials, no model slugs. Plain values, fine to edit in the UI. |
| 1 | RealtyAPI Search By Zip | `clients/realty.py: RealtyAPIClient` | Native HTTP Request node. Request/response shape confirmed against live calls. RealtyAPI key pasted directly in the Headers tab. |
| 2 | Normalize & Filter Properties | `clients/realty.py: _extract_records/_to_listings_realtyapi` | Code node, runs once, outputs one n8n item per qualifying property (age-filtered by `maxDaysSinceSale`, sorted, limited), including the lat/lng embedded in each RealtyAPI record. |
| 3 | Imagery, Vision, Filter & Postcard | `pipeline.py: process_property` + `build_postcard_text` + `clients/geocoding.py` + `clients/weather.py` | One self-contained Code node doing Steps 3-7: resolves coordinates (embedded lat/lng preferred; Google Geocoding only as per-property fallback), fetches satellite + street view images, calls OpenRouter with the exact required vision prompt, applies the has_patio/already_covered filter, and builds postcard copy (with a best-effort Open-Meteo forecast for the temperature line). Google/OpenRouter keys and the vision model slug are all `const`s at the top of this node's code — it doesn't read anything from the Config node. Runs once for all items and loops with a per-property try/catch, matching the Python pipeline's "one bad property doesn't abort the batch" behavior. |
| 4 | Backyard Render, Panorama & Teaser Video | *(n8n only — not yet in the Python CLI)* | Self-contained Code node that takes every qualified lead from node 3 and, using OpenRouter's Image API, generates a photorealistic backyard render with a pergola installed (referencing the satellite + street-view images already on the item) and then a true 360° equirectangular panorama of that render. If `GENERATE_VIDEO` is set to `true`, it also submits a 5-second teaser video job to OpenRouter's async Video API (Seedance 2.0 Fast) and polls until it's ready. Render/panorama/video failures don't drop the lead — the postcard text from node 3 still goes through; see "Node 4 observability" below. |
| 5 | Qualified Leads (Postcard-Ready) | CLI `--output` | End of the pipeline — attach whatever you want here: Google Sheets, Airtable, a print/mail-house API, Slack notification, etc. |

### Node 3 observability

- **Missing credentials fail loudly**: if the `GOOGLE_MAPS_API_KEY` /
  `OPENROUTER_API_KEY` placeholders at the top of node 3 weren't replaced
  with real keys, the node throws immediately and tells you which one,
  instead of silently producing an empty result. (There's no equivalent
  check needed for `VISION_MODEL` — an invalid slug fails at the
  OpenRouter call itself, surfaced by the per-call error detail below.)
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
  for a currently valid vision-capable slug and update the `VISION_MODEL`
  constant at the top of this same node.
- **The analyzed images are attached as binary data** (`satellite` and
  `street_view` properties) on each qualified lead. View them in the
  execution panel's Output → Binary tab, or feed them to downstream nodes
  (email attachment, Drive upload, the postcard print API).

### Node 4 observability

- **Best-effort, not battle-tested**: OpenRouter's Image API
  (`/api/v1/images`) and Video API (`/api/v1/videos`) are recent
  additions, and their docs pages block automated fetching, so this
  node's exact field names (`input_references`, `frame_images`,
  `unsigned_urls`, etc.) come from their published docs/blog and a
  third-party integration that quotes the same schema — not a live test
  run against your key. If the first real run 404s or the response
  shape doesn't match, `safeRequest` will name exactly which call
  (`OpenRouter backyard render`, `OpenRouter panorama`, `OpenRouter video
  (submit|poll|download)`) failed and why — paste that back for a
  one-line fix, same loop as node 3's `VISION_MODEL`.
- **Missing credentials fail loudly**: same `PASTE_...` placeholder guard
  as node 3, for `OPENROUTER_API_KEY`.
- **Render/panorama/video failures never drop a lead**: these are bonus
  visuals for the pitch, not a filter. If image generation fails, the
  lead still passes through with just `satellite`/`street_view` binaries
  (from node 3) and its postcard text. If only the video step fails
  (timeout or job error), you still get the render + panorama. The
  per-property run log (`RENDER_OK` / `RENDER_FAILED` / `PANORAMA_OK` /
  `VIDEO_OK` / `VIDEO_SKIPPED` / `VIDEO_FAILED`, with reasons) prints via
  `console.log` on every run.
- **`GENERATE_VIDEO` is `false` by default** — video generation is an
  async job that takes on the order of minutes per property and is
  billed per generation by the provider. Leave it off while testing the
  render/panorama steps (fast, cheap), and only flip it on for a lead
  you've already reviewed and actually want to send a teaser video for.
  When it's on, this node polls every 5 seconds for up to ~4 minutes
  before giving up on a single property's video — the whole node's
  execution stays open for that long, so make sure your n8n instance's
  workflow timeout (if any) allows for it.
- **New binary properties**: `backyard_render` (PNG), `panorama` (PNG,
  equirectangular 2:1), and — only when a video succeeds —
  `teaser_video` (MP4), all viewable the same way as `satellite`/
  `street_view` in the execution panel's Output → Binary tab.

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
  OpenRouter vision call, plus 1 Geocoding call only if the record lacked
  embedded coordinates. Keep `limit` small while testing.
- With node 4 in the mix, every qualifying property additionally costs 2
  OpenRouter image-generation calls (render + panorama) and, only when
  `GENERATE_VIDEO = true`, 1 OpenRouter video-generation job — by far the
  most expensive and slowest call in the whole pipeline. Keep it off
  until you're sending to a specific reviewed lead.
- Open-Meteo (weather) is free and unlimited for reasonable use, no key.
