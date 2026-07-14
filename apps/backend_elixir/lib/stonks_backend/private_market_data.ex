defmodule StonksBackend.PrivateMarketData do
  @moduledoc "Member-private, short-lived normalized MarketData.app reads."

  alias StonksBackend.{PrivateMarketDataCache, Settings, TickerProviderConnections}

  @symbol_regex ~r/^[A-Z0-9.\-]{1,16}$/
  @cache_ttl_ms 5 * 60 * 1_000

  def history(user_id, symbol, from_date, to_date, opts \\ []) do
    with :ok <- require_enabled(),
         {:ok, symbol} <- valid_symbol(symbol),
         {:ok, from_date} <- Date.from_iso8601(to_string(from_date)),
         {:ok, to_date} <- Date.from_iso8601(to_string(to_date)),
         true <- Date.compare(from_date, to_date) != :gt,
         {:ok, token} <- TickerProviderConnections.token_for(user_id, opts) do
      key =
        {to_string(user_id), :history,
         symbol <> ":" <> Date.to_iso8601(from_date) <> ":" <> Date.to_iso8601(to_date)}

      PrivateMarketDataCache.fetch(key, @cache_ttl_ms, fn ->
        fetch_history(token, symbol, from_date, to_date, opts)
      end)
    else
      false -> {:error, :invalid_date_range}
      error -> error
    end
  end

  def options(user_id, symbol, expiration, opts \\ []) do
    with :ok <- require_enabled(),
         {:ok, symbol} <- valid_symbol(symbol),
         {:ok, expiration} <- optional_date(expiration),
         {:ok, token} <- TickerProviderConnections.token_for(user_id, opts) do
      key = {to_string(user_id), :options, symbol <> ":" <> to_string(expiration || "nearest")}

      PrivateMarketDataCache.fetch(key, @cache_ttl_ms, fn ->
        fetch_options(token, symbol, expiration, opts)
      end)
    end
  end

  def normalize_history(payload, symbol) when is_map(payload) do
    closes = List.wrap(payload["c"] || payload["close"])
    timestamps = List.wrap(payload["t"] || payload["timestamp"])

    points =
      timestamps
      |> Enum.with_index()
      |> Enum.take(2_000)
      |> Enum.map(fn {timestamp, index} ->
        %{
          time: timestamp,
          open: at(payload["o"] || payload["open"], index),
          high: at(payload["h"] || payload["high"], index),
          low: at(payload["l"] || payload["low"], index),
          close: Enum.at(closes, index),
          volume: at(payload["v"] || payload["volume"], index)
        }
      end)

    %{
      status: "ready",
      symbol: symbol,
      delay: "provider_defined",
      as_of: List.last(timestamps),
      points: points
    }
  end

  def normalize_options(payload, symbol) when is_map(payload) do
    rows = List.wrap(payload["optionChain"] || payload["data"] || payload["options"])

    chain =
      rows
      |> Enum.filter(&is_map/1)
      |> Enum.take(500)
      |> Enum.map(fn row ->
        %{
          symbol: row["symbol"] || row["optionSymbol"],
          expiration: row["expiration"] || row["expirationDate"],
          side: row["side"] || row["type"],
          strike: row["strike"],
          bid: row["bid"],
          ask: row["ask"],
          last: row["last"] || row["lastPrice"],
          volume: row["volume"],
          open_interest: row["openInterest"] || row["open_interest"],
          implied_volatility: row["iv"] || row["impliedVolatility"],
          delta: row["delta"],
          underlying_price: row["underlyingPrice"]
        }
      end)

    %{
      status: if(chain == [], do: "empty", else: "ready"),
      symbol: symbol,
      delay: "provider_defined",
      as_of: payload["updated"] || payload["asOf"] || DateTime.to_iso8601(DateTime.utc_now()),
      chain: chain
    }
  end

  defp fetch_history(token, symbol, from_date, to_date, opts) do
    request_fun = Keyword.get(opts, :request_fun, &Req.get/2)
    base = Settings.get(:marketdata_app_base_url, "https://api.marketdata.app")

    case request_fun.("#{base}/v1/stocks/candles/D/#{URI.encode(symbol)}/",
           auth: {:bearer, token},
           params: %{from: Date.to_iso8601(from_date), to: Date.to_iso8601(to_date)},
           receive_timeout: 10_000,
           retry: false
         ) do
      {:ok, %{status: status, body: body}} when status in 200..299 and is_map(body) ->
        {:ok, normalize_history(body, symbol)}

      {:ok, %{status: 429}} ->
        {:error, :provider_quota_exceeded}

      {:ok, %{status: status}} when status in [401, 403] ->
        {:error, :provider_entitlement_required}

      _ ->
        {:error, :provider_unavailable}
    end
  end

  defp fetch_options(token, symbol, expiration, opts) do
    request_fun = Keyword.get(opts, :request_fun, &Req.get/2)
    base = Settings.get(:marketdata_app_base_url, "https://api.marketdata.app")
    params = if expiration, do: %{expiration: Date.to_iso8601(expiration)}, else: %{}

    case request_fun.("#{base}/v1/options/chain/#{URI.encode(symbol)}/",
           auth: {:bearer, token},
           params: params,
           receive_timeout: 10_000,
           retry: false
         ) do
      {:ok, %{status: status, body: body}} when status in 200..299 and is_map(body) ->
        {:ok, normalize_options(body, symbol)}

      {:ok, %{status: 429}} ->
        {:error, :provider_quota_exceeded}

      {:ok, %{status: status}} when status in [401, 403] ->
        {:error, :provider_entitlement_required}

      _ ->
        {:error, :provider_unavailable}
    end
  end

  defp require_enabled do
    if TickerProviderConnections.enabled?(), do: :ok, else: {:error, :feature_disabled}
  end

  defp valid_symbol(value) do
    symbol = value |> to_string() |> String.trim() |> String.upcase()
    if Regex.match?(@symbol_regex, symbol), do: {:ok, symbol}, else: {:error, :invalid_symbol}
  end

  defp optional_date(value) when value in [nil, ""], do: {:ok, nil}

  defp optional_date(value) do
    case Date.from_iso8601(to_string(value)) do
      {:ok, date} -> {:ok, date}
      {:error, _reason} -> {:error, :invalid_date}
    end
  end

  defp at(value, index) when is_list(value), do: Enum.at(value, index)
  defp at(_value, _index), do: nil
end
