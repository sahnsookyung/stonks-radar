from __future__ import annotations

import argparse
import asyncio
import json

from frw_api.db.session import SessionLocal
from frw_api.services.trump_disclosures import ingest_trump_disclosures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest Trump-family public disclosure filings.")
    parser.add_argument("--skip-oge", action="store_true", help="Do not fetch OGE disclosure records/PDFs.")
    parser.add_argument("--skip-sec", action="store_true", help="Do not fetch SEC EDGAR submissions/documents.")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    with SessionLocal() as db:
        result = await ingest_trump_disclosures(
            db,
            include_oge=not args.skip_oge,
            include_sec=not args.skip_sec,
        )
        db.commit()
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
