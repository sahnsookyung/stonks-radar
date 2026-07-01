import { describe, expect, it } from "vitest";
import {
  disclosureTransactionBucket,
  disclosureTransactionCaveat,
  disclosureTransactionLabel
} from "./disclosureLabels";

describe("disclosure transaction labels", () => {
  it("labels Form 144 notices as sale intent instead of executed sales", () => {
    const transaction = { source: "SEC", form_type: "144", transaction_code: "S" };

    expect(disclosureTransactionLabel(transaction, "en")).toBe("Form 144 sale intent");
    expect(disclosureTransactionLabel(transaction, "ko")).toBe("Form 144 매도 의향");
    expect(disclosureTransactionBucket(transaction, "en")).toBe("sale intent");
    expect(disclosureTransactionCaveat(transaction, "en")).toBe("Proposed sale notice, not proof of execution.");
  });

  it("uses form-code labels, buckets, and caveats for reported transaction codes", () => {
    expect(disclosureTransactionLabel({ transaction_code: " p " }, "en")).toBe("Market purchase");
    expect(disclosureTransactionBucket({ transaction_code: "S" }, "en")).toBe("market trade");
    expect(disclosureTransactionBucket({ transaction_code: "F" }, "ko")).toBe("행정/보상");
    expect(disclosureTransactionCaveat({ transaction_code: "F" }, "en")).toBe(
      "Tax withholding, not a normal open-market sale."
    );
    expect(disclosureTransactionCaveat({ transaction_code: "A" }, "en")).toBe(
      "Do not read as a simple buy/sell signal."
    );
  });

  it("falls back to source-provided transaction text and generic reported labels", () => {
    expect(disclosureTransactionLabel({ transaction_type: "Issuer reported correction" }, "en")).toBe(
      "Issuer reported correction"
    );
    expect(disclosureTransactionLabel({ transaction_code: "Z" }, "ko")).toBe("Z");
    expect(disclosureTransactionLabel({}, "en")).toBe("reported");
    expect(disclosureTransactionBucket({}, "ko")).toBe("신고");
    expect(disclosureTransactionCaveat({}, "en")).toBe("");
  });
});
