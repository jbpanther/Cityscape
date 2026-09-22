"""
Ticketmaster Discovery API → Cityscape `events` rows.

This is the first source adapter, and it sets the shape every later one follows:

    fetch_events(...)  -> yields raw provider dicts
    normalize(...)     -> turns one raw dict into an `events` row (or None)
    collect(...)       -> convenience wrapper that does both

Two API constraints drive the design (verified against the Discovery API docs):

  1. Rate limit: 5,000 calls/day, 5 requests/second. We sleep between calls.
  2. Deep paging cap: `size * page` must stay under 1000, so a single query can
     never return more than 1,000 events no matter how many pages we ask for.
     To get more, you slice the *date range* into windows and query each one —
     which is exactly what `fetch_events` does.
"""

import logging
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

log = logging.getLogger(__name__)

API_BASE = "https://app.ticketmaster.com/discovery/v2"

# Identifies this pipeline in `events.source_name`. Changing it would orphan
# every row already ingested, so treat it as permanent.
SOURCE_NAME = "ticketmaster"

# Page size. Deep paging allows size*page < 1000, so 100 gives us pages 0-9.
PAGE_SIZE = 100
MAX_ITEMS_PER_QUERY = 1000

# 5 req/sec is the documented ceiling; 4/sec leaves headroom for clock jitter.
SECONDS_BETWEEN_REQUESTS = 0.25

# Ticketmaster almost never reports an end time. These are our assumptions.
DEFAULT_DURATION = timedelta(hours=3)        # a normal ticketed event
ALL_DAY_DURATION = timedelta(hours=24)       # when only a date is known


# ---------------------------------------------------------------------------
# Category mapping
# ---------------------------------------------------------------------------
#
# Ticketmaster classifies events as segment → genre → subGenre. We map onto the
# EventType cases the iOS app already knows (see Event.swift). The *values* here
# must match EventType's raw values exactly, or the app's decoder will reject
# the row.

_SEGMENT_TO_EVENT_TYPE = {
    "Music": "Concert",
    "Sports": "Sports",
    "Arts & Theatre": "Theatre",
    "Film": "Other",
    "Miscellaneous": "Other",
}

# Genre overrides, applied when the segment alone is too coarse. Checked as
# case-insensitive substrings so "Comedy" matches "Comedy/Variety" etc.
_GENRE_OVERRIDES = [
    ("comedy", "Comedy"),
    ("food", "Food"),
    ("cultural", "Cultural"),
]


def _event_type(raw: dict) -> str:
    """Pick the best EventType raw value for a Ticketmaster event."""
    classifications = raw.get("classifications") or []
    if not classifications:
        return "Other"

    primary = classifications[0] or {}
    segment = ((primary.get("segment") or {}).get("name")) or ""
    genre = ((primary.get("genre") or {}).get("name")) or ""

    for needle, event_type in _GENRE_OVERRIDES:
        if needle in genre.lower():
            return event_type

    return _SEGMENT_TO_EVENT_TYPE.get(segment, "Other")


# ---------------------------------------------------------------------------
# Date handling
# ---------------------------------------------------------------------------

def _parse_start(raw: dict):
    """
    Work out when an event starts, in UTC.

    Returns (datetime_utc, time_is_known) or (None, False) if unresolvable.

    Ticketmaster gives us, in descending order of usefulness:
      - dates.start.dateTime : full UTC instant  ("2026-10-01T23:00:00Z")
      - localDate + localTime + dates.timezone   (needs assembling)
      - localDate alone                          (time genuinely TBA)
    """
    dates = raw.get("dates") or {}
    start = dates.get("start") or {}
    tz_name = dates.get("timezone")

    # Best case — an explicit UTC instant.
    iso = start.get("dateTime")
    if iso:
        # Python's fromisoformat didn't accept a trailing "Z" before 3.11.
        return datetime.fromisoformat(iso.replace("Z", "+00:00")), True

    local_date = start.get("localDate")
    if not local_date:
        return None, False

    local_time = start.get("localTime")
    time_known = bool(local_time)
    naive = datetime.fromisoformat(f"{local_date}T{local_time or '00:00:00'}")

    # Interpret in the venue's timezone when we know it; otherwise assume UTC
    # and accept a few hours of drift rather than dropping the event.
    if tz_name:
        try:
            return naive.replace(tzinfo=ZoneInfo(tz_name)).astimezone(timezone.utc), time_known
        except Exception:
            log.debug("Unknown timezone %r, falling back to UTC", tz_name)

    return naive.replace(tzinfo=timezone.utc), time_known


def _parse_end(raw: dict, start_utc: datetime, time_known: bool) -> datetime:
    """
    Work out when an event ends.

    `events.end_at` is NOT NULL, but Ticketmaster rarely supplies an end time —
    so we assume a duration. Three hours for a normal ticketed event; a full day
    when we only know the date, so it stays visible for that whole day.
    """
    dates = raw.get("dates") or {}
    iso = ((dates.get("end") or {}).get("dateTime"))
    if iso:
        end = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if end > start_utc:
            return end
        log.debug("Ignoring end time that is not after start")

    return start_utc + (DEFAULT_DURATION if time_known else ALL_DAY_DURATION)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def _description(raw: dict, venue: dict) -> str:
    """
    Build something worth reading in the app's detail view.

    Ticketmaster's `info` field is often absent, so fall back to a generated
    line like "Rock at Madison Square Garden" rather than showing an empty card.
    """
    info = (raw.get("info") or "").strip()
    if info:
        return info

    classifications = raw.get("classifications") or []
    genre = ""
    if classifications:
        genre = (((classifications[0] or {}).get("genre") or {}).get("name") or "").strip()

    venue_name = (venue.get("name") or "").strip()

    if genre and venue_name and genre.lower() not in ("undefined", "other"):
        return f"{genre} at {venue_name}"
    if venue_name:
        return f"Live at {venue_name}"
    return ""


