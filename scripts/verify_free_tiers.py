from __future__ import annotations

import argparse
import configparser
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROVIDER_ENV_FILE_KEYS = ("STONKS_SNAPSHOT_ENV_FILE", "STONKS_PROVIDER_ENV_FILE")
DEFAULT_PROVIDER_ENV_FILES = (
    ROOT / ".env",
    ROOT / ".secrets" / "stonks-radar.production.env",
)
_LOADED_PROVIDER_ENV_FILES: list[str] | None = None

PROVIDERS = {
    "FRED_API_KEY": "FRED live ingest",
    "BLS_API_KEY": "BLS higher-limit ingest",
    "EIA_API_KEY": "EIA live ingest",
    "MARKET_DATA_API_KEY": "licensed market-data ingest",
    "TWELVE_DATA_API_KEY": "portfolio market-data primary",
    "ALPHA_VANTAGE_API_KEY": "portfolio market-data fallback",
    "FMP_API_KEY": "portfolio market/fundamental fallback",
    "FINNHUB_API_KEY": "future market/fundamental fallback",
    "NASDAQ_DATA_LINK_API_KEY": "future Nasdaq Data Link datasets",
    "KRX_OPEN_API_AUTH_KEY": "KRX Open API for Korea index daily-trading ingest",
    "KRX_AUTH_KEY": "KRX Open API alias for Korea index daily-trading ingest",
    "KRX_API_KEY": "KRX Open API alias for Korea index daily-trading ingest",
    "DATA_GO_KR_SERVICE_KEY": "Korea public-data portal key for FSC/KRX-derived market data",
    "DATA_GO_KR_API_KEY": "Korea public-data portal alias for FSC/KRX-derived market data",
    "PUBLIC_DATA_API_KEY": "Korea public-data portal alias for FSC/KRX-derived market data",
    "KOREA_PUBLIC_DATA_API_KEY": "Korea public-data portal alias for FSC/KRX-derived market data",
    "FINRA_API_TOKEN": "FINRA bearer token for short interest/short volume ingest",
    "FINRA_API_CLIENT_ID": "FINRA OAuth client id for short interest/short volume ingest",
    "FINRA_API_CLIENT_SECRET": "FINRA OAuth client secret for short interest/short volume ingest",
    "GEMINI_API_KEY": "Gemini public-facts LLM tasks",
    "GROQ_API_KEY": "Groq public-facts LLM tasks",
    "CEREBRAS_API_KEY": "Cerebras public-facts LLM tasks",
    "MISTRAL_API_KEY": "Mistral public-facts LLM tasks",
    "OPENROUTER_API_KEY": "OpenRouter public-facts LLM tasks",
    "HF_TOKEN": "Hugging Face public-facts LLM tasks",
}

OCI_ALWAYS_FREE_LIMITS = {
    "a1_ocpus": 4.0,
    "a1_memory_gb": 24.0,
    "block_volume_total_gb": 200,
}

TERMINAL_STATES = {"TERMINATED", "TERMINATING"}

PROVIDER_COVERAGE_GROUPS = {
    "fred_macro_pulse": {
        "required_any": ("FRED_API_KEY",),
        "description": "FRED-backed macro, rates, volatility, FX, and commodity pulse tiles",
    },
    "krx_korea_pulse": {
        "required_any": (
            "KRX_OPEN_API_AUTH_KEY",
            "KRX_AUTH_KEY",
            "KRX_API_KEY",
            "DATA_GO_KR_SERVICE_KEY",
            "DATA_GO_KR_API_KEY",
            "PUBLIC_DATA_API_KEY",
            "KOREA_PUBLIC_DATA_API_KEY",
        ),
        "description": "Official Korea market pulse via KRX Open API or FSC/KRX public-data portal",
    },
    "finra_shorts": {
        "required_any": ("FINRA_API_TOKEN",),
        "required_groups_any": (("FINRA_API_CLIENT_ID", "FINRA_API_CLIENT_SECRET"),),
        "description": "FINRA short interest and Reg SHO short-volume ingest",
    },
}


def _oci_config_path() -> Path:
    return Path(os.getenv("OCI_CLI_CONFIG_FILE", "~/.oci/config")).expanduser()


def _oci_profile() -> str:
    return os.getenv("OCI_CLI_PROFILE", "DEFAULT")


def _load_oci_config() -> tuple[str | None, str | None]:
    config_path = _oci_config_path()
    if not config_path.exists():
        return None, None
    parser = configparser.ConfigParser()
    parser.read(config_path)
    profile = _oci_profile()
    if profile not in parser:
        return None, None
    return parser[profile].get("tenancy"), parser[profile].get("region")


