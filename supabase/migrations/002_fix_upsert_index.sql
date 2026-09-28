-- Migration 002 — make the (source_name, external_id) index usable by upserts
--
-- Run this in the Supabase SQL editor (Dashboard → SQL Editor → New query).
-- Safe to re-run.
--
-- WHY THIS EXISTS
-- ---------------
-- Migration 001 created the uniqueness guarantee as a PARTIAL unique index:
--
--     create unique index ... on events (source_name, external_id)
--         where source_name is not null and external_id is not null;
--
-- That enforces the right rule, but it cannot be used by INSERT ... ON CONFLICT.
-- Postgres will only infer a partial index for conflict resolution if the
-- statement repeats the index predicate, and PostgREST (which is what the
-- Python pipeline talks to) offers no way to send one. The result is that every
-- upsert fails with:
--
--     42P10: there is no unique or exclusion constraint matching the
--            ON CONFLICT specification
--
-- The predicate was never needed. It was added so that user-submitted events,
-- which leave both columns NULL, would not collide with each other — but
-- Postgres already treats NULLs as DISTINCT in a unique index, so any number of
-- (NULL, NULL) rows coexist happily under a plain one. We get the same
-- protection and working upserts.
--
-- (Do not "improve" this later by adding NULLS NOT DISTINCT — that would make
-- every user-submitted event collide with every other one.)


-- Out with the partial index...
drop index if exists public.events_source_external_id_uidx;

-- ...and in with a plain one that ON CONFLICT can actually infer.
create unique index if not exists events_source_external_id_uidx
    on public.events (source_name, external_id);


-- Verification — should return one row, with indexdef containing no WHERE.
--
--   select indexname, indexdef from pg_indexes
--    where tablename = 'events' and indexname = 'events_source_external_id_uidx';
