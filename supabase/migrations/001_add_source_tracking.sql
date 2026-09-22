-- Migration 001 — source tracking for ingested (scraped) events
--
-- Run this in the Supabase SQL editor (Dashboard → SQL Editor → New query).
-- Safe to re-run: every statement is IF NOT EXISTS / DROP-then-CREATE.
--
-- WHY THIS EXISTS
-- ---------------
-- `events.source` already tells us *how* an event arrived ('user' | 'scraped' |
-- 'partner'), but not *where from* or *which upstream record it was*. The moment
-- we have two scrapers we need both, for two reasons:
--
--   1. Idempotent re-runs. Re-scraping Ticketmaster every night must UPDATE the
--      rows we already have, not insert duplicates. `(source_name, external_id)`
--      is the natural key to match on.
--   2. Provenance. When an event looks wrong we need to know which pipeline put
--      it there, and be able to go look at the upstream record.
--
-- User-submitted events leave both columns NULL — the unique index below only
-- applies to rows where both are present.


-- ---------------------------------------------------------------------------
-- Columns
-- ---------------------------------------------------------------------------

-- Which pipeline produced this row: 'ticketmaster', 'nyc_open_data', ...
-- NULL for user-submitted events.
alter table public.events
    add column if not exists source_name text;

-- That source's own ID for the event, stored verbatim as text (every provider
-- has a different ID format — don't try to normalize it).
alter table public.events
    add column if not exists external_id text;


-- ---------------------------------------------------------------------------
-- Uniqueness — this is what makes re-scraping safe
-- ---------------------------------------------------------------------------
--
-- A partial unique index (note the WHERE clause) rather than a plain unique
-- constraint, so that the many user-submitted rows with NULLs in both columns
-- don't collide with each other.
--
-- Postgres treats NULLs as distinct in unique indexes, so a plain constraint
-- would technically work too — but being explicit documents the intent and
-- keeps the index small.
create unique index if not exists events_source_external_id_uidx
    on public.events (source_name, external_id)
    where source_name is not null and external_id is not null;


-- Lets us quickly answer "everything Ticketmaster gave us" for debugging and
-- for bulk cleanup if a pipeline ever goes wrong.
create index if not exists events_source_name_idx
    on public.events (source_name)
    where source_name is not null;
