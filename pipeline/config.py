"""
Configuration for the Cityscape ingestion pipeline.

Everything secret comes from environment variables (loaded from `.env`).
Everything non-secret — like the city definitions — lives here in code so it is
version-controlled and reviewable.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load `.env` sitting next to this file. Explicit path rather than a search,
# so the pipeline behaves the same no matter which directory you run it from.
load_dotenv(Path(__file__).parent / ".env")


def _required(name: str) -> str:
    """
    Read an environment variable, failing loudly if it is missing.

    A clear error now beats a confusing 401 from an API three functions later.
    """
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}\n"
            f"Copy pipeline/.env.example to pipeline/.env and fill it in."
        )
    return value


# --- Secrets ---------------------------------------------------------------
# Read lazily via functions so that `import config` doesn't explode in contexts
# where only the city table is needed (e.g. running tests, or --dry-run).

def supabase_url() -> str:
    return _required("SUPABASE_URL")


def supabase_service_key() -> str:
    return _required("SUPABASE_SERVICE_KEY")


def ticketmaster_api_key() -> str:
    return _required("TICKETMASTER_API_KEY")


# --- Cities ----------------------------------------------------------------
#
# The `city` column in Postgres stores these short keys ('nyc', 'boston',
# 'london'), which is what the iOS app filters on. Each source needs its own
# way of asking for that city, so per-source query parameters live alongside.
#
# Multi-city from day one — adding a city means adding an entry here, not
# changing any pipeline code.

CITIES = {
    "nyc": {
        "label": "New York City",
        # Ticketmaster Discovery API query parameters for this city.
        "ticketmaster": {
            "city": "New York",
            "stateCode": "NY",
            "countryCode": "US",
        },
    },
    "boston": {
        "label": "Boston",
        "ticketmaster": {
            "city": "Boston",
            "stateCode": "MA",
            "countryCode": "US",
        },
    },
    "london": {
        "label": "London",
        "ticketmaster": {
            "city": "London",
            "countryCode": "GB",  # no stateCode outside the US
        },
    },
}
