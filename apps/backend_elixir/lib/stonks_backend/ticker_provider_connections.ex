defmodule StonksBackend.TickerProviderConnections do
  @moduledoc "Encrypted member-owned private provider connections."

  alias StonksBackend.Accounts.CredentialCipher
  alias StonksBackend.{PrivateMarketDataCache, Settings, Sql}

  @provider "marketdata_app"

  def connect(user_id, token, opts \\ []) do
    verify_fun = Keyword.get(opts, :verify_fun, &verify_token/1)

    with true <- is_binary(token) and byte_size(String.trim(token)) in 8..4096,
         {:ok, verification} <- verify_fun.(String.trim(token)),
         {:ok, encrypted} <- CredentialCipher.encrypt(String.trim(token), opts) do
      row =
        Sql.one(
          """
          insert into user_provider_connection(
            user_id, provider_key, token_ciphertext, token_nonce, key_version,
            verification_status, verified_at, verification_metadata
          )
          values ($1, $2, $3, $4, $5, 'verified', now(), $6::jsonb)
          on conflict (user_id, provider_key) do update set
            token_ciphertext = excluded.token_ciphertext,
            token_nonce = excluded.token_nonce,
            key_version = excluded.key_version,
            verification_status = 'verified',
            verified_at = now(),
            verification_metadata = excluded.verification_metadata,
            updated_at = now()
          returning provider_key, verification_status, verified_at, updated_at
          """,
          [
            user_id,
            @provider,
            encrypted.ciphertext,
            encrypted.nonce,
            encrypted.key_version,
            Jason.encode!(Map.take(verification, [:entitlement, :delay, :quota]))
          ]
        )

      if row, do: {:ok, public_connection(row)}, else: {:error, :storage_unavailable}
    else
      false -> {:error, :invalid_credential}
      error -> error
    end
  end

  def status(user_id) do
    row =
      Sql.one(
        """
        select provider_key, verification_status, verified_at, updated_at
        from user_provider_connection
        where user_id = $1 and provider_key = $2
        """,
        [user_id, @provider]
      )

    if row, do: {:ok, public_connection(row)}, else: {:error, :not_connected}
  end

  def token_for(user_id, opts \\ []) do
    row =
      Sql.one(
        """
        select token_ciphertext, token_nonce, verification_status
        from user_provider_connection
        where user_id = $1 and provider_key = $2
        """,
        [user_id, @provider]
      )

    cond do
      is_nil(row) -> {:error, :not_connected}
      row["verification_status"] != "verified" -> {:error, :not_verified}
      true -> CredentialCipher.decrypt(row["token_ciphertext"], row["token_nonce"], opts)
    end
  end

  def delete(user_id) do
    Sql.execute(
      "delete from user_provider_connection where user_id = $1 and provider_key = $2",
      [user_id, @provider]
    )

    PrivateMarketDataCache.delete_user(user_id)
    :ok
  rescue
    _ -> {:error, :storage_unavailable}
  end

  def enabled? do
    Settings.truthy?(Settings.get(:ticker_private_market_data_enabled, "false"))
  end

  def verify_token(token) do
    url =
      Settings.get(
        :marketdata_app_verify_url,
        "https://api.marketdata.app/v1/stocks/quotes/AAPL/"
      )

    case Req.get(url,
           auth: {:bearer, token},
           headers: [{"accept", "application/json"}],
           receive_timeout: 8_000,
           retry: false
         ) do
      {:ok, %{status: status}} when status in 200..299 ->
        {:ok,
         %{entitlement: "delegated_private", delay: "provider_defined", quota: "provider_owned"}}

      {:ok, %{status: 401}} ->
        {:error, :invalid_credential}

      {:ok, %{status: 403}} ->
        {:error, :provider_entitlement_required}

      {:ok, %{status: 429}} ->
        {:error, :provider_quota_exceeded}

      _ ->
        {:error, :provider_unavailable}
    end
  end

  defp public_connection(row) do
    %{
      provider: row["provider_key"],
      status: row["verification_status"],
      verified_at: row["verified_at"],
      updated_at: row["updated_at"]
    }
  end
end
