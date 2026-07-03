defmodule StonksBackend.News.EmailAlerts do
  @moduledoc "Signed email alert compatibility boundary."

  alias StonksBackend.{Settings, Sql}

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
        record_nonce(headers)

      true ->
        {:error, "invalid_signature"}
    end
  end

  def ingest(payload), do: %{status: "accepted", payload_hash: hash(Jason.encode!(payload))}

  defp missing_signature?(headers),
    do:
      is_nil(header(headers, "x-stonks-email-signature")) or
        is_nil(header(headers, "x-stonks-timestamp")) or
        is_nil(header(headers, "x-stonks-nonce"))

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
    actual = signature_value(headers)

    expected =
      :crypto.mac(:hmac, :sha256, secret, "#{timestamp}.#{nonce}." <> body)
      |> Base.encode16(case: :lower)

    byte_size(actual) == byte_size(expected) and Plug.Crypto.secure_compare(expected, actual)
  end

  defp record_nonce(headers) do
    nonce = header(headers, "x-stonks-nonce") |> to_string()
    nonce_store = Settings.get(:news_email_nonce_store, &record_nonce_in_db/1)
    nonce_store.(nonce)
  end

  defp record_nonce_in_db(nonce) do
    purge_old_nonces()

    case Sql.scalar(
           """
           insert into news_email_webhook_nonce(nonce)
           values ($1)
           on conflict (nonce) do nothing
           returning nonce
           """,
           [nonce]
         ) do
      nil -> {:error, "replayed_signature_nonce"}
      _ -> :ok
    end
  rescue
    _ -> {:error, "email_webhook_nonce_store_unavailable"}
  end

  defp purge_old_nonces do
    max_skew = Settings.get(:news_email_signature_max_skew_seconds, "300") |> String.to_integer()
    retention_seconds = max(max_skew * 2, 600)

    Sql.execute(
      """
      delete from news_email_webhook_nonce
      where received_at < now() - ($1::int * interval '1 second')
      """,
      [retention_seconds]
    )
  end

  defp signature_value(headers) do
    headers
    |> header("x-stonks-email-signature")
    |> to_string()
    |> String.trim()
    |> String.downcase()
    |> String.replace_prefix("sha256=", "")
  end

  defp header(headers, key), do: Map.get(headers, key) || Map.get(headers, String.downcase(key))
  defp hash(value), do: :crypto.hash(:sha256, value) |> Base.encode16(case: :lower)
end
