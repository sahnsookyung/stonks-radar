#!/usr/bin/env node
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";

function main() {
  const options = parseArgs(process.argv.slice(2));
  if (!options.base || !options.target) {
    throw new Error("Usage: node scripts/snapshot_diff.mjs --base <snapshot-root> --target <snapshot-root> [--json]");
  }
  const baseRoot = path.resolve(options.base);
  const targetRoot = path.resolve(options.target);
  const baseManifest = readJson(path.join(baseRoot, "latest", "manifest.json"));
  const targetManifest = readJson(path.join(targetRoot, "latest", "manifest.json"));
  const rows = diffManifestObjects(baseRoot, targetRoot, baseManifest, targetManifest);
  const summary = summarize(rows);
  const outputRows = options.includeUnchanged ? rows : rows.filter((row) => row.status !== "unchanged");
  const report = {
    base_root: baseRoot,
    target_root: targetRoot,
    base_version: baseManifest.current_version,
    target_version: targetManifest.current_version,
    summary,
    rows: outputRows
  };

  if (options.json) {
    console.log(JSON.stringify(report, null, 2));
  } else {
    printMarkdown(report);
  }

  if (summary.removed > 0 || summary.errors > 0) {
    process.exitCode = 1;
  }
}

function parseArgs(args) {
  const options = { base: undefined, target: undefined, json: false, includeUnchanged: false };
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (arg === "--base") options.base = args[++index];
    else if (arg === "--target") options.target = args[++index];
    else if (arg === "--json") options.json = true;
    else if (arg === "--include-unchanged") options.includeUnchanged = true;
    else if (!options.base) options.base = arg;
    else if (!options.target) options.target = arg;
    else throw new Error(`Unexpected argument: ${arg}`);
  }
  return options;
}

function diffManifestObjects(baseRoot, targetRoot, baseManifest, targetManifest) {
  const keys = new Set([...Object.keys(baseManifest.objects ?? {}), ...Object.keys(targetManifest.objects ?? {})]);
  const rows = [];
  for (const objectKey of [...keys].sort(compareText)) {
    const locales = new Set([
      ...Object.keys(baseManifest.objects?.[objectKey] ?? {}),
      ...Object.keys(targetManifest.objects?.[objectKey] ?? {})
    ]);
    for (const locale of [...locales].sort(compareText)) {
      const baseManifestPath = baseManifest.objects?.[objectKey]?.[locale];
      const targetManifestPath = targetManifest.objects?.[objectKey]?.[locale];
      rows.push(diffSnapshot(baseRoot, targetRoot, objectKey, locale, baseManifestPath, targetManifestPath));
    }
  }
  return rows;
}

function diffSnapshot(baseRoot, targetRoot, objectKey, locale, baseManifestPath, targetManifestPath) {
  if (!baseManifestPath) return { object_key: objectKey, locale, status: "added", target_path: targetManifestPath };
  if (!targetManifestPath) return { object_key: objectKey, locale, status: "removed", base_path: baseManifestPath };

  try {
    const baseSnapshot = readJson(resolveManifestPath(baseRoot, baseManifestPath));
    const targetSnapshot = readJson(resolveManifestPath(targetRoot, targetManifestPath));
    const baseHash = stableHash(baseSnapshot);
    const targetHash = stableHash(targetSnapshot);
    return {
      object_key: objectKey,
      locale,
      status: baseHash === targetHash ? "unchanged" : "changed",
      base_path: baseManifestPath,
      target_path: targetManifestPath,
      base_snapshot_version: baseSnapshot.snapshot_version,
      target_snapshot_version: targetSnapshot.snapshot_version,
      base_content_hash: baseSnapshot.content_hash,
      target_content_hash: targetSnapshot.content_hash,
      metrics: metricDelta(snapshotMetrics(baseSnapshot), snapshotMetrics(targetSnapshot))
    };
  } catch (error) {
    return {
      object_key: objectKey,
      locale,
      status: "error",
      base_path: baseManifestPath,
      target_path: targetManifestPath,
      error: error instanceof Error ? error.message : String(error)
    };
  }
}

function snapshotMetrics(snapshot) {
  const data = snapshot.data ?? {};
  const breakingMap = data.breaking_market_map ?? {};
  return {
    events: count(data.events),
    breaking_events: count(data.breaking_market_events ?? breakingMap.events),
    map_points: count(breakingMap.map_points),
    coverage_gaps: count(breakingMap.coverage_gaps),
    regional_briefs: count(breakingMap.regional_briefs)
  };
}

function metricDelta(base, target) {
  return Object.fromEntries(
    Object.keys({ ...base, ...target }).map((key) => [
      key,
      {
        base: base[key] ?? 0,
        target: target[key] ?? 0,
        delta: (target[key] ?? 0) - (base[key] ?? 0)
      }
    ])
  );
}

function summarize(rows) {
  return rows.reduce(
    (summary, row) => {
      summary.total += 1;
      summary[row.status] = (summary[row.status] ?? 0) + 1;
      return summary;
    },
    { total: 0, added: 0, changed: 0, unchanged: 0, removed: 0, errors: 0 }
  );
}

function printMarkdown(report) {
  console.log("# Snapshot Diff");
  console.log("");
  console.log(`base: ${report.base_root} (v${report.base_version})`);
  console.log(`target: ${report.target_root} (v${report.target_version})`);
  console.log(
    `summary: ${report.summary.changed} changed, ${report.summary.added} added, ${report.summary.removed} removed, ${report.summary.unchanged} unchanged, ${report.summary.errors} errors`
  );
  console.log("");
  console.log("| status | object | locale | base version | target version | events | map points | gaps |");
  console.log("| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |");
  for (const row of report.rows) {
    const metrics = row.metrics ?? {};
    console.log(
      `| ${row.status} | ${row.object_key} | ${row.locale} | ${row.base_snapshot_version ?? ""} | ${row.target_snapshot_version ?? ""} | ${formatDelta(metrics.events)} | ${formatDelta(metrics.map_points)} | ${formatDelta(metrics.coverage_gaps)} |`
    );
  }
}

function formatDelta(metric) {
  if (!metric) return "";
  const sign = metric.delta > 0 ? "+" : "";
  return `${metric.base}->${metric.target} (${sign}${metric.delta})`;
}

function stableHash(value) {
  return crypto.createHash("sha256").update(stableStringify(value)).digest("hex");
}

function stableStringify(value) {
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value)
      .sort(compareText)
      .map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function compareText(left, right) {
  return left.localeCompare(right);
}

function count(value) {
  return Array.isArray(value) ? value.length : 0;
}

function resolveManifestPath(root, manifestPath) {
  const withoutPublicPrefix = manifestPath.startsWith("public/") ? manifestPath.slice("public/".length) : manifestPath;
  return path.join(root, withoutPublicPrefix);
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

main();
