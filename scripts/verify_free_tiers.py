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
    "KRX_OPEN_API_AUTH_KEY": "KRX Open API for KODEX 200 and KOSPI 200 futures ingest",
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
    return {env_name: "configured" if os.getenv(env_name) else "missing" for env_name in PROVIDERS}


def _build_report(include_oci: bool) -> dict[str, Any]:
    report: dict[str, Any] = {
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "paid_usage_allowed": os.getenv("PAID_USAGE_ALLOWED", "false").lower() == "true",
        "providers": _provider_status(),
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
