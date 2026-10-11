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

from datetime import datetime, timedelta, timezone

from sources import ticketmaster as tm
from sources import ticketmaster_venues as tv


# A pinned clock. normalize() now drops events that are already over and caps
# how far ahead it will believe a date, which made the old hardcoded 2026 dates
# rot the moment real time passed them. Every test passes this explicitly so the
# suite gives the same answer forever, not just in the month it was written.
NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)


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
    row = tm.normalize(raw, "nyc", now=NOW)
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
    row = tm.normalize(raw, "nyc", now=NOW)
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
        return tm.normalize(raw, "nyc", now=NOW)["start_at"]

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
    row = tm.normalize(raw, "london", now=NOW)
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
    assert tm.normalize(raw, "nyc", now=NOW)["event_type"] == "Comedy"


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
        assert tm.normalize(raw, "nyc", now=NOW) is None


def test_unknown_timezone_degrades_to_utc():
    """A timezone we can't resolve shouldn't lose the event entirely."""
    raw = {"id": "tz1", "name": "Show",
           "dates": {"start": {"localDate": "2026-07-02"}, "timezone": "Mars/Olympus"},
           "_embedded": {"venues": [venue()]}}
    row = tm.normalize(raw, "nyc", now=NOW)
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


def test_finished_events_are_dropped():
    """An event whose end time has passed is stale — it must not be ingested."""
    raw = {"id": "OLD1", "name": "Last Month's Show",
           "dates": {"start": {"dateTime": "2026-04-10T23:00:00Z"},
                     "end": {"dateTime": "2026-04-11T02:00:00Z"}},
           "_embedded": {"venues": [venue()]}}
    assert tm.normalize(raw, "nyc", now=NOW) is None


def test_already_started_event_is_dropped():
    """
    Anything already underway is skipped, which is what removes Ticketmaster's
    season passes and flex admissions (they advertise a start months in the past
    and an end months ahead).

    This does NOT lose multi-day events: see the companion test below.
    """
    raw = {"id": "FEST1", "name": "Oktoberfest, mid-run",
           "dates": {"start": {"dateTime": "2026-05-25T15:00:00Z"},
                     "end": {"dateTime": "2026-06-08T23:00:00Z"}},
           "_embedded": {"venues": [venue()]}}
    assert tm.normalize(raw, "nyc", now=NOW) is None


def test_multi_day_event_is_kept_when_still_upcoming():
    """
    The reason the rule above is safe. We catch a multi-day event while its start
    is still in the future; because upserts never delete, that row then stays in
    the table for the event's whole run.
    """
    raw = {"id": "FEST2", "name": "Oktoberfest, not started yet",
           "dates": {"start": {"dateTime": "2026-06-20T15:00:00Z"},
                     "end": {"dateTime": "2026-07-04T23:00:00Z"}},
           "_embedded": {"venues": [venue()]}}
    row = tm.normalize(raw, "nyc", now=NOW)
    assert row is not None, "an upcoming multi-day event must survive"
    assert row["start_at"].startswith("2026-06-20")
    assert row["end_at"].startswith("2026-07-04")     # full span preserved


def test_long_running_event_is_kept_not_dropped():
    """
    A year-long celebration (America 250) is legitimate. There is deliberately
    no maximum duration — only a cap on how far the end date may run.
    """
    raw = {"id": "A250", "name": "America 250 Celebration",
           "dates": {"start": {"dateTime": "2026-07-04T16:00:00Z"},
                     "end": {"dateTime": "2027-01-04T16:00:00Z"}},
           "_embedded": {"venues": [venue()]}}
    row = tm.normalize(raw, "nyc", now=NOW)
    assert row is not None
    assert row["end_at"].startswith("2027-01-04")     # under the cap, untouched


def test_end_date_beyond_horizon_is_clamped():
    """A standing season pass keeps its pin but cannot outlive the 1-year cap."""
    raw = {"id": "PASS1", "name": "Museum Flex Admission",
           "dates": {"start": {"dateTime": "2026-07-01T15:00:00Z"},
                     "end": {"dateTime": "2031-12-31T23:00:00Z"}},
           "_embedded": {"venues": [venue()]}}
    row = tm.normalize(raw, "nyc", now=NOW)
    assert row is not None
    horizon = NOW + tm.MAX_FUTURE
    assert row["end_at"] == horizon.isoformat()
    assert row["end_at"] < "2031"                     # the runaway date is gone


def test_start_beyond_horizon_is_dropped():
    """A date more than a year out is a placeholder, not something to pin now."""
    raw = {"id": "FAR1", "name": "Someday Festival",
           "dates": {"start": {"dateTime": "2028-07-01T15:00:00Z"}},
           "_embedded": {"venues": [venue()]}}
    assert tm.normalize(raw, "nyc", now=NOW) is None


