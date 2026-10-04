-- Migration 003 — showtimes: one event, several performances
--
-- Run this in the Supabase SQL editor (Dashboard → SQL Editor → New query).
-- Safe to re-run.
--
-- WHY THIS EXISTS
-- ---------------
-- Ticketmaster lists every performance as its own event. For a timed-entry
-- attraction that is absurd — The Banksy Museum sells a slot every 30 minutes,
-- which came out as 19 rows a day, ~570 a month, all stacked on one pin. Shows
-- with several performances a day (The Very Hungry Caterpillar Show, 4/day) have
-- the same problem on a smaller scale.
--
-- The pipeline now merges those into ONE row per attraction per day, whose
-- start_at/end_at span the first performance to the last. This column keeps the
-- individual performances so the app can list them later.
--
-- SHAPE
-- -----
-- NULL for an ordinary single-showing event (start_at/end_at say it all).
-- Otherwise a JSON array sorted by start, one object per performance:
--
--     [
--       {"start_at": "2026-10-04T14:00:00+00:00",
--        "end_at":   "2026-10-05T04:00:00+00:00",
--        "external_id": "LvZ18QrTdtviDfOZvhDWf"},
--       ...
--     ]
--
-- `external_id` is the upstream record for that one performance, kept for
-- provenance and ticket links. Timestamps are ISO-8601 UTC, same as start_at.
--
-- The iOS app ignores this column until it is taught to read it: Event.swift
-- decodes through explicit CodingKeys, so unknown columns are skipped.

alter table public.events
    add column if not exists showtimes jsonb;

-- Guard the shape loosely: if present it must be an array. The pipeline is the
-- only writer; this just stops a typo from storing an object or a string.
alter table public.events
    drop constraint if exists events_showtimes_is_array;
alter table public.events
    add constraint events_showtimes_is_array
    check (showtimes is null or jsonb_typeof(showtimes) = 'array');


-- Verification — should return one row: showtimes | jsonb
--
--   select column_name, data_type from information_schema.columns
--    where table_name = 'events' and column_name = 'showtimes';