def _run_oci(args: list[str]) -> dict[str, Any]:
    result = subprocess.run(
        ["oci", *args, "--output", "json"],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout or "{}")


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


def _provider_env_file_candidates() -> list[Path]:
    candidates = list(DEFAULT_PROVIDER_ENV_FILES)
    for env_name in PROVIDER_ENV_FILE_KEYS:
        env_path = os.getenv(env_name)
        if env_path:
            candidates.append(Path(env_path).expanduser())
    return candidates


def _load_provider_env_files() -> list[str]:
    global _LOADED_PROVIDER_ENV_FILES
    if _LOADED_PROVIDER_ENV_FILES is not None:
        return _LOADED_PROVIDER_ENV_FILES

    loaded: dict[str, str] = {}
    loaded_paths: list[str] = []
    for path in _provider_env_file_candidates():
        if not path.exists():
            continue
        loaded.update(_read_env_file(path))
        loaded_paths.append(str(path))

    for key, value in loaded.items():
        if value:
            os.environ.setdefault(key, value)

    _LOADED_PROVIDER_ENV_FILES = loaded_paths
    return loaded_paths


def _active_compartments(tenancy_ocid: str) -> tuple[list[dict[str, str]], list[str]]:
    compartments = [{"id": tenancy_ocid, "name": "root-tenancy"}]
    warnings: list[str] = []
    try:
        payload = _run_oci(
            [
                "iam",
                "compartment",
                "list",
                "--compartment-id",
                tenancy_ocid,
                "--compartment-id-in-subtree",
                "true",
                "--access-level",
                "ANY",
                "--all",
            ]
        )
        for item in payload.get("data", []):
            if item.get("lifecycle-state") == "ACTIVE":
                compartments.append({"id": item["id"], "name": item.get("name", item["id"])})
    except (subprocess.CalledProcessError, KeyError, json.JSONDecodeError) as exc:
        warnings.append(f"compartment_list_error={type(exc).__name__}")
    return compartments, warnings


def _availability_domains(tenancy_ocid: str) -> tuple[list[str], list[str]]:
    try:
        payload = _run_oci(["iam", "availability-domain", "list", "--compartment-id", tenancy_ocid])
        return [item["name"] for item in payload.get("data", [])], []
    except (subprocess.CalledProcessError, KeyError, json.JSONDecodeError) as exc:
        return [], [f"availability_domain_list_error={type(exc).__name__}"]


