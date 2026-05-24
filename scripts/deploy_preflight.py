from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from verify_free_tiers import _build_report

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    min_ocpus = float(os.getenv("DEPLOY_MIN_A1_OCPUS", "2"))
    min_memory = float(os.getenv("DEPLOY_MIN_A1_MEMORY_GB", "12"))
    min_storage = float(os.getenv("DEPLOY_MIN_STORAGE_GB", os.getenv("DEPLOY_MIN_BLOCK_GB", "50")))
    target_instance_name = os.getenv("DEPLOY_TARGET_INSTANCE_NAME", "stonks-radar")
    report = _build_report(include_oci=True)
    oci = report.get("oci", {})
    if not oci.get("configured"):
        raise SystemExit(f"OCI preflight failed: {oci.get('reason', 'not configured')}")
    failures = []
    target_instance = _target_instance(oci, target_instance_name)
    if target_instance:
        if target_instance.get("shape") != "VM.Standard.A1.Flex":
            failures.append(f"Target instance {target_instance_name} is not VM.Standard.A1.Flex")
        if float(target_instance.get("ocpus") or 0) < min_ocpus:
            failures.append(f"Target instance OCPU {target_instance.get('ocpus')} < {min_ocpus}")
        if float(target_instance.get("memory_gb") or 0) < min_memory:
            failures.append(f"Target instance memory {target_instance.get('memory_gb')} GB < {min_memory} GB")
        boot_volume = _target_boot_volume(oci, target_instance_name)
        if not boot_volume:
            failures.append(f"Could not verify boot volume for target instance {target_instance_name}")
        elif float(boot_volume.get("size_gb") or 0) < min_storage:
            failures.append(f"Target boot volume {boot_volume.get('size_gb')} GB < {min_storage} GB")
        if not oci.get("within_always_free"):
            failures.append("OCI usage is outside the Always Free envelope")
    else:
        remaining = oci.get("remaining", {})
        if float(remaining.get("a1_ocpus", 0)) < min_ocpus:
            failures.append(f"A1 OCPU remaining {remaining.get('a1_ocpus')} < {min_ocpus}")
        if float(remaining.get("a1_memory_gb", 0)) < min_memory:
            failures.append(f"A1 memory remaining {remaining.get('a1_memory_gb')} GB < {min_memory} GB")
        if float(remaining.get("block_volume_total_gb", 0)) < min_storage:
            failures.append(f"Storage remaining {remaining.get('block_volume_total_gb')} GB < {min_storage} GB")
    if failures:
        print(json.dumps(report, indent=2, sort_keys=True))
        raise SystemExit("OCI Always Free capacity preflight failed: " + "; ".join(failures))

    _run(["npm", "run", "check:schemas"])
    _run(["docker", "compose", "-f", "compose.yaml", "-f", "infra/docker-compose.prod.yml", "config"])
    _run(["uv", "run", "--project", ".", "alembic", "-c", "alembic.ini", "upgrade", "head", "--sql"], cwd=ROOT / "apps/api")
    print("deploy_preflight=ok")


def _target_instance(oci: dict, target_instance_name: str) -> dict | None:
    for instance in oci.get("instances", []):
        if instance.get("name") == target_instance_name:
            return instance
    return None


def _target_boot_volume(oci: dict, target_instance_name: str) -> dict | None:
    for volume in oci.get("boot_volumes", []):
        name = volume.get("name") or ""
        if name == f"{target_instance_name} (Boot Volume)" or name.startswith(f"{target_instance_name} "):
            return volume
    return None


def _run(cmd: list[str], cwd: Path = ROOT) -> None:
    subprocess.run(cmd, cwd=cwd, check=True)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc
