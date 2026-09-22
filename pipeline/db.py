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

    That pair is backed by the partial unique index added in migration 001 —
    it is what makes this operation idempotent. Run the pipeline five times and
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
