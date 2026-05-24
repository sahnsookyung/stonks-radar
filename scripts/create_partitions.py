from __future__ import annotations

import os
from datetime import date

from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://frw:frw@localhost:5432/frw")


def month_add(value: date, months: int) -> date:
    year = value.year + (value.month - 1 + months) // 12
    month = (value.month - 1 + months) % 12 + 1
    return date(year, month, 1)


def main() -> None:
    today = date.today().replace(day=1)
    engine = create_engine(DATABASE_URL, future=True)
    with engine.begin() as conn:
        for offset in range(-1, 4):
            start = month_add(today, offset)
            end = month_add(start, 1)
            name = f"observation_candidate_{start:%Y_%m}"
            conn.execute(
                text(
                    f"""
                    create table if not exists {name}
                    partition of observation_candidate
                    for values from ('{start.isoformat()}') to ('{end.isoformat()}')
                    """
                )
            )
            conn.execute(text(f"create index if not exists {name}_series_ts_idx on {name}(series_id, observation_timestamp desc)"))
            conn.execute(text(f"create index if not exists {name}_source_ingest_idx on {name}(source_id, ingest_timestamp desc)"))
            print(f"ensured_partition={name}")


if __name__ == "__main__":
    main()
