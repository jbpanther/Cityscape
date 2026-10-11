"""
Repairing Ticketmaster venues whose coordinates are placeholders.

Ticketmaster carries a second set of listings (partner/resale inventory) whose
venue records have the right name and street address but fake coordinates:
dozens of unrelated theatres all share one point. Measured Oct 2026 on a 30-day
NYC pull:

    28 venues at 40.7593,-73.9902  (Belasco, Lyceum, Birdland, Minskoff, ...)
    15 venues at 40.7652,-73.9853  (Studio 54, Gershwin, Neil Simon, ...)
     3 venues at 40.7316,-73.9891  (Public Theater, Daryl Roth, Webster Hall)

That was ~21% of upcoming rows pinned to the wrong place. The points are not
hardcoded here, because Boston and London will have their own. Instead, a point
is a placeholder when venues with DIFFERENT street addresses share it exactly.
Venues that really do share a building (New World Stages' five stages, all at
340 W 50th St) have one address and are left alone.

Each affected venue is then located, in order of preference:

  1. By street address, via OpenStreetMap's free geocoder (Nominatim). The
     address is the one field these records reliably get right. Checked against
     Ticketmaster's own venue search on 57 venues: agreed within ~50 m nearly
     everywhere, and was right where Ticketmaster was wrong (City Center and
     Studio 54 share one bogus point in Ticketmaster's main feed too).
  2. By name, via Ticketmaster's venue search, for addresses Nominatim can't
     place (e.g. "10 Lincoln Center Plaza").
  3. Not at all: the row keeps its original point. Placeholders sit in the
     right neighbourhood, so a slightly-off pin beats dropping the event.

Any answer more than MAX_DISTANCE_KM from the original point is rejected:
"891 Seventh Avenue" geocodes to upstate New York, "63rd Street" to Queens.

Results are cached in `venue_locations.json`, so each venue costs one lookup,
ever. Edit that file to correct a venue by hand; entries are keyed by
Ticketmaster venue ID.
"""

import difflib
import json
import logging
import math
import re
import time
from collections import defaultdict
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

CACHE_PATH = Path(__file__).resolve().parent.parent / "venue_locations.json"

# Nominatim's usage policy: at most 1 request/second, an identifying
# User-Agent, and cache results. The cache means a normal run makes zero calls.
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_HEADERS = {"User-Agent": "CityscapeEventPipeline/0.1 (personal hobby project)"}
NOMINATIM_SECONDS_BETWEEN_REQUESTS = 1.1

TM_VENUE_SEARCH_URL = "https://app.ticketmaster.com/discovery/v2/venues.json"
TM_SECONDS_BETWEEN_REQUESTS = 0.25

# Placeholders observed so far are within ~2 km of the venues they stand in for.
MAX_DISTANCE_KM = 5.0

# How closely a Ticketmaster search result's name must match ours. Containment
# ("Jacobs Theatre" in "Bernard B. Jacobs Theatre") counts as a match on its own.
MIN_NAME_SIMILARITY = 0.8


def venue_of(raw: dict) -> dict:
    venues = ((raw.get("_embedded") or {}).get("venues")) or []
    return venues[0] if venues else {}


def _coords(venue: dict):
    location = venue.get("location") or {}
    try:
        return float(location["latitude"]), float(location["longitude"])
    except (KeyError, TypeError, ValueError):
        return None


def _km_between(a, b) -> float:
    """Good enough at city scale; no need for full haversine."""
    dlat = (a[0] - b[0]) * 111.0
    dlng = (a[1] - b[1]) * 111.0 * math.cos(math.radians(a[0]))
    return math.hypot(dlat, dlng)


def _address_key(venue: dict) -> str:
    """'111 W. 44th St.' and '111 West 44th Street' should compare equal."""
    line1 = ((venue.get("address") or {}).get("line1") or "").lower()
    line1 = re.sub(r"\bwest\b", "w", line1)
    line1 = re.sub(r"\beast\b", "e", line1)
    line1 = re.sub(r"\bstreet\b", "st", line1)
    return re.sub(r"[^a-z0-9]", "", line1)


def _name_key(name: str) -> str:
    """'Belasco Theatre - NY' -> 'belasco theatre'."""
    name = (name or "").lower()
    name = re.sub(r"\s*-\s*ny\s*$", "", name)
    name = re.sub(r"[^a-z0-9 ]", " ", name)
    return " ".join(name.split())


def find_placeholder_coords(raws) -> set:
    """Coordinates shared by venues at two or more different street addresses."""
    addresses_at = defaultdict(set)
    for raw in raws:
        venue = venue_of(raw)
        coords = _coords(venue)
        if coords is not None:
            addresses_at[coords].add(_address_key(venue))
    return {coords for coords, addresses in addresses_at.items() if len(addresses) > 1}