def _oci_capacity() -> dict[str, Any]:
    if not shutil.which("oci"):
        return {"configured": False, "reason": "oci_cli_missing"}

    tenancy_ocid, region = _load_oci_config()
    if not tenancy_ocid:
        return {"configured": False, "reason": "oci_config_missing_tenancy"}

    warnings: list[str] = []
    compartments, compartment_warnings = _active_compartments(tenancy_ocid)
    warnings.extend(compartment_warnings)
    availability_domains, ad_warnings = _availability_domains(tenancy_ocid)
    warnings.extend(ad_warnings)

    instances: list[dict[str, Any]] = []
    boot_volumes: list[dict[str, Any]] = []
    block_volumes: list[dict[str, Any]] = []

    for compartment in compartments:
        try:
            payload = _run_oci(
                [
                    "compute",
                    "instance",
                    "list",
                    "--compartment-id",
                    compartment["id"],
                    "--all",
                ]
            )
            for item in payload.get("data", []):
                if item.get("lifecycle-state") in TERMINAL_STATES:
                    continue
                shape_config = item.get("shape-config") or {}
                instances.append(
                    {
                        "compartment": compartment["name"],
                        "name": item.get("display-name"),
                        "shape": item.get("shape"),
                        "state": item.get("lifecycle-state"),
                        "availability_domain": item.get("availability-domain"),
                        "ocpus": shape_config.get("ocpus"),
                        "memory_gb": shape_config.get("memory-in-gbs"),
                    }
                )
        except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
            warnings.append(f"instance_list_error:{compartment['name']}={type(exc).__name__}")

        try:
            payload = _run_oci(["bv", "volume", "list", "--compartment-id", compartment["id"], "--all"])
            for item in payload.get("data", []):
                if item.get("lifecycle-state") in TERMINAL_STATES:
                    continue
                block_volumes.append(
                    {
                        "compartment": compartment["name"],
                        "name": item.get("display-name"),
                        "state": item.get("lifecycle-state"),
                        "size_gb": item.get("size-in-gbs"),
                    }
                )
        except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
            warnings.append(f"block_volume_list_error:{compartment['name']}={type(exc).__name__}")

        for availability_domain in availability_domains:
            try:
                payload = _run_oci(
                    [
                        "bv",
                        "boot-volume",
                        "list",
                        "--availability-domain",
                        availability_domain,
                        "--compartment-id",
                        compartment["id"],
                        "--all",
                    ]
                )
                for item in payload.get("data", []):
                    if item.get("lifecycle-state") in TERMINAL_STATES:
                        continue
                    boot_volumes.append(
                        {
                            "compartment": compartment["name"],
                            "name": item.get("display-name"),
                            "state": item.get("lifecycle-state"),
                            "availability_domain": availability_domain,
                            "size_gb": item.get("size-in-gbs"),
                        }
                    )
            except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
                warnings.append(
                    f"boot_volume_list_error:{compartment['name']}:{availability_domain}={type(exc).__name__}"
                )

    a1_instances = [item for item in instances if item.get("shape") == "VM.Standard.A1.Flex"]
    a1_ocpus = sum(float(item.get("ocpus") or 0) for item in a1_instances)
    a1_memory = sum(float(item.get("memory_gb") or 0) for item in a1_instances)
    boot_volume_gb = sum(int(item.get("size_gb") or 0) for item in boot_volumes)
    block_volume_gb = sum(int(item.get("size_gb") or 0) for item in block_volumes)

    remaining = {
        "a1_ocpus": OCI_ALWAYS_FREE_LIMITS["a1_ocpus"] - a1_ocpus,
        "a1_memory_gb": OCI_ALWAYS_FREE_LIMITS["a1_memory_gb"] - a1_memory,
        "block_volume_total_gb": OCI_ALWAYS_FREE_LIMITS["block_volume_total_gb"]
        - boot_volume_gb
        - block_volume_gb,
    }
    return {
        "configured": True,
        "region": region,
        "profile": _oci_profile(),
        "compartments_checked": [item["name"] for item in compartments],
        "availability_domains": availability_domains,
        "instances": instances,
        "boot_volumes": boot_volumes,
        "block_volumes": block_volumes,
        "limits": OCI_ALWAYS_FREE_LIMITS,
        "used": {
            "a1_ocpus": a1_ocpus,
            "a1_memory_gb": a1_memory,
            "boot_volume_gb": boot_volume_gb,
            "block_volume_gb": block_volume_gb,
            "block_volume_total_gb": boot_volume_gb + block_volume_gb,
        },
        "remaining": remaining,
        "within_always_free": all(value >= 0 for value in remaining.values()),
        "can_create_new_a1_instance": remaining["a1_ocpus"] > 0
        and remaining["a1_memory_gb"] > 0
        and remaining["block_volume_total_gb"] >= 47,
        "warnings": warnings,
    }


def _provider_status() -> dict[str, str]:
    _load_provider_env_files()
    return {env_name: "configured" if os.getenv(env_name) else "missing" for env_name in PROVIDERS}


def _coverage_status() -> dict[str, dict[str, Any]]:
    _load_provider_env_files()
    coverage: dict[str, dict[str, Any]] = {}
    for name, spec in PROVIDER_COVERAGE_GROUPS.items():
        required_any = spec.get("required_any", ())
        required_groups_any = spec.get("required_groups_any", ())
        satisfied_by_any = [key for key in required_any if os.getenv(key)]
        satisfied_by_group = [
            list(group) for group in required_groups_any if all(os.getenv(key) for key in group)
        ]
        configured = bool(satisfied_by_any or satisfied_by_group)
        coverage[name] = {
            "status": "configured" if configured else "missing",
            "description": spec["description"],
            "required_any": list(required_any),
            "required_groups_any": [list(group) for group in required_groups_any],
            "satisfied_by_any": satisfied_by_any,
            "satisfied_by_group": satisfied_by_group,
            "missing_any": [] if configured else [key for key in required_any if not os.getenv(key)],
            "missing_groups_any": []
            if configured
            else [
                [key for key in group if not os.getenv(key)]
                for group in required_groups_any
                if not all(os.getenv(key) for key in group)
            ],
        }
    return coverage


def _build_report(include_oci: bool) -> dict[str, Any]:
    loaded_env_files = _load_provider_env_files()
    report: dict[str, Any] = {
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "paid_usage_allowed": os.getenv("PAID_USAGE_ALLOWED", "false").lower() == "true",
        "provider_env_files_loaded": loaded_env_files,
        "providers": _provider_status(),
        "coverage": _coverage_status(),
    }
    if include_oci:
        report["oci"] = _oci_capacity()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Check paid-provider and OCI Always Free capacity gates.")
    parser.add_argument("--no-oci", action="store_true", help="Skip OCI CLI capacity checks.")
    args = parser.parse_args()
    report = _build_report(include_oci=not args.no_oci)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
