from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import json
import os
from pathlib import Path
import time
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
DATA_GO_KR_ENV_NAMES = (
    "DATA_GO_KR_SERVICE_KEY",
    "DATA_GO_KR_API_KEY",
    "PUBLIC_DATA_API_KEY",
    "KOREA_PUBLIC_DATA_API_KEY",
)
KOREA_MARKET_DATA_SOURCES = (
    "krx",
    "fsc_market_index",
    "fsc_securities_product",
    "fsc_derivatives",
    "ishares_ewy",
)


@dataclass(frozen=True)
class SourceProbe:
    url: str
    url_env: str | None = None
    path: str | None = None
    required_env: str | None = None
    required_env_any: tuple[str, ...] = ()
    params: dict[str, str] | None = None
    api_key_param: str | None = "api_key"
    auth_header: str | None = None
    expect: Callable[[httpx.Response], tuple[bool, str | None]] | None = None
    timeout_seconds: float = 10.0
    follow_redirects: bool = False


@dataclass(frozen=True)
class SourceHealthResult:
    source_key: str
    status: str
    status_code: str | None
    response_ms: int | None
    error: str | None
    details: dict[str, Any]


def _json_has(*keys: str) -> Callable[[httpx.Response], tuple[bool, str | None]]:
    def expect(response: httpx.Response) -> tuple[bool, str | None]:
        if response.status_code != 200:
            return False, f"unexpected status {response.status_code}"
        try:
            payload = response.json()
        except ValueError:
            return False, "response was not JSON"
        current: Any = payload
        for key in keys:
            if not isinstance(current, dict):
                return False, f"missing JSON key {'.'.join(keys)}"
            current = current.get(key)
        return current is not None, None if current is not None else f"missing JSON key {'.'.join(keys)}"

    return expect


def _status_200(response: httpx.Response) -> tuple[bool, str | None]:
    return response.status_code == 200, None if response.status_code == 200 else f"unexpected status {response.status_code}"


def _html_contains(*needles: str) -> Callable[[httpx.Response], tuple[bool, str | None]]:
    def expect(response: httpx.Response) -> tuple[bool, str | None]:
        if response.status_code != 200:
            return False, f"unexpected status {response.status_code}"
        body = response.text
        missing = [needle for needle in needles if needle not in body]
        return not missing, None if not missing else f"missing page marker: {missing[0]}"

    return expect


def _krx_status(response: httpx.Response) -> tuple[bool, str | None]:
    if response.status_code == 200:
        return True, None
    message = ""
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if isinstance(payload, dict):
        message = str(payload.get("respMsg") or payload.get("message") or "").strip()
    if response.status_code == 401 and message:
        return False, f"KRX {message}; confirm the key is approved for this Open API service"
    return False, f"unexpected status {response.status_code}"


def _data_go_kr_status(response: httpx.Response) -> tuple[bool, str | None]:
    if response.status_code != 200:
        return False, f"unexpected status {response.status_code}"
    try:
        payload = response.json()
    except ValueError:
        return False, "response was not JSON"
    header = payload.get("response", {}).get("header") if isinstance(payload, dict) else None
    result_code = str((header or {}).get("resultCode") or "").strip()
    if result_code and result_code != "00":
        message = str((header or {}).get("resultMsg") or "public-data API returned an error").strip()
        return False, f"data.go.kr {result_code}: {message}"
    items = payload.get("response", {}).get("body", {}).get("items") if isinstance(payload, dict) else None
    return items not in (None, "", []), None if items not in (None, "", []) else "data.go.kr response had no items"


