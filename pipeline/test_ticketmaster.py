#!/usr/bin/env python3
"""
Tests for the Ticketmaster normalizer.

No API key and no network needed — these run against hand-written payloads
shaped like real Discovery API responses. Run them after changing anything in
sources/ticketmaster.py:

    python test_ticketmaster.py

Deliberately plain asserts rather than pytest, so there's no extra dependency
and no framework to remember six weeks from now.
"""

from datetime import datetime

from sources import ticketmaster as tm


def venue(lat="40.7505", lng="-73.9934", name="Madison Square Garden"):
    return {"name": name, "location": {"latitude": lat, "longitude": lng}}


def test_full_concert():
    """An event with an explicit UTC dateTime is the easy, common case."""
    raw = {
        "id": "G5vabc1", "name": "Vampire Weekend",
        "info": "Doors open at 7pm. All ages.",
        "dates": {"start": {"dateTime": "2026-10-16T00:00:00Z"},
                  "timezone": "America/New_York"},
        "classifications": [{"segment": {"name": "Music"}, "genre": {"name": "Rock"}}],
        "_embedded": {"venues": [venue()]},
    }
    row = tm.normalize(raw, "nyc")
    assert row["name"] == "Vampire Weekend"
    assert row["event_type"] == "Concert"
    assert row["city"] == "nyc"
    assert row["source"] == "scraped"
    assert row["source_name"] == "ticketmaster"
    assert row["external_id"] == "G5vabc1"
    assert row["latitude"] == 40.7505
    assert "created_by" not in row      # scraped events belong to no user
    assert "upvotes" not in row         # re-runs must never reset engagement

    # No end time supplied -> assume 3 hours.
    duration = datetime.fromisoformat(row["end_at"]) - datetime.fromisoformat(row["start_at"])
    assert duration.total_seconds() == 3 * 3600


def test_time_tba_becomes_all_day():
    """Date-only listings are common and must not be dropped."""
    raw = {
        "id": "G5vdef2", "name": "Knicks vs Celtics",
        "dates": {"start": {"localDate": "2026-11-02"}, "timezone": "America/New_York"},
        "classifications": [{"segment": {"name": "Sports"}, "genre": {"name": "Basketball"}}],
        "_embedded": {"venues": [venue()]},
    }
    row = tm.normalize(raw, "nyc")
    duration = datetime.fromisoformat(row["end_at"]) - datetime.fromisoformat(row["start_at"])
    assert duration.total_seconds() == 24 * 3600
    # Generated description, since Ticketmaster gave us no `info`.
    assert row["description"] == "Basketball at Madison Square Garden"


def test_daylight_saving_is_applied():
    """
    The same local midnight maps to different UTC instants across a DST
    boundary. Getting this wrong shifts events by an hour for half the year.
    """
    def start_for(local_date):
        raw = {"id": "x", "name": "Show",
               "dates": {"start": {"localDate": local_date}, "timezone": "America/New_York"},
               "_embedded": {"venues": [venue()]}}
        return tm.normalize(raw, "nyc")["start_at"]

    assert start_for("2026-07-02").startswith("2026-07-02T04:00")   # EDT, UTC-4
    assert start_for("2026-11-02").startswith("2026-11-02T05:00")   # EST, UTC-5


def test_london_timezone():
    """Multi-city from day one — a non-US timezone must work identically."""
    raw = {
        "id": "l1", "name": "Arsenal vs Spurs",
        "dates": {"start": {"localDate": "2026-07-02", "localTime": "15:00:00"},
                  "timezone": "Europe/London"},
        "classifications": [{"segment": {"name": "Sports"}, "genre": {"name": "Soccer"}}],
        "_embedded": {"venues": [venue("51.5549", "-0.1084", "Emirates Stadium")]},
    }
    row = tm.normalize(raw, "london")
    assert row["city"] == "london"
    assert row["start_at"].startswith("2026-07-02T14:00")           # BST, UTC+1


def test_comedy_genre_overrides_segment():
    """Arts & Theatre normally maps to Theatre; the Comedy genre should win."""
    raw = {
        "id": "c1", "name": "John Mulaney",
        "dates": {"start": {"dateTime": "2026-10-20T23:00:00Z"}},
        "classifications": [{"segment": {"name": "Arts & Theatre"},
                             "genre": {"name": "Comedy"}}],
        "_embedded": {"venues": [venue(name="Beacon Theatre")]},
    }
    assert tm.normalize(raw, "nyc")["event_type"] == "Comedy"


def test_unusable_events_are_skipped_not_crashed():
    """Missing data is normal in this feed — skipping is the correct behavior."""
    base_date = {"start": {"dateTime": "2026-10-20T23:00:00Z"}}

    no_venue = {"id": "x1", "name": "Mystery", "dates": base_date, "_embedded": {"venues": []}}
    no_coords = {"id": "x2", "name": "Mystery", "dates": base_date,
                 "_embedded": {"venues": [{"name": "TBA"}]}}
    zero_coords = {"id": "x3", "name": "Placeholder", "dates": base_date,
                   "_embedded": {"venues": [venue("0", "0")]}}
    no_date = {"id": "x4", "name": "Undated", "_embedded": {"venues": [venue()]}}
    no_name = {"id": "x5", "name": "", "dates": base_date, "_embedded": {"venues": [venue()]}}

    for raw in (no_venue, no_coords, zero_coords, no_date, no_name):
        assert tm.normalize(raw, "nyc") is None


def test_unknown_timezone_degrades_to_utc():
    """A timezone we can't resolve shouldn't lose the event entirely."""
    raw = {"id": "tz1", "name": "Show",
           "dates": {"start": {"localDate": "2026-07-02"}, "timezone": "Mars/Olympus"},
           "_embedded": {"venues": [venue()]}}
    row = tm.normalize(raw, "nyc")
    assert row is not None
    assert row["start_at"].startswith("2026-07-02T00:00")


def test_date_windows_respect_paging_cap():
    """
    Windows exist so no single query runs into the 1000-item deep-paging cap.
    """
    windows = list(tm._date_windows(days_ahead=30, window_days=7))
    assert len(windows) == 5
    assert all((end - start).days <= 7 for start, end in windows)
    # Windows must be contiguous, or events fall through the gaps.
    for (_, end), (next_start, _) in zip(windows, windows[1:]):
        assert end == next_start


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"  PASS  {test.__name__}")
    print(f"\n{len(tests)} tests passed.")
