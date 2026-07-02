# ShadeScout

An autonomous lead-generation pipeline for pergola/shade installers. Given a
target location, it finds recently-sold homes, inspects each backyard with
satellite + street-level imagery and a vision model, and outputs
hyper-personalized postcard copy for the properties that are actually good
fits (has a patio, isn't already shaded).

Two implementations of the same pipeline are provided:
- **`shadescout/`** — a Python CLI (documented below).
- **`n8n/`** — an importable n8n workflow, for teams that prefer running
  this as a scheduled visual workflow instead of a script. See
  [`n8n/README.md`](n8n/README.md).

## How it works

For each target location, ShadeScout runs:

1. **Lead generation** — pull recently-sold properties from a real estate
   data API.
2. **Geocode** each address to lat/lng (Google Geocoding API).
3. **Image acquisition** — grab a top-down satellite image and a
   street-level image (Google Static Maps / Street View Static API).
4. **Vision analysis** — ask a vision LLM (via OpenRouter) whether the
   property has a patio/deck, whether it's already shaded, and how many
   hours of direct sun it gets.
5. **Filter** — drop properties with no patio, or that are already covered.
6. **Postcard generation** — turn the sun-hours estimate (plus an optional
   real weather forecast) into ready-to-print postcard copy.

Output is a JSON array of qualified leads:

```json
[
  {
    "lead_status": "QUALIFIED",
    "property_address": "123 Main St, Austin, TX 78704",
    "coordinates": { "lat": 30.25, "lng": -97.75 },
    "sun_hours": 10,
    "postcard_text": "Your patio takes 10 hours of direct sun a day. This Saturday it hits 97°. Scan this QR code to see how a louvered pergola looks in your exact backyard."
  }
]
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in your API keys
```

```bash
python main.py --location 78704 --limit 10 --output leads.json -v
```

`--location` must be a 5-digit ZIP code with the default provider
(realtyapi.io only exposes a by-ZIP search endpoint). The `rentcast` and
`rapidapi_realtymole` providers also accept `"City, ST"`.

Use `--save-images` to also write the satellite/street-view PNGs used for
each qualified lead to `--image-dir` (default `images/`).

## API keys required

| Variable | Used for | Where to get it |
| --- | --- | --- |
| `REALTYAPI_KEY` | Recently-sold property data (default provider) | https://www.realtyapi.io/ — free tier, 250 requests/month, no card required at signup |
| `GOOGLE_MAPS_API_KEY` | Geocoding, Static Maps (satellite), Street View | https://console.cloud.google.com/google/maps-apis — enable Geocoding API, Maps Static API, Street View Static API |
| `OPENROUTER_API_KEY` | Vision analysis (Claude 3.5 Sonnet / GPT-4o etc.) | https://openrouter.ai/keys |

No key is required for the postcard weather personalization — it uses
[Open-Meteo](https://open-meteo.com), which is free and keyless.

### On the property-data provider

The default is `REALTY_PROVIDER=realtyapi` (realtyapi.io), because its free
tier doesn't ask for a credit card at signup. **Caveat:** realtyapi.io's own
docs site blocks automated tooling, so the endpoint (`/search/byzip`) and
response field names in `shadescout/clients/realty.py` were assembled from
third-party sources, not verified against a live response. The parser
(`_to_listings_realtyapi`) tries several plausible field-name variants
defensively, but if your first real run comes back with zero results, run
with `-v`, inspect the raw response, and adjust `_ADDRESS_KEYS` /
`_SALE_DATE_KEYS` / `_PRICE_KEYS` / `_RECORDS_CONTAINER_KEYS` at the top of
that file to match.

Two other providers are built in and can be selected via `REALTY_PROVIDER`:

- `rentcast` — [RentCast](https://www.rentcast.io/)'s own API (the company
  that Realty Mole was folded into). Also has a free tier, but their signup
  flow does ask for card details, which is why it isn't the default. Set
  `RENTCAST_API_KEY` instead of `REALTYAPI_KEY`.
- `rapidapi_realtymole` — the original RapidAPI "Realty Mole Property API"
  listing, kept for teams with an existing RapidAPI subscription. Set
  `RAPIDAPI_KEY`.

Other free/low-cost alternatives worth knowing about if none of the above
fit:
- **Apify Real Estate API** — actor-based scraper (Zillow/Redfin/Realtor),
  no-card signup, free monthly platform credit. Different call shape
  (trigger a run, then fetch results) than the REST clients here.
- **ATTOM Data API** — broad property/sales history data, has a free trial tier.
- **County assessor open data** — completely free where available, but
  coverage and "recently sold" freshness vary a lot by county, and it's not
  a drop-in API (custom per county/state).

Scraping Zillow/Redfin directly is explicitly against their Terms of Service
and isn't used here.

## Configuration reference

See `.env.example` for the full list. Notable optional settings:

- `MAX_DAYS_SINCE_SALE` (default `180`) — properties whose last recorded sale
  is older than this are skipped, since the whole pitch is "you just moved
  in, here's your backyard."
- `VISION_MODEL` (default `anthropic/claude-3.5-sonnet`) — any OpenRouter
  vision-capable model ID works, e.g. `openai/gpt-4o`.

## Project layout

```
shadescout/
  config.py           # env-based settings + validation
  models.py            # PropertyListing, VisionAnalysis, QualifiedLead, ...
  errors.py             # one exception type per pipeline stage
  http.py                # shared retrying HTTP helpers
  pipeline.py             # orchestrates steps 2-7, postcard copy generation
  cli.py                   # argparse entry point
  clients/
    realty.py               # Step 1: RentCast / RapidAPI Realty Mole
    geocoding.py             # Step 3: Google Geocoding
    imagery.py                # Step 4: Static Maps + Street View
    vision.py                  # Step 5/6: OpenRouter vision call + parsing
    weather.py                  # optional postcard weather personalization
main.py                          # `python main.py ...`
tests/                            # unit tests, all HTTP calls mocked
```

## Testing

```bash
pip install -r requirements-dev.txt
pytest
```

All tests mock HTTP calls — no API keys or network access are needed to run
the test suite.

## Notes / limitations

- A single failing property (bad geocode, imagery timeout, unparseable
  vision response) is logged and skipped; it does not abort the whole run.
- The vision model's JSON output is extracted with a best-effort regex to
  tolerate models that wrap their answer in markdown code fences.
- Postcard temperature personalization is best-effort: if the weather
  lookup fails, the postcard still generates, just without a specific
  day/temperature.