SOURCES: dict[str, SourceProbe] = {
    "bls": SourceProbe(
        "https://api.bls.gov/publicAPI/v2/timeseries/data/CUUR0000SA0",
        params={"startyear": "2024", "endyear": "2024"},
        expect=_json_has("Results", "series"),
    ),
    "fred": SourceProbe(
        "https://api.stlouisfed.org/fred/series/observations",
        required_env="FRED_API_KEY",
        params={
            "series_id": "GDP",
            "file_type": "json",
            "observation_start": "2024-01-01",
            "limit": "1",
        },
        expect=_json_has("observations"),
    ),
    "federal_reserve": SourceProbe(
        "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
        expect=_status_200,
    ),
    "treasury_xml_feed": SourceProbe(
        "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml",
        params={"data": "daily_treasury_yield_curve", "field_tdr_date_value": "2026"},
        expect=_html_contains("DailyTreasuryYieldCurveRateData", "BC_10YEAR"),
        timeout_seconds=20.0,
    ),
    "sec_edgar": SourceProbe(
        "https://data.sec.gov/submissions/CIK0000320193.json",
        expect=_json_has("cik"),
    ),
    "eia": SourceProbe(
        "https://api.eia.gov/v2/electricity/rto/region-data/data/",
        required_env="EIA_API_KEY",
        params={
            "frequency": "hourly",
            "data[0]": "value",
            "facets[respondent][]": "CAL",
            "start": "2024-01-01T00",
            "end": "2024-01-01T00",
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
            "offset": "0",
            "length": "1",
        },
        expect=_json_has("response"),
    ),
    "krx": SourceProbe(
        "https://data-dbg.krx.co.kr/svc/apis/idx/krx_dd_trd.json",
        url_env="KRX_OPEN_API_BASE_URL",
        path="idx/krx_dd_trd.json",
        required_env_any=("KRX_OPEN_API_AUTH_KEY", "KRX_AUTH_KEY", "KRX_API_KEY"),
        params={"basDd": "20260526"},
        api_key_param=None,
        auth_header="AUTH_KEY",
        expect=_krx_status,
    ),
    "fsc_market_index": SourceProbe(
        "https://apis.data.go.kr/1160100/service/GetMarketIndexInfoService/getStockMarketIndex",
        required_env_any=DATA_GO_KR_ENV_NAMES,
        params={"resultType": "json", "pageNo": "1", "numOfRows": "1", "likeIdxNm": "KOSPI"},
        api_key_param="serviceKey",
        expect=_data_go_kr_status,
    ),
    "fsc_securities_product": SourceProbe(
        "https://apis.data.go.kr/1160100/service/GetSecuritiesProductInfoService/getETFPriceInfo",
        required_env_any=DATA_GO_KR_ENV_NAMES,
        params={"resultType": "json", "pageNo": "1", "numOfRows": "1", "likeItmsNm": "KODEX 200"},
        api_key_param="serviceKey",
        expect=_data_go_kr_status,
    ),
    "fsc_derivatives": SourceProbe(
        "https://apis.data.go.kr/1160100/GetDerivativeProductInfoService/getStockFuturesPriceInfo",
        required_env_any=DATA_GO_KR_ENV_NAMES,
        params={"resultType": "json", "pageNo": "1", "numOfRows": "1", "likeItmsNm": "KOSPI 200"},
        api_key_param="serviceKey",
        expect=_data_go_kr_status,
    ),
    "ishares_ewy": SourceProbe(
        "https://www.ishares.com/us/products/239681/ishares-msci-south-korea-etf",
        expect=_html_contains("iShares MSCI South Korea ETF", "fundHeader.fundNav.navAmount"),
    ),
    "ecb": SourceProbe(
        "https://data-api.ecb.europa.eu/service/dataflow/ECB/EXR/1.0",
        params={"detail": "allstubs"},
        expect=_status_200,
    ),
    "world_bank": SourceProbe(
        "https://api.worldbank.org/v2/country/USA/indicator/NY.GDP.MKTP.CD",
        params={"format": "json"},
        expect=_status_200,
    ),
}


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _load_env() -> None:
    loaded: dict[str, str] = {}
    candidates = [ROOT / ".env", ROOT / ".secrets" / "stonks-radar.production.env"]
    for env_name in ("STONKS_SNAPSHOT_ENV_FILE", "STONKS_PROVIDER_ENV_FILE", "STONKS_SOURCE_HEALTH_ENV_FILE"):
        explicit_env = os.getenv(env_name)
        if explicit_env:
            candidates.append(Path(explicit_env).expanduser())
    for path in candidates:
        loaded.update(_read_env_file(path))
    for key, value in loaded.items():
        if value:
            os.environ.setdefault(key, value)


def _selected_required_env(probe: SourceProbe) -> str | None:
    if probe.required_env:
        return probe.required_env if os.getenv(probe.required_env) else None
    for env_name in probe.required_env_any:
        if os.getenv(env_name):
            return env_name
    return None


def _required_env_label(probe: SourceProbe) -> str | None:
    if probe.required_env:
        return probe.required_env
    if probe.required_env_any:
        return " or ".join(probe.required_env_any)
    return None


