defmodule StonksBackend.News.EmailAlerts do
  @moduledoc "Signed email alert compatibility boundary."

  alias StonksBackend.Settings

  def verify(headers, body) do
    secret = Settings.get(:news_email_webhook_secret)

    cond do
      not Settings.present?(secret) ->
        {:error, "email_webhook_disabled"}

      missing_signature?(headers) ->
        {:error, "missing_signature_headers"}

      stale?(headers) ->
        {:error, "stale_signature"}

      valid_signature?(headers, body, secret) ->
        :ok

      true ->
        {:error, "invalid_signature"}
    end
  end

  def ingest(payload), do: %{status: "accepted", payload_hash: hash(Jason.encode!(payload))}

  defp missing_signature?(headers),
    do:
      is_nil(header(headers, "x-stonks-email-signature")) or
        is_nil(header(headers, "x-stonks-timestamp"))

  defp stale?(headers) do
    max_skew = Settings.get(:news_email_signature_max_skew_seconds, "300") |> String.to_integer()

    case Integer.parse(header(headers, "x-stonks-timestamp") || "") do
      {timestamp, ""} -> abs(System.system_time(:second) - timestamp) > max_skew
      _ -> true
    end
  end

  defp valid_signature?(headers, body, secret) do
    timestamp = header(headers, "x-stonks-timestamp")
    nonce = header(headers, "x-stonks-nonce") || ""

    expected =
      :crypto.mac(:hmac, :sha256, secret, "#{timestamp}.#{nonce}." <> body)
      |> Base.encode16(case: :lower)

    Plug.Crypto.secure_compare(expected, header(headers, "x-stonks-email-signature") || "")
  end

  defp header(headers, key), do: Map.get(headers, key) || Map.get(headers, String.downcase(key))
  defp hash(value), do: :crypto.hash(:sha256, value) |> Base.encode16(case: :lower)
end