def test_skip_rule_is_the_start_date_only():
    """
    The skip decision depends on the START date alone — the assumed 3h duration
    must not quietly influence it. An event starting an hour from now is kept
    even though we are inventing its end time.
    """
    def row_for(offset):
        start = NOW + offset
        raw = {"id": f"BOUND{offset}", "name": "Boundary Show",
               "dates": {"start": {"dateTime": start.strftime("%Y-%m-%dT%H:%M:%SZ")}},
               "_embedded": {"venues": [venue()]}}
        return tm.normalize(raw, "nyc", now=NOW)

    assert row_for(timedelta(hours=-1)) is None      # started: skipped
    kept = row_for(timedelta(hours=1))               # upcoming: kept
    assert kept is not None
    # And the invented end time is still start + 3h, untouched by the skip logic.
    assert kept["end_at"] == (NOW + timedelta(hours=4)).isoformat()


def test_cancelled_and_postponed_are_dropped_offsale_kept():
    """Cancelled shows must not reach the map; off-sale (sold out) ones still happen."""
    def with_status(code):
        return {"id": f"S-{code}", "name": "Status Test",
                "dates": {"start": {"dateTime": "2026-07-01T23:00:00Z"},
                          "status": {"code": code}},
                "_embedded": {"venues": [venue()]}}
    assert tm.normalize(with_status("cancelled"), "nyc", now=NOW) is None
    assert tm.normalize(with_status("postponed"), "nyc", now=NOW) is None
    assert tm.normalize(with_status("offsale"), "nyc", now=NOW) is not None
    assert tm.normalize(with_status("rescheduled"), "nyc", now=NOW) is not None
    assert tm.normalize(with_status("onsale"), "nyc", now=NOW)["showtimes"] is None


# --- merging repeated showings ----------------------------------------------

BANKSY = ("40.7196025", "-74.00135811")
BELASCO = ("40.75662668", "-73.98396120")


def showing(id_, local_date, local_time, name="The Banksy Museum New York!",
            at=BANKSY):
    """One performance or timed-entry slot, shaped like the real listings."""
    return {"id": id_, "name": name,
            "dates": {"start": {"localDate": local_date, "localTime": local_time},
                      "timezone": "America/New_York"},
            "_embedded": {"venues": [venue(lat=at[0], lng=at[1])]}}


def rows_for(raws):
    return [tm.normalize(raw, "nyc", now=NOW) for raw in raws]


def test_timed_entry_slots_merge_into_one_row():
    """Real bug: The Banksy Museum came through as one row per 30-minute slot."""
    times = ["14:00:00", "14:30:00", "15:00:00", "15:30:00"]
    raws = [showing(f"LvZ{i}", "2026-07-04", t) for i, t in enumerate(times)]
    rows = tm.merge_showings(rows_for(raws))

    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "The Banksy Museum New York!"
    # Spans first start to last end (15:30 EDT = 19:30Z, + 3h assumed = 22:30Z).
    assert row["start_at"] == "2026-07-04T18:00:00+00:00"
    assert row["end_at"] == "2026-07-04T22:30:00+00:00"
    # Every slot kept, in order, with its own upstream ID.
    assert [s["external_id"] for s in row["showtimes"]] == ["LvZ0", "LvZ1", "LvZ2", "LvZ3"]
    assert row["showtimes"][0]["start_at"] == row["start_at"]


def test_a_broadway_run_becomes_one_row():
    """Real bug: Hamilton was 10 stacked pins in one week, one per performance."""
    raws = [showing("MAT", "2026-07-04", "14:00:00", name="Hamilton", at=BELASCO),
            showing("EVE", "2026-07-04", "19:30:00", name="Hamilton", at=BELASCO),
            showing("SUN", "2026-07-05", "15:00:00", name="Hamilton", at=BELASCO)]
    rows = tm.merge_showings(rows_for(raws))
    assert len(rows) == 1
    assert [s["external_id"] for s in rows[0]["showtimes"]] == ["MAT", "EVE", "SUN"]
    assert rows[0]["start_at"] == "2026-07-04T18:00:00+00:00"
    assert rows[0]["end_at"] == "2026-07-05T22:00:00+00:00"


def test_single_showing_keeps_its_own_id():
    rows = tm.merge_showings(rows_for([showing("ONE", "2026-07-04", "20:00:00")]))
    assert rows[0]["external_id"] == "ONE"
    assert rows[0]["showtimes"] is None


def test_merged_id_is_stable_as_performances_pass():
    """
    Each run only sees performances that have not started yet. The merged row
    must keep the same external_id anyway, or every run would insert a new row.
    """
    run = [showing(f"A{d}", f"2026-07-{d:02d}", "20:00:00") for d in range(4, 10)]
    id_today = tm.merge_showings(rows_for(run))[0]["external_id"]
    id_later = tm.merge_showings(rows_for(run[3:]))[0]["external_id"]
    assert id_today == id_later
    assert id_today.startswith("multi:")


