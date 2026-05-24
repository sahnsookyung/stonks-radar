# Source Adapter Contract

Adapters return candidate observations, releases, documents, and explicit unsupported coverage.

Requirements:
- never write canonical data directly
- attach `source_key`, provider object key, source timestamp when available, and idempotency keys
- respect provider budget and source rate limits
- mark GDELT and similar aggregators as discovery-only
- label market data delayed/reference unless source policy explicitly permits realtime redistribution
