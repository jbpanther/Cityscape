# Cityscape ingestion pipeline

Python scripts that pull events from external sources into the Supabase
`events` table, so they show up on the map alongside user-submitted events.

Separate from the iOS app on purpose: **the two never talk to each other.**
Python writes rows to Postgres, Swift reads rows from Postgres, and Supabase is
the only contract between them. Either side can be rewritten without touching
the other.

## First-time setup

**1. Run the database migration.** In the Supabase dashboard → SQL Editor → New
query, paste and run `../supabase/migrations/001_add_source_tracking.sql`.
This adds `source_name` and `external_id` to `events` plus the unique index that
makes re-scraping safe. It's safe to run more than once.

**2. Install dependencies** (into a virtual environment, so these packages stay
out of your system Python):

```bash
cd pipeline
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

You'll need to run `source .venv/bin/activate` each time you come back to this.

**3. Get a Ticketmaster API key.** Free, at
<https://developer.ticketmaster.com/> — register an app and copy the *Consumer
Key*. Default quota is 5,000 calls/day at 5 requests/second, which is far more
than this pipeline uses.

**4. Create your `.env`:**

```bash
cp .env.example .env
```

Then fill in the three values. The Supabase ones are in Dashboard → Project
Settings → API.

> ⚠️ **Use the service-role key, not the anon key.** Scraped events have
> `created_by = NULL`, and the RLS policy on `events` requires
> `auth.uid() = created_by` for inserts — no anonymous client can satisfy that.
> The service-role key bypasses RLS, which also makes it a **real secret**:
> anyone holding it has full read/write access to your database. It's gitignored;
> keep it out of the iOS app and out of screenshots.

## Usage

Always start with a dry run — it fetches and normalizes but writes nothing, and
doesn't even need Supabase credentials:

```bash
python run.py --city nyc --limit 20 --dry-run
```

Once the output looks right:

```bash
python run.py --city nyc --days 30        # ingest the next 30 days
python run.py --all-cities --days 14      # every city in config.py
```

Useful flags: `--source` (which adapter), `--window-days` (see below),
`--limit` (stop early), `--verbose` (debug logging).

## Tests

```bash
python test_ticketmaster.py
```

No API key, no network — they run against hand-written payloads. Run them after
changing anything in `sources/ticketmaster.py`.

## How it fits together

```
run.py              CLI: picks cities + source, prints stats, writes
config.py           Secrets (from .env) + the city table
db.py               Supabase client and the idempotent upsert
sources/
  ticketmaster.py   Ticketmaster Discovery API adapter
test_ticketmaster.py
```

Adding a source means writing a module with the same `collect()` signature and
registering it in `SOURCES` in `run.py`. Adding a city means adding an entry to
`CITIES` in `config.py` — no pipeline code changes.

## Things worth knowing

**Re-running is safe.** Rows are upserted on `(source_name, external_id)`, so
running the pipeline five times gives you one copy of each event with the latest
details. Engagement counters (`upvotes`/`downvotes`/`flag_count`) are never sent,
so re-running can't reset votes on an event people have already rated.

**The 1,000-item paging cap.** Ticketmaster won't return past the 1000th result
of any single query (`size × page < 1000`). The pipeline works around this by
splitting the date range into windows (default 7 days) and querying each one. If
you see a `hit the 1000-item paging cap` warning, lower `--window-days`.

**Events get skipped, and that's normal.** Listings without venue coordinates or
without a resolvable start time are dropped — a map-first app has nothing to do
with an event it can't place or schedule. The run summary reports the count.

**End times are assumed.** Ticketmaster rarely supplies one, so we assume 3
hours for a timed event and 24 hours when only a date is known. If events start
disappearing from the map too early, this is the knob.

**NJ venues come back for NYC.** Ticketmaster's "New York" city filter includes
metro-area venues like the Prudential Center. Left in deliberately — they're
plausibly NYC events to a user — but if that turns out wrong, filter on
`stateCode` in `normalize()`.

## Next

- Second source (NYC Open Data street events) — proves the adapter boundary
- Scheduling, so this runs unattended rather than by hand
