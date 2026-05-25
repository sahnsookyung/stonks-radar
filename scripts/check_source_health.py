from __future__ import annotations

import asyncio
import os
import time

import httpx

SOURCES = {
    "bls": "https://api.bls.gov/publicAPI/v2/timeseries/data/",
    "fred": "https://api.stlouisfed.org/fred/category?category_id=0&file_type=json",
    "federal_reserve": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
    "sec_edgar": "https://data.sec.gov/submissions/CIK0000320193.json",
    "eia": "https://api.eia.gov/v2/",
    "ecb": "https://data-api.ecb.europa.eu/service/data",
    "world_bank": "https://api.worldbank.org/v2/country/USA/indicator/NY.GDP.MKTP.CD?format=json",
}


async def check(name: str, url: str) -> tuple[str, int | str]:
    headers = {"User-Agent": "StonksRadar health-check contact@example.com"}
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=False, headers=headers) as client:
            response = await client.get(url)
            return name, response.status_code, int((time.perf_counter() - start) * 1000)
    except Exception as exc:  # noqa: BLE001
        return name, exc.__class__.__name__, int((time.perf_counter() - start) * 1000)


async def main() -> None:
    results = await asyncio.gather(*(check(name, url) for name, url in SOURCES.items()))
    for name, status, _elapsed in results:
        print(f"{name}: {status}")
    if os.getenv("DATABASE_URL"):
        from sqlalchemy import create_engine, text

        engine = create_engine(os.environ["DATABASE_URL"], future=True)
        with engine.begin() as conn:
            for name, status, elapsed in results:
                ready = isinstance(status, int) and status < 500
                conn.execute(
                    text(
                        """
                        insert into source_health_status(
                          source_key, status, status_code, response_ms, last_checked_at,
                          last_success_at, last_error, details
                        )
                        values (
                          :source_key, :status, :status_code, :response_ms, now(),
                          case when :status = 'ready' then now() else null end,
                          :error, '{}'::jsonb
                        )
                        on conflict (source_key) do update
                        set status = excluded.status,
                            status_code = excluded.status_code,
                            response_ms = excluded.response_ms,
                            last_checked_at = now(),
                            last_success_at = case when excluded.status = 'ready' then now() else source_health_status.last_success_at end,
                            last_error = excluded.last_error
                        """
                    ),
                    {
                        "source_key": name,
                        "status": "ready" if ready else "failed",
                        "status_code": str(status),
                        "response_ms": elapsed,
                        "error": None if ready else str(status),
                    },
                )


if __name__ == "__main__":
    asyncio.run(main())