def test_same_show_at_distant_venues_stays_separate():
    uptown = ("40.8099", "-73.9493")   # ~6 km from the Belasco
    raws = ([showing(f"B{i}", "2026-07-04", f"1{i}:00:00", name="Comedy Night", at=BELASCO)
             for i in range(2)]
            + [showing(f"U{i}", "2026-07-04", f"1{i}:00:00", name="Comedy Night", at=uptown)
               for i in range(2)])
    rows = tm.merge_showings(rows_for(raws))
    assert len(rows) == 2
    assert len({r["external_id"] for r in rows}) == 2


def test_partner_feed_duplicate_collapses_and_keeps_main_feed_content():
    """
    Real data: 'Hamilton (NY)' (main feed) and 'Hamilton' (partner feed, moved
    off a placeholder by address lookup, ~20 m away) are the same performance.
    """
    main = showing("Z1MAIN", "2026-07-04", "19:00:00", name="Hamilton (NY)", at=BELASCO)
    main["info"] = "The main feed's description."
    partner = showing("Z7PART", "2026-07-04", "19:00:00", name="Hamilton",
                      at=("40.75664", "-73.98380"))
    rows = tm.merge_showings(rows_for([partner, main]), relocated_ids={"Z7PART"})
    assert len(rows) == 1
    row = rows[0]
    assert row["external_id"] == "Z1MAIN"
    assert row["name"] == "Hamilton"
    assert row["description"] == "The main feed's description."
    # The address-derived location wins.
    assert (row["latitude"], row["longitude"]) == (40.75664, -73.98380)


def week_of(name, prefix, at=BELASCO, days=range(4, 10)):
    return [showing(f"{prefix}{d}", f"2026-07-{d:02d}", "20:00:00", name=name, at=at)
            for d in days]


def test_subtitled_twin_listings_merge():
    """Real data: 'Six' and 'Six: The Musical' were two pins on one theatre."""
    for a, b in [("Six", "Six: The Musical"),
                 ("Chicago", "Chicago - The Musical"),
                 ("Two Strangers", "Two Strangers (Carry a Cake Across New York)"),
                 ("School Girls:Or, The African Mean Girls",
                  "School Girls; Or, the African Mean Girls Play")]:
        rows = tm.merge_showings(rows_for(week_of(a, "A") + week_of(b, "B")))
        assert len(rows) == 1, (a, b)
        assert len(rows[0]["showtimes"]) == 6


def test_merged_twins_take_the_shorter_title():
    rows = tm.merge_showings(rows_for(week_of("Six: The Musical", "A") + week_of("Six", "B")))
    assert rows[0]["name"] == "Six"


def test_same_core_title_on_different_nights_stays_separate():
    """NYC Ballet runs several programs at one venue, all 'New York City Ballet: ...'."""
    raws = (week_of("New York City Ballet: All Balanchine I", "A", days=range(4, 7))
            + week_of("New York City Ballet: Eclectic NYCB I", "B", days=range(7, 10)))
    assert len(tm.merge_showings(rows_for(raws))) == 2


def test_neighbouring_theatres_at_the_same_times_stay_separate():
    """Aladdin and The Lion King: 250 m apart, identical curtain times."""
    lion_king = ("40.75799", "-73.98577")
    raws = week_of("Aladdin", "A") + week_of("The Lion King", "L", at=lion_king)
    assert len(tm.merge_showings(rows_for(raws))) == 2


def test_city_suffix_is_dropped_from_names():
    for title in ["Hamilton (NY)", "Hamilton (New York, NY)", "Hamilton (nyc)"]:
        assert tm.normalize(showing("X", "2026-07-04", "19:00:00", name=title),
                            "nyc", now=NOW)["name"] == "Hamilton"


# --- placeholder venue coordinates ------------------------------------------

def at_venue(id_, lat, lng, address):
    return {"_embedded": {"venues": [{"id": id_, "location": {"latitude": lat, "longitude": lng},
                                      "address": {"line1": address}}]}}


def test_shared_point_with_different_addresses_is_a_placeholder():
    raws = [at_venue("A", "40.7593", "-73.990196", "111 W. 44th St."),
            at_venue("B", "40.7593", "-73.990196", "149 W. 45th St.")]
    assert tv.find_placeholder_coords(raws) == {(40.7593, -73.990196)}


def test_one_building_with_many_stages_is_not_a_placeholder():
    """New World Stages: five stage records, one real address."""
    raws = [at_venue("S1", "40.763", "-73.9876", "340 West 50th Street"),
            at_venue("S2", "40.763", "-73.9876", "340 W 50th St")]
    assert tv.find_placeholder_coords(raws) == set()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"  PASS  {test.__name__}")
    print(f"\n{len(tests)} tests passed.")