def normalize(raw: dict, city_key: str):
    """
    Turn one Ticketmaster event into an `events` row.

    Returns a dict ready to upsert, or None if the event is unusable — which
    happens often enough to be normal, not an error: some listings carry no
    venue coordinates, and a map-first app has nothing to do with those.
    """
    external_id = raw.get("id")
    name = (raw.get("name") or "").strip()
    if not external_id or not name:
        return None

    venues = ((raw.get("_embedded") or {}).get("venues")) or []
    venue = venues[0] if venues else {}
    location = venue.get("location") or {}

    # No coordinates means we cannot put a pin on the map — skip it.
    try:
        latitude = float(location["latitude"])
        longitude = float(location["longitude"])
    except (KeyError, TypeError, ValueError):
        return None

    # Guard against the (0, 0) placeholder some providers emit for "unknown".
    if latitude == 0.0 and longitude == 0.0:
        return None

    start_utc, time_known = _parse_start(raw)
    if start_utc is None:
        return None
    end_utc = _parse_end(raw, start_utc, time_known)

    return {
        "name": name,
        "description": _description(raw, venue),
        "event_type": _event_type(raw),
        "latitude": latitude,
        "longitude": longitude,
        "city": city_key,
        "start_at": start_utc.isoformat(),
        "end_at": end_utc.isoformat(),
        "source": "scraped",
        "source_name": SOURCE_NAME,
        "external_id": str(external_id),
        # `created_by` is deliberately omitted — scraped events belong to no
        # user. Engagement counters are omitted too, so that re-running the
        # pipeline never resets votes on an event people have already rated.
    }


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def _date_windows(days_ahead: int, window_days: int):
    """
    Split the search range into windows, yielding (start, end) UTC pairs.

    This exists because of the 1,000-item deep-paging cap: one query can never
    see past its 1000th result. Narrower date windows mean fewer results each,
    so nothing gets silently truncated. Shrink `window_days` if a busy city
    starts hitting the cap.
    """
    now = datetime.now(timezone.utc)
    cursor = now
    final = now + timedelta(days=days_ahead)

    while cursor < final:
        window_end = min(cursor + timedelta(days=window_days), final)
        yield cursor, window_end
        cursor = window_end


def _iso_for_api(dt: datetime) -> str:
    """Ticketmaster wants UTC as YYYY-MM-DDTHH:MM:SSZ — no sub-seconds, no offset."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_events(api_key: str, city_key: str, city_config: dict,
                 days_ahead: int = 30, window_days: int = 7, limit: int = None):
    """
    Yield raw Ticketmaster event dicts for one city.

    `limit` caps the total number yielded — useful for a quick smoke test that
    doesn't burn through the daily quota.
    """
    params_base = dict(city_config["ticketmaster"])
    yielded = 0

    with httpx.Client(timeout=30.0) as client:
        for window_start, window_end in _date_windows(days_ahead, window_days):
            page = 0

            while page * PAGE_SIZE < MAX_ITEMS_PER_QUERY:
                params = {
                    **params_base,
                    "apikey": api_key,
                    "size": PAGE_SIZE,
                    "page": page,
                    "sort": "date,asc",
                    "startDateTime": _iso_for_api(window_start),
                    "endDateTime": _iso_for_api(window_end),
                }

                response = client.get(f"{API_BASE}/events.json", params=params)

                # 429 means we out-ran the rate limit. Back off and retry once
                # rather than losing the whole window.
                if response.status_code == 429:
                    log.warning("Rate limited, backing off for 5s")
                    time.sleep(5)
                    continue

                response.raise_for_status()
                payload = response.json()

                events = ((payload.get("_embedded") or {}).get("events")) or []
                if not events:
                    break  # no results in this window — move to the next

                for raw in events:
                    yield raw
                    yielded += 1
                    if limit is not None and yielded >= limit:
                        return

                # Stop when we've seen the last page Ticketmaster will give us.
                page_info = payload.get("page") or {}
                total_pages = page_info.get("totalPages", 0)
                if page + 1 >= total_pages:
                    if total_pages * PAGE_SIZE >= MAX_ITEMS_PER_QUERY:
                        log.warning(
                            "Window %s–%s hit the 1000-item paging cap; "
                            "some events were not retrieved. Lower --window-days.",
                            window_start.date(), window_end.date(),
                        )
                    break

                page += 1
                time.sleep(SECONDS_BETWEEN_REQUESTS)


def collect(api_key: str, city_key: str, city_config: dict,
            days_ahead: int = 30, window_days: int = 7, limit: int = None):
    """
    Fetch and normalize in one call.

    Returns (rows, stats). Rows are deduplicated by external_id, because a
    single upsert batch must not contain the same conflict key twice — Postgres
    rejects that with "ON CONFLICT DO UPDATE command cannot affect row a second
    time", which is a genuinely confusing error to meet for the first time.
    """
    rows_by_id = {}
    seen = 0
    skipped = 0

    for raw in fetch_events(api_key, city_key, city_config,
                            days_ahead=days_ahead, window_days=window_days, limit=limit):
        seen += 1
        row = normalize(raw, city_key)
        if row is None:
            skipped += 1
            continue
        rows_by_id[row["external_id"]] = row

    stats = {
        "fetched": seen,
        "skipped": skipped,
        "duplicates": seen - skipped - len(rows_by_id),
        "usable": len(rows_by_id),
    }
    return list(rows_by_id.values()), stats
