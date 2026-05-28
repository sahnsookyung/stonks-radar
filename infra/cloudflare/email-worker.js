export default {
  async email(message, env, ctx) {
    const allowedRecipients = splitList(env.NEWS_EMAIL_ALLOWED_RECIPIENTS || "");
    const to = String(message.to || "").toLowerCase();
    if (allowedRecipients.length && !allowedRecipients.includes(to)) {
      message.setReject("Recipient is not accepted by Stonks Radar.");
      return;
    }
    if (!env.NEWS_EMAIL_WEBHOOK_URL || !env.NEWS_EMAIL_WEBHOOK_SECRET) {
      message.setReject("Email webhook is not configured.");
      return;
    }
    const maxBytes = Number(env.NEWS_EMAIL_MAX_RAW_BYTES || 1048576);
    const rawBytes = new Uint8Array(await new Response(message.raw).arrayBuffer());
    if (rawBytes.byteLength > maxBytes) {
      message.setReject("Email exceeds the Stonks Radar ingestion size limit.");
      return;
    }

    const body = JSON.stringify({
      to,
      from: message.from || "",
      envelope_from: message.headers.get("return-path") || message.from || "",
      subject: message.headers.get("subject") || "",
      message_id: message.headers.get("message-id") || "",
      received_at: new Date().toISOString(),
      auth_results: {
        authentication_results: message.headers.get("authentication-results") || "",
        dkim_signature: message.headers.get("dkim-signature") ? "present" : "absent",
      },
      raw_base64: bytesToBase64(rawBytes),
    });

    const timestamp = String(Math.floor(Date.now() / 1000));
    const nonce = crypto.randomUUID();
    const signature = await hmacSha256(env.NEWS_EMAIL_WEBHOOK_SECRET, `${timestamp}.${nonce}.${body}`);
    let webhookResponse;
    try {
      webhookResponse = await fetch(env.NEWS_EMAIL_WEBHOOK_URL, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-stonks-timestamp": timestamp,
          "x-stonks-nonce": nonce,
          "x-stonks-email-signature": `sha256=${signature}`,
        },
        body,
      });
    } catch {
      message.setReject("Stonks Radar email webhook could not be reached.");
      return;
    }
    if (!webhookResponse.ok) {
      message.setReject(`Stonks Radar email webhook failed: ${webhookResponse.status}`);
      return;
    }

    if (env.NEWS_EMAIL_FORWARD_TO) {
      ctx.waitUntil(message.forward(env.NEWS_EMAIL_FORWARD_TO));
    }
  },
};

function splitList(value) {
  return value
    .split(",")
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean);
}

async function hmacSha256(secret, value) {
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    enc.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const digest = await crypto.subtle.sign("HMAC", key, enc.encode(value));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function bytesToBase64(bytes) {
  let binary = "";
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
  }
  return btoa(binary);
}
