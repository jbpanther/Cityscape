#!/usr/bin/env python3
"""
Cityscape ingestion pipeline — command-line entry point.

Examples:

    # See what would be ingested, without touching the database or needing
    # Supabase credentials. Start here.
    python run.py --city nyc --limit 20 --dry-run

    # Ingest the next 30 days of NYC events for real.
    python run.py --city nyc --days 30

    # Every configured city.
    python run.py --all-cities --days 14
"""

import argparse
import json
import logging
import sys

import config
from sources import ticketmaster

# Sources are registered here. Adding a second one (NYC Open Data, say) means
# writing a module with the same collect() shape and adding a line below —
# run.py itself shouldn't need to change.
SOURCES = {
    "ticketmaster": ticketmaster,
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Pull events from external sources into Supabase.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--city", choices=sorted(config.CITIES),
                        help="Which city to ingest.")
    parser.add_argument("--all-cities", action="store_true",
                        help="Ingest every city defined in config.CITIES.")
    parser.add_argument("--source", choices=sorted(SOURCES), default="ticketmaster",
                        help="Which source adapter to run (default: ticketmaster).")
    parser.add_argument("--days", type=int, default=30,
                        help="How many days ahead to search (default: 30).")
    parser.add_argument("--window-days", type=int, default=7,
                        help="Date-window size; lower it if you hit the 1000-item "
                             "paging cap (default: 7).")
    parser.add_argument("--limit", type=int,
                        help="Stop after this many events. Useful for smoke tests.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch and normalize, print a sample, write nothing. "
                             "Needs no Supabase credentials.")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show debug logging.")

    args = parser.parse_args()
    if not args.city and not args.all_cities:
        parser.error("specify --city CITY or --all-cities")
    return args


def run_city(source_module, city_key: str, args) -> list:
    """Fetch and normalize one city's events. Returns the rows."""
    city_config = config.CITIES[city_key]
    print(f"\n=== {city_config['label']} ({city_key}) via {args.source}")

    rows, stats = source_module.collect(
        api_key=config.ticketmaster_api_key(),
        city_key=city_key,
        city_config=city_config,
        days_ahead=args.days,
        window_days=args.window_days,
        limit=args.limit,
    )

    print(f"    fetched {stats['fetched']}  "
          f"skipped {stats['skipped']} (no coords, no start time, "
          f"already over, or >1yr out)  "
          f"duplicates {stats['duplicates']}  "
          f"usable {stats['usable']}")
    return rows


def main():
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    # Ticketmaster authenticates via an `apikey=` QUERY PARAMETER, and httpx
    # logs every request's full URL at INFO level — which means the key would be
    # printed to the console and into any log file we ever redirect this to.
    #
    # Pin httpx to WARNING so request lines never appear. Do NOT lower this to
    # see requests while debugging; use a proxy or print the params dict with
    # the key removed instead.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    source_module = SOURCES[args.source]
    city_keys = sorted(config.CITIES) if args.all_cities else [args.city]

    all_rows = []
    for city_key in city_keys:
        all_rows.extend(run_city(source_module, city_key, args))

    if not all_rows:
        print("\nNothing usable to write.")
        return 0

    if args.dry_run:
        print(f"\n--- DRY RUN: {len(all_rows)} rows would be written. Sample:\n")
        for row in all_rows[:3]:
            print(json.dumps(row, indent=2))
        print("\nRe-run without --dry-run to write these to Supabase.")
        return 0

    # Imported here rather than at the top so that --dry-run works without
    # Supabase credentials configured.
    import db

    client = db.get_client()
    written = db.upsert_events(client, all_rows)
    print(f"\nWrote {written} rows to Supabase.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