class VenueResolver:
    """
    Finds real coordinates for a venue, with a JSON cache.

    Only successful lookups are cached. A miss is retried on the next run, in
    case the data has improved; there are only a handful, so it costs little.
    """

    def __init__(self, api_key: str, cache_path: Path = CACHE_PATH):
        self.api_key = api_key
        self.cache_path = cache_path
        self.cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
        self._dirty = False
        # Misses are not cached on disk, but within one run each venue is only
        # tried once, not once per performance.
        self._missed = set()

    def resolve(self, venue: dict, placeholders: set):
        """Return (lat, lng) for this venue, or None if nothing trustworthy."""
        venue_id = venue.get("id")
        if venue_id in self.cache:
            hit = self.cache[venue_id]
            return hit["latitude"], hit["longitude"]
        if venue_id in self._missed:
            return None

        original = _coords(venue)
        for method, lookup in (("address", self._by_address), ("name", self._by_name)):
            coords = lookup(venue, placeholders)
            if coords is None:
                continue
            if _km_between(coords, original) > MAX_DISTANCE_KM:
                log.info("Rejected %s lookup for %s: %.1f km from Ticketmaster's point",
                         method, venue.get("name"), _km_between(coords, original))
                continue
            self.cache[venue_id] = {
                "name": venue.get("name"),
                "address": (venue.get("address") or {}).get("line1"),
                "found_by": method,
                "latitude": coords[0],
                "longitude": coords[1],
            }
            self._dirty = True
            return coords

        log.info("No location found for venue %s (%s); leaving it where it is",
                 venue.get("name"), venue_id)
        self._missed.add(venue_id)
        return None

    def _by_address(self, venue: dict, placeholders: set):
        street = ((venue.get("address") or {}).get("line1") or "").strip()
        if not street:
            return None
        params = {
            "street": street,
            "city": (venue.get("city") or {}).get("name", ""),
            "state": (venue.get("state") or {}).get("stateCode", ""),
            "country": (venue.get("country") or {}).get("countryCode", ""),
            "format": "jsonv2",
            "limit": 1,
        }
        time.sleep(NOMINATIM_SECONDS_BETWEEN_REQUESTS)
        response = httpx.get(NOMINATIM_URL, params=params,
                             headers=NOMINATIM_HEADERS, timeout=30.0)
        response.raise_for_status()
        results = response.json()
        if not results:
            return None
        return float(results[0]["lat"]), float(results[0]["lon"])

    def _by_name(self, venue: dict, placeholders: set):
        wanted = _name_key(venue.get("name"))
        if not wanted:
            return None
        params = {"apikey": self.api_key, "keyword": wanted, "size": 20}
        state = (venue.get("state") or {}).get("stateCode")
        country = (venue.get("country") or {}).get("countryCode")
        if state:
            params["stateCode"] = state
        if country:
            params["countryCode"] = country

        time.sleep(TM_SECONDS_BETWEEN_REQUESTS)
        response = httpx.get(TM_VENUE_SEARCH_URL, params=params, timeout=30.0)
        response.raise_for_status()
        candidates = ((response.json().get("_embedded") or {}).get("venues")) or []

        best, best_score = None, 0.0
        for candidate in candidates:
            coords = _coords(candidate)
            # A result sitting on a placeholder point is no better than what we had.
            if coords is None or coords in placeholders:
                continue
            name = _name_key(candidate.get("name"))
            if wanted in name or name in wanted:
                score = 1.0
            else:
                score = difflib.SequenceMatcher(None, wanted, name).ratio()
            if score > best_score:
                best, best_score = coords, score

        return best if best_score >= MIN_NAME_SIMILARITY else None

    def save(self):
        if self._dirty:
            self.cache_path.write_text(json.dumps(self.cache, indent=2, sort_keys=True) + "\n")
            self._dirty = False


def relocate(pairs, resolver):
    """
    Move rows sitting on a placeholder point to their venue's real location.

    `pairs` is a list of (raw, row); rows are updated in place. Returns the set
    of external_ids that were moved and the number left where they were.
    """
    placeholders = find_placeholder_coords(raw for raw, _ in pairs)
    relocated_ids, unresolved = set(), 0

    for raw, row in pairs:
        venue = venue_of(raw)
        if _coords(venue) not in placeholders:
            continue
        coords = resolver.resolve(venue, placeholders)
        if coords is None:
            unresolved += 1
            continue
        row["latitude"], row["longitude"] = coords
        relocated_ids.add(row["external_id"])

    resolver.save()
    return relocated_ids, unresolved