async def check(name: str, probe: SourceProbe) -> SourceHealthResult:
    required_env = _selected_required_env(probe)
    if (probe.required_env or probe.required_env_any) and not required_env:
        required_label = _required_env_label(probe)
        return SourceHealthResult(
            source_key=name,
            status="unsupported",
            status_code=None,
            response_ms=None,
            error=f"{required_label} is not configured",
            details={"required_env": required_label},
        )

    headers = {
        "User-Agent": os.getenv("SEC_USER_AGENT", "StonksRadar health-check contact@example.com"),
        "Accept": "application/json, application/xml, text/xml, text/html, */*",
    }
    params = dict(probe.params or {})
    if required_env and probe.api_key_param:
        params[probe.api_key_param] = os.environ[required_env]
    if required_env and probe.auth_header:
        headers[probe.auth_header] = os.environ[required_env]

    url = _probe_url(probe)
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(
            timeout=probe.timeout_seconds,
            follow_redirects=probe.follow_redirects,
            headers=headers,
            trust_env=False,
        ) as client:
            response = await client.get(url, params=params)
            elapsed = int((time.perf_counter() - start) * 1000)
            expect = probe.expect or _status_200
            ready, error = expect(response)
            return SourceHealthResult(
                source_key=name,
                status="ready" if ready else "failed",
                status_code=str(response.status_code),
                response_ms=elapsed,
                error=error,
                details={
                    "url": url,
                    "required_env": probe.required_env,
                    "content_type": response.headers.get("content-type"),
                    "credential_env": required_env,
                },
            )
    except Exception as exc:  # noqa: BLE001
        return SourceHealthResult(
            source_key=name,
            status="failed",
            status_code=exc.__class__.__name__,
            response_ms=int((time.perf_counter() - start) * 1000),
            error=str(exc),
            details={"url": url, "required_env": _required_env_label(probe), "credential_env": required_env},
        )


def _probe_url(probe: SourceProbe) -> str:
    if probe.url_env and probe.path:
        base_url = os.getenv(probe.url_env)
        if not base_url and _truthy(os.getenv("KRX_ALLOW_SAMPLE_API_FALLBACK")):
            base_url = os.getenv("KRX_SAMPLE_API_BASE_URL", "https://data-dbg.krx.co.kr/svc/sample/apis")
        if base_url:
            return f"{base_url.rstrip('/')}/{probe.path.lstrip('/')}"
    return probe.url


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _source_list(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    if value.strip().lower() in {"0", "false", "none", "off"}:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _required_ready_failures(results: list[SourceHealthResult], required_ready: tuple[str, ...]) -> list[str]:
    by_name = {result.source_key: result for result in results}
    failures: list[str] = []
    for source_key in required_ready:
        if source_key == "korea_market_data":
            ready_sources = [
                name for name in KOREA_MARKET_DATA_SOURCES if by_name.get(name) and by_name[name].status == "ready"
            ]
            if ready_sources:
                continue
            source_statuses = [
                f"{name}={by_name[name].status}:{by_name[name].error or by_name[name].status_code}"
                for name in KOREA_MARKET_DATA_SOURCES
                if name in by_name
            ]
            failures.append("korea_market_data=failed:" + ", ".join(source_statuses or ["no configured Korea source"]))
            continue
        result = by_name.get(source_key)
        if result is None:
            failures.append(f"{source_key}=missing_probe")
        elif result.status != "ready":
            failures.append(f"{source_key}={result.status}:{result.error or result.status_code}")
    return failures


async def main(required_ready: tuple[str, ...] = ()) -> None:
    _load_env()
    results = await asyncio.gather(*(check(name, probe) for name, probe in SOURCES.items()))
    for result in results:
        suffix = f" ({result.error})" if result.error else ""
        print(f"{result.source_key}: {result.status}{suffix}")
    if os.getenv("DATABASE_URL"):
        from sqlalchemy import create_engine, text

        try:
            engine = create_engine(os.environ["DATABASE_URL"], future=True)
            with engine.begin() as conn:
                for result in results:
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
                              :error, cast(:details as jsonb)
                            )
                            on conflict (source_key) do update
                            set status = excluded.status,
                                status_code = excluded.status_code,
                                response_ms = excluded.response_ms,
                                last_checked_at = now(),
                                last_success_at = case when excluded.status = 'ready' then now() else source_health_status.last_success_at end,
                                last_error = excluded.last_error,
                                details = excluded.details
                            """
                        ),
                        {
                            "source_key": result.source_key,
                            "status": result.status,
                            "status_code": result.status_code,
                            "response_ms": result.response_ms,
                            "error": result.error,
                            "details": json.dumps(result.details),
                        },
                    )
        except Exception as exc:  # noqa: BLE001
            print(f"source_health_db_write: skipped ({exc.__class__.__name__})")
    failures = _required_ready_failures(list(results), required_ready)
    if failures:
        raise SystemExit("source_health_required_failed: " + "; ".join(failures))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check source connectivity and credential health.")
    parser.add_argument(
        "--require-ready",
        default=os.getenv("STONKS_SOURCE_HEALTH_REQUIRE_READY", ""),
        help="Comma-separated source keys that must return ready. Use 'none' to disable.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(main(required_ready=_source_list(args.require_ready)))
