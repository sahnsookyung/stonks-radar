#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import process from "node:process";

const coreObjects = ["home", "map_events", "news_index"];

function main() {
  const options = parseArgs(process.argv.slice(2));
  const root = path.resolve(options.root ?? "apps/web/public/public");
  const manifest = readJson(path.join(root, "latest", "manifest.json"));
  const locales = Array.isArray(manifest.locales) ? manifest.locales : ["en", "ko"];
  const rows = [];
  const warnings = [];

  for (const objectKey of coreObjects) {
    for (const locale of locales) {
      const manifestPath = manifest.objects?.[objectKey]?.[locale];
      if (!manifestPath) {
        warnings.push(`${objectKey}/${locale} missing from latest manifest`);
        continue;
      }
      const snapshotPath = resolveManifestPath(root, manifestPath);
      const snapshot = readJson(snapshotPath);
      const row = summarizeSnapshot(objectKey, locale, manifestPath, snapshot);
      rows.push(row);
      warnings.push(...contractWarnings(row, snapshot));
    }
  }

  const report = {
    root,
    current_version: manifest.current_version,
    generated_at: manifest.generated_at,
    rows,
    warnings
  };

  if (options.json) {
    console.log(JSON.stringify(report, null, 2));
  } else {
    printMarkdown(report);
  }

  if (warnings.length > 0 && options.strict) {
    process.exitCode = 1;
  }
}

function parseArgs(args) {
  const options = { json: false, strict: false, root: undefined };
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (arg === "--json") options.json = true;
    else if (arg === "--strict") options.strict = true;
    else if (arg === "--root") options.root = args[++index];
    else if (options.root === undefined) options.root = arg;
    else throw new Error(`Unexpected argument: ${arg}`);
  }
  return options;
}

function summarizeSnapshot(objectKey, locale, manifestPath, snapshot) {
  const data = snapshot.data ?? {};
  const breakingMap = data.breaking_market_map ?? {};
  const filters = data.filters ?? {};
  return {
    object_key: objectKey,
    locale,
    manifest_path: manifestPath,
    object_type: snapshot.object_type,
    snapshot_version: snapshot.snapshot_version,
    generated_at: snapshot.generated_at,
    hard_expires_at: snapshot.hard_expires_at,
    content_hash: snapshot.content_hash,
    event_count: count(data.events),
    news_event_count: count(data.events),
    breaking_event_count: count(data.breaking_market_events ?? breakingMap.events),
    map_point_count: count(breakingMap.map_points),
    coverage_gap_count: count(breakingMap.coverage_gaps),
    regional_brief_count: count(breakingMap.regional_briefs),
    filter_count: countObjectArrays(filters)
  };
}

function contractWarnings(row, snapshot) {
  const warnings = [];
  if (row.object_type !== objectTypeForKey(row.object_key)) {
    warnings.push(`${row.object_key}/${row.locale} object_type is ${row.object_type}`);
  }
  if (!String(row.content_hash ?? "").startsWith("sha256:")) {
    warnings.push(`${row.object_key}/${row.locale} content_hash missing sha256 prefix`);
  }
  if (row.object_key === "map_events") {
    if (row.map_point_count === 0) warnings.push(`${row.object_key}/${row.locale} has no map_points`);
    if (row.coverage_gap_count === 0) warnings.push(`${row.object_key}/${row.locale} has no coverage_gaps`);
    if (row.regional_brief_count === 0) warnings.push(`${row.object_key}/${row.locale} has no regional_briefs`);
    if (!Array.isArray(snapshot.data?.filters?.severities)) {
      warnings.push(`${row.object_key}/${row.locale} filters.severities is missing`);
    }
  }
  if (row.object_key === "news_index" && row.news_event_count === 0) {
    warnings.push(`${row.object_key}/${row.locale} has no news events`);
  }
  if (row.object_key === "home" && row.breaking_event_count === 0) {
    warnings.push(`${row.object_key}/${row.locale} has no breaking_market_events`);
  }
  return warnings;
}

function printMarkdown(report) {
  console.log(`# Snapshot Contract Report`);
  console.log("");
  console.log(`root: ${report.root}`);
  console.log(`version: ${report.current_version}`);
  console.log(`generated_at: ${report.generated_at}`);
  console.log("");
  console.log("| object | locale | version | events | breaking | map points | gaps | briefs | filters |");
  console.log("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |");
  for (const row of report.rows) {
    console.log(
      `| ${row.object_key} | ${row.locale} | ${row.snapshot_version} | ${row.event_count} | ${row.breaking_event_count} | ${row.map_point_count} | ${row.coverage_gap_count} | ${row.regional_brief_count} | ${row.filter_count} |`
    );
  }
  if (report.warnings.length > 0) {
    console.log("");
    console.log("Warnings:");
    for (const warning of report.warnings) console.log(`- ${warning}`);
  }
}

function objectTypeForKey(objectKey) {
  if (objectKey === "news_index") return "news_index";
  if (objectKey === "map_events") return "map_events";
  return "home";
}

function count(value) {
  return Array.isArray(value) ? value.length : 0;
}

function countObjectArrays(value) {
  if (!value || typeof value !== "object") return 0;
  return Object.values(value).reduce((sum, item) => sum + count(item), 0);
}

function resolveManifestPath(root, manifestPath) {
  const withoutPublicPrefix = manifestPath.startsWith("public/") ? manifestPath.slice("public/".length) : manifestPath;
  return path.join(root, withoutPublicPrefix);
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

main();
