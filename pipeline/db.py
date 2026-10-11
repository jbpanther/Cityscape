"""
Writing events into Supabase.

One job: take normalized rows and upsert them, so re-running a pipeline updates
what is already there instead of creating duplicates.
"""

import logging

from supabase import create_client

import config

log = logging.getLogger(__name__)

# Rows per request. Large enough to be efficient, small enough that a failure
# doesn't cost much work and the error message stays readable.
BATCH_SIZE = 200


def get_client():
    """
    Build a Supabase client using the SERVICE-ROLE key.

    The service-role key bypasses Row-Level Security, which is required here:
    scraped events have `created_by = NULL`, and the "events insertable by
    owner" policy demands auth.uid() = created_by. No anonymous client can
    satisfy that, by design.
    """
    return create_client(config.supabase_url(), config.supabase_service_key())


def upsert_events(client, rows, batch_size: int = BATCH_SIZE) -> int:
    """
    Insert-or-update events, matching on (source_name, external_id).

    That pair is backed by the unique index from migrations 001/002 — it is what
    makes this operation idempotent. The index must NOT be partial, or this call
    fails with 42P10; see migration 002. Run the pipeline five times and
    you get one copy of each event, with the latest details.

    Returns the number of rows written.
    """
    if not rows:
        return 0

    written = 0
    for start in range(0, len(rows), batch_size):
        batch = rows[start:start + batch_size]

        response = (
            client.table("events")
            .upsert(batch, on_conflict="source_name,external_id")
            .execute()
        )

        written += len(response.data or [])
        log.info("Upserted %d/%d rows", written, len(rows))

    return written


def prune_missing(client, source_name: str, city: str, keep_external_ids,
                  start_from: str, start_to: str) -> int:
    """
    Delete upcoming rows from a source that its latest full run no longer produced.

    Upserts never delete, so without this every change in how rows are shaped
    (one row per performance → one row per show) leaves the old rows behind on
    the map forever. It also removes events the source has since dropped.

    Only rows that START inside the run's search window are candidates. That
    window is what makes this safe:
      - an event already under way (start < now) was never going to be
        re-fetched, so it is left alone, as is a festival mid-run;
      - events beyond the --days horizon were outside the search, so absence
        from the run says nothing about them.
    User-submitted events have no source_name and are never touched.

    Note this deletes the row's votes too. Fine while the app has no real users.

    Returns the number of rows deleted.
    """
    keep = set(keep_external_ids)
    stale_ids, offset, page_size = [], 0, 1000
    while True:
        page = (
            client.table("events")
            .select("id, external_id")
            .eq("source_name", source_name)
            .eq("city", city)
            .gte("start_at", start_from)
            .lte("start_at", start_to)
            .order("id")
            .range(offset, offset + page_size - 1)
            .execute()
        ).data or []
        stale_ids += [r["id"] for r in page if r["external_id"] not in keep]
        offset += page_size
        if len(page) < page_size:
            break

    for start in range(0, len(stale_ids), BATCH_SIZE):
        batch = stale_ids[start:start + BATCH_SIZE]
        client.table("events").delete().in_("id", batch).execute()
        log.info("Deleted %d/%d stale rows", start + len(batch), len(stale_ids))

    return len(stale_ids)
