import fundLinksJson from "../../../../packages/shared-config/fund-links.json";

export type FundLinkEntry = {
  key: string;
  human_name: string;
  fund_name: string;
  primary_url: string;
  source_label: string;
  note: string;
};

export const fundLinks = validateFundLinks(fundLinksJson as unknown);

export function getFundLinkByKey(key: string) {
  return fundLinks.find((entry) => entry.key === key);
}

export function validateFundLinks(value: unknown): FundLinkEntry[] {
  if (!Array.isArray(value)) {
    throw new Error("fund links registry must be an array");
  }

  const seen = new Set<string>();
  return value.map((entry, index) => {
    if (!isRecord(entry)) {
      throw new Error(`fund links entry ${index} must be an object`);
    }

    const parsed = {
      key: requiredString(entry, "key", index),
      human_name: requiredString(entry, "human_name", index),
      fund_name: requiredString(entry, "fund_name", index),
      primary_url: requiredString(entry, "primary_url", index),
      source_label: requiredString(entry, "source_label", index),
      note: requiredString(entry, "note", index),
    };

    if (!/^[a-z0-9-]+$/.test(parsed.key)) {
      throw new Error(`fund links entry ${index} has invalid key`);
    }
    if (seen.has(parsed.key)) {
      throw new Error(`fund links registry has duplicate key ${parsed.key}`);
    }
    seen.add(parsed.key);

    try {
      const url = new URL(parsed.primary_url);
      if (url.protocol !== "https:") {
        throw new Error("non-https URL");
      }
    } catch {
      throw new Error(`fund links entry ${index} has invalid primary_url`);
    }

    return parsed;
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requiredString(entry: Record<string, unknown>, key: keyof FundLinkEntry, index: number) {
  const value = entry[key];
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new Error(`fund links entry ${index} is missing ${key}`);
  }
  return value.trim();
}
