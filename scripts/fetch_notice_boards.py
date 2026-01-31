#!/usr/bin/env python3
"""Fetch official notice board data from Czech APIs and save to JSON.

This script fetches data from:
1. Česko.Digital API - comprehensive municipality data (~6,300 entries)
2. NKOD GraphQL API - OFN úřední desky datasets with official URLs

Usage:
    # Fetch all data (Česko.Digital + NKOD OFN)
    uv run python scripts/fetch_notice_boards.py -o data/notice_boards.json

    # Quick fetch (skip OFN, faster)
    uv run python scripts/fetch_notice_boards.py --skip-ofn -o data/notice_boards.json
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# API endpoints
CESKO_DIGITAL_URL = "https://data.cesko.digital/obce/1/obce.json"
NKOD_GRAPHQL_URL = "https://data.gov.cz/graphql"

NKOD_QUERY = """
query {
  datasets(limit: 2000, filters: {
    conformsTo: "https://ofn.gov.cz/úřední-desky/2021-07-20/"
  }) {
    data {
      iri
      title { cs }
      publisher { title { cs } }
      distribution {
        accessURL
        format
      }
    }
  }
}
"""


# Pydantic models for JSON handling
class Address(BaseModel):
    """Address of a municipality office."""

    street_name: str | None = None
    city: str | None = None
    district: str | None = None
    postal_code: str | None = None
    region: str | None = None
    address_point_id: str | None = None


class NoticeBoardData(BaseModel):
    """Notice board data for JSON serialization."""

    name: str = Field(..., description="Name of the municipality")
    abbreviation: str | None = None
    ico: str | None = None
    url: str | None = None
    ofn_json_url: str | None = None
    edesky_url: str | None = None
    municipality_code: str | None = None
    nutslau: str | None = None
    coordinates: tuple[float, float] | None = None
    address: Address | None = None
    data_box_id: str | None = None
    email: list[str] | None = None
    legal_form_code: int | None = None
    legal_form_label: str | None = None
    coat_of_arms_url: str | None = None
    type_: str = "obec"

    model_config = {"extra": "ignore"}


# Fetchers
async def fetch_cesko_digital(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    """Fetch municipality data from Česko.Digital."""
    logger.info("Fetching Česko.Digital obce.json...")
    response = await client.get(CESKO_DIGITAL_URL)
    response.raise_for_status()
    data: dict[str, Any] = response.json()
    municipalities: list[dict[str, Any]] = data.get("municipalities", [])
    if not municipalities and isinstance(data, list):
        municipalities = data
    logger.info(f"Fetched {len(municipalities)} municipalities from Česko.Digital")
    return municipalities


async def fetch_nkod_notice_boards(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    """Fetch official notice board datasets from NKOD GraphQL API."""
    logger.info("Fetching NKOD datasets via GraphQL...")
    response = await client.post(
        NKOD_GRAPHQL_URL,
        json={"query": NKOD_QUERY},
        headers={"Content-Type": "application/json"},
    )
    response.raise_for_status()
    result: dict[str, Any] = response.json()
    datasets: list[dict[str, Any]] = result.get("data", {}).get("datasets", {}).get("data", [])
    logger.info(f"Fetched {len(datasets)} OFN datasets from NKOD")
    return datasets


def extract_json_distribution_url(dataset: dict[str, Any]) -> str | None:
    """Extract JSON distribution URL from a NKOD dataset."""
    distributions: list[dict[str, Any]] = dataset.get("distribution", [])
    for dist in distributions:
        access_url: str | None = dist.get("accessURL")
        fmt: str = dist.get("format") or ""
        if access_url and ("json" in fmt.lower() or access_url.endswith(".json")):
            return access_url
    if distributions:
        first_url: str | None = distributions[0].get("accessURL")
        return first_url
    return None


async def fetch_ofn_board_data(client: httpx.AsyncClient, url: str) -> dict[str, Any] | None:
    """Fetch and parse OFN úřední deska JSON data."""
    try:
        response = await client.get(url, timeout=30.0)
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return data
    except (httpx.HTTPError, ValueError) as e:
        logger.warning(f"Failed to fetch OFN data from {url}: {e}")
        return None


def extract_official_url_from_ofn(ofn_data: dict[str, Any]) -> str | None:
    """Extract official notice board URL from OFN JSON data."""
    url: str | None = ofn_data.get("stránka")
    return url


def extract_publisher_name_from_ofn(ofn_data: dict[str, Any]) -> str | None:
    """Extract publisher name from OFN JSON data."""
    provozovatel = ofn_data.get("provozovatel", {})
    nazev = provozovatel.get("název", {})
    return nazev.get("cs") if isinstance(nazev, dict) else nazev


async def fetch_all_ofn_urls(
    client: httpx.AsyncClient,
    datasets: list[dict[str, Any]],
    max_concurrent: int = 20,
) -> dict[str, dict[str, Any]]:
    """Fetch official URLs from all OFN datasets."""
    semaphore = asyncio.Semaphore(max_concurrent)
    results: dict[str, dict[str, Any]] = {}

    async def fetch_one(dataset: dict[str, Any]) -> None:
        json_url = extract_json_distribution_url(dataset)
        if not json_url:
            return

        publisher_title = dataset.get("publisher", {}).get("title", {})
        publisher_name = (
            publisher_title.get("cs") if isinstance(publisher_title, dict) else publisher_title
        )

        async with semaphore:
            ofn_data = await fetch_ofn_board_data(client, json_url)

        if ofn_data:
            official_url = extract_official_url_from_ofn(ofn_data)
            if not publisher_name:
                publisher_name = extract_publisher_name_from_ofn(ofn_data)

            if publisher_name:
                results[publisher_name] = {
                    "url": official_url,
                    "ofn_json_url": json_url,
                }

    logger.info(f"Fetching official URLs from {len(datasets)} OFN datasets...")
    tasks = [fetch_one(ds) for ds in datasets]
    await asyncio.gather(*tasks, return_exceptions=True)
    logger.info(f"Successfully extracted {len(results)} official URLs")

    return results


# Parsing and merging
def parse_cesko_digital_entry(entry: dict[str, Any]) -> NoticeBoardData:
    """Parse a single entry from Česko.Digital obce.json."""
    address_raw = entry.get("adresaUradu", {})
    address = None
    if address_raw:
        street = address_raw.get("ulice")
        house_number = address_raw.get("cisloDomovni")
        orientation_number = address_raw.get("cisloOrientacni")

        street_full = street
        if street and house_number:
            street_full = f"{street} {house_number}"
            if orientation_number:
                street_full = f"{street_full}/{orientation_number}"
        elif house_number:
            street_full = house_number

        address = Address(
            street_name=street_full,
            city=address_raw.get("obec"),
            district=address_raw.get("castObce"),
            postal_code=address_raw.get("PSC"),
            region=address_raw.get("kraj"),
            address_point_id=address_raw.get("adresniBod"),
        )

    coordinates_raw = entry.get("souradnice", [])
    coordinates = None
    if coordinates_raw and len(coordinates_raw) == 2:
        coordinates = (float(coordinates_raw[0]), float(coordinates_raw[1]))

    edesky_id = entry.get("eDeskyID")
    edesky_url = f"https://edesky.cz/desky/{edesky_id}" if edesky_id else None

    email_raw = entry.get("mail") or entry.get("email")
    emails = None
    if email_raw:
        if isinstance(email_raw, list):
            emails = email_raw
        elif isinstance(email_raw, str):
            emails = [email_raw]

    name = entry.get("hezkyNazev") or entry.get("nazev", "")
    abbreviation = entry.get("zkratka")
    type_ = determine_municipality_type(name, entry)

    legal_form = entry.get("pravniForma", {})
    legal_form_code = legal_form.get("type") if legal_form else None
    legal_form_label = legal_form.get("label") if legal_form else None

    coat_of_arms_url = entry.get("erb")
    municipality_code = entry.get("RUIAN") or (address_raw.get("obecKod") if address_raw else None)
    nutslau = entry.get("NUTS_LAU")

    return NoticeBoardData(
        name=name,
        abbreviation=abbreviation,
        ico=entry.get("ICO"),
        url=None,
        ofn_json_url=None,
        edesky_url=edesky_url,
        municipality_code=municipality_code,
        nutslau=nutslau,
        coordinates=coordinates,
        address=address,
        data_box_id=entry.get("datovaSchrankaID"),
        email=emails,
        legal_form_code=legal_form_code,
        legal_form_label=legal_form_label,
        coat_of_arms_url=coat_of_arms_url,
        type_=type_,
    )


def determine_municipality_type(name: str, entry: dict[str, Any]) -> str:
    """Determine municipality type from name and data."""
    name_lower = name.lower()

    if "městská část" in name_lower or "městský obvod" in name_lower:
        return "mestska_cast"
    if "kraj" in name_lower and "hlavní město" not in name_lower:
        return "kraj"
    if "statutární město" in name_lower or entry.get("statutarniMesto"):
        return "mesto"
    if name_lower.startswith("město "):
        return "mesto"
    if "hlavní město praha" in name_lower:
        return "mesto"

    population = entry.get("pocetObyvatel", 0)
    if population and int(population) > 3000:
        return "mesto"

    return "obec"


def normalize_name(name: str) -> str:
    """Normalize municipality name for matching."""
    name = name.lower().strip()
    prefixes = ["obec ", "město ", "městská část ", "městys ", "statutární město "]
    for prefix in prefixes:
        if name.startswith(prefix):
            name = name[len(prefix) :]
    return name


def merge_sources(
    cesko_digital_data: list[dict[str, Any]],
    ofn_urls: dict[str, dict[str, Any]],
) -> list[NoticeBoardData]:
    """Merge data from Česko.Digital and NKOD OFN sources."""
    logger.info(
        f"Merging {len(cesko_digital_data)} municipalities with {len(ofn_urls)} OFN entries"
    )

    ofn_by_normalized_name: dict[str, dict[str, Any]] = {}
    for name, data in ofn_urls.items():
        normalized = normalize_name(name)
        ofn_by_normalized_name[normalized] = data

    results: list[NoticeBoardData] = []
    matched_count = 0

    for entry in cesko_digital_data:
        board = parse_cesko_digital_entry(entry)
        normalized_name = normalize_name(board.name)
        ofn_data = ofn_by_normalized_name.get(normalized_name)

        if ofn_data:
            board.url = ofn_data.get("url")
            board.ofn_json_url = ofn_data.get("ofn_json_url")
            matched_count += 1

        results.append(board)

    logger.info(f"Merged {len(results)} municipalities, {matched_count} matched with OFN data")
    return results


def to_json_serializable(boards: list[NoticeBoardData]) -> list[dict[str, Any]]:
    """Convert list of NoticeBoardData to JSON-serializable dicts."""
    return [board.model_dump(mode="json", exclude_none=True) for board in boards]


# CLI
def setup_logging(verbose: bool = False) -> None:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stderr)],
    )


async def fetch_list(output_path: Path, skip_ofn: bool = False) -> None:
    """Fetch list of official notice boards and save to file."""
    async with httpx.AsyncClient(
        timeout=60.0,
        follow_redirects=True,
        headers={"User-Agent": "ruian2pg/0.1.0"},
    ) as client:
        cesko_digital_data = await fetch_cesko_digital(client)

        ofn_urls: dict[str, dict[str, Any]] = {}
        if not skip_ofn:
            nkod_datasets = await fetch_nkod_notice_boards(client)
            ofn_urls = await fetch_all_ofn_urls(client, nkod_datasets)

        merged = merge_sources(cesko_digital_data, ofn_urls)
        output_data = to_json_serializable(merged)

        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)

        logger.info(f"Saved {len(output_data)} records to {output_path}")

        with_official_url = sum(1 for d in output_data if d.get("url"))
        with_ofn_json = sum(1 for d in output_data if d.get("ofn_json_url"))
        with_edesky = sum(1 for d in output_data if d.get("edesky_url"))

        print("\nSummary:")
        print(f"  Total municipalities: {len(output_data)}")
        print(f"  With official URL:    {with_official_url}")
        print(f"  With OFN JSON URL:    {with_ofn_json}")
        print(f"  With eDesky URL:      {with_edesky}")


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Fetch Czech official notice boards data and save to JSON"
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("data/notice_boards.json"),
        help="Output file path (default: data/notice_boards.json)",
    )
    parser.add_argument(
        "--skip-ofn",
        action="store_true",
        help="Skip fetching OFN data from NKOD (faster, but no official URLs)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    setup_logging(args.verbose)
    asyncio.run(fetch_list(args.output, args.skip_ofn))


if __name__ == "__main__":
    main()
