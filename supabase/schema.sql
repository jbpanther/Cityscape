-- Cityscape initial schema (v2)
-- Run this in the Supabase SQL editor (Dashboard → SQL Editor → New query).
--
-- Safe to re-run — everything uses IF NOT EXISTS or DROP-then-CREATE for the
-- generated `location` column. If you already ran v1 and want to reset:
--     drop table if exists public.photos cascade;
--     drop table if exists public.events cascade;
-- then run this file.

-- ---------------------------------------------------------------------------
-- Extensions
-- ---------------------------------------------------------------------------

-- PostGIS gives us proper geographic types + spatial queries (ST_DWithin, etc).
create extension if not exists postgis;


-- ---------------------------------------------------------------------------
-- events table
-- ---------------------------------------------------------------------------
--
-- Design note: we store latitude + longitude as plain doubles (which is what
-- the Swift app naturally has from CoreLocation) and let a trigger keep the
-- PostGIS `location` column in sync. This gives us both:
--   - Simple inserts from the app (no GeoJSON encoding required)
--   - Fast spatial queries via `location` + its GIST index
--
create table if not exists public.events (
    id              uuid primary key default gen_random_uuid(),

    -- Content
    name            text not null,
    description     text not null default '',
    event_type      text,  -- keep unconstrained for now; add CHECK/enum later once categories stabilize

    -- Location — plain doubles as the source of truth.
    latitude        double precision not null,
    longitude       double precision not null,
    -- PostGIS geography, auto-populated by trigger below. Do NOT insert into this directly.
    location        geography(Point, 4326),

    city            text not null,  -- 'nyc' | 'boston' | 'london' for now. Kept as text so we can add cities without a schema change.

    -- When
    start_at        timestamptz not null,
    end_at          timestamptz not null,

    -- Provenance — which ingestion path this event came from.
    source          text not null default 'user' check (source in ('user', 'scraped', 'partner')),

    -- Engagement signals — baked in from day one so we don't retrofit later.
    -- Per-user vote tracking (who voted on what) will live in a separate table when we build voting.
    upvotes         integer not null default 0,
    downvotes       integer not null default 0,
    flag_count      integer not null default 0,

    -- Audit
    created_by      uuid references auth.users(id) on delete set null,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);

-- Spatial index — required for fast "events near me" queries. Without this,
-- PostGIS will do a table scan and get slow past a few thousand rows.
create index if not exists events_location_gix on public.events using gist (location);

-- Support "what's happening in this city right now" queries.
create index if not exists events_city_endat_idx on public.events (city, end_at);

-- Support ordering feeds by freshness.
create index if not exists events_created_at_idx on public.events (created_at desc);


-- ---------------------------------------------------------------------------
-- Auto-populate the `location` column from latitude/longitude
-- ---------------------------------------------------------------------------
-- Trigger fires before insert or update. Keeps `location` in sync with the
-- lat/lng columns so callers only ever have to set the two numbers.
create or replace function public.set_event_location()
returns trigger
language plpgsql
as $$
begin
    new.location = ST_SetSRID(ST_MakePoint(new.longitude, new.latitude), 4326)::geography;
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists events_set_location on public.events;
create trigger events_set_location
    before insert or update on public.events
    for each row
    execute function public.set_event_location();


-- ---------------------------------------------------------------------------
-- photos table
-- ---------------------------------------------------------------------------

create table if not exists public.photos (
    id              uuid primary key default gen_random_uuid(),
    event_id        uuid not null references public.events(id) on delete cascade,

    image_url       text not null,
    description     text not null default '',

    -- Who uploaded. Storing both id (stable) and email (human-readable) matches
    -- how the current Firestore code uses currentUser.email as the reviewer field.
    reviewer_id     uuid references auth.users(id) on delete set null,
    reviewer_email  text,

    posted_at       timestamptz not null default now()
);

create index if not exists photos_event_id_idx on public.photos (event_id);


-- ---------------------------------------------------------------------------
-- Row-Level Security (RLS)
-- ---------------------------------------------------------------------------
-- Supabase turns RLS *on* by default for new tables, which means all access is
-- denied until we write policies. Below are the minimal policies to match the
-- current Firestore behavior (open reads, authenticated writes). We can tighten
-- these once moderation/roles exist.

alter table public.events enable row level security;
alter table public.photos enable row level security;

-- Anyone (including logged-out users) can read events + photos.
drop policy if exists "events readable by all" on public.events;
create policy "events readable by all"
    on public.events for select
    using (true);

drop policy if exists "photos readable by all" on public.photos;
create policy "photos readable by all"
    on public.photos for select
    using (true);

-- Logged-in users can insert events, and only as themselves.
drop policy if exists "events insertable by owner" on public.events;
create policy "events insertable by owner"
    on public.events for insert
    with check (auth.uid() = created_by);

-- Logged-in users can update or delete events they created.
drop policy if exists "events updatable by owner" on public.events;
create policy "events updatable by owner"
    on public.events for update
    using (auth.uid() = created_by);

drop policy if exists "events deletable by owner" on public.events;
create policy "events deletable by owner"
    on public.events for delete
    using (auth.uid() = created_by);

-- Same for photos.
drop policy if exists "photos insertable by owner" on public.photos;
create policy "photos insertable by owner"
    on public.photos for insert
    with check (auth.uid() = reviewer_id);

drop policy if exists "photos deletable by owner" on public.photos;
create policy "photos deletable by owner"
    on public.photos for delete
    using (auth.uid() = reviewer_id);


-- ---------------------------------------------------------------------------
-- Handy example queries (reference — don't run as part of setup)
-- ---------------------------------------------------------------------------
-- Events within 5 km of a point, currently happening, most-upvoted first:
--
--   select id, name, ST_Distance(location, ST_MakePoint(-73.9857, 40.7484)::geography) as distance_m
--   from public.events
--   where city = 'nyc'
--     and now() between start_at and end_at
--     and ST_DWithin(location, ST_MakePoint(-73.9857, 40.7484)::geography, 5000)
--   order by upvotes desc, distance_m asc;
