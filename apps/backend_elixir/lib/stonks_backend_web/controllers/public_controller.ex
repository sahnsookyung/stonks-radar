defmodule StonksBackendWeb.PublicController do
  use StonksBackendWeb, :controller

  alias StonksBackend.{MarketData, Providers, Snapshots, Sources, Sql}

  @disclosure_sources ["OGE", "SEC"]
  @public_search_limit 20
  @ticker_regex ~r/^[A-Za-z0-9.\-]{1,16}$/

  def health(conn, _params) do
    conn
    |> put_public_status_headers()
    |> json(%{
      status: "ok",
      service: "stonks-radar-api",
      public_read_path: "snapshot-first",
      time: DateTime.utc_now() |> DateTime.to_iso8601()
    })
  end

  def status(conn, _params) do
    manifest = Snapshots.manifest_status()
    db_snapshot_age = db_snapshot_age()

    metrics = %{
      snapshot_age_minutes: (manifest && manifest.age_minutes) || db_snapshot_age,
      published_file_snapshot_age_minutes: manifest && manifest.age_minutes,
      published_file_generated_at: manifest && manifest.generated_at,
      db_snapshot_age_minutes: db_snapshot_age,
      dead_letter_jobs:
        Sql.scalar("select count(*) from job_queue where status = 'dead_letter'", [], 0),
      quota_wait_jobs:
        Sql.scalar("select count(*) from job_queue where status = 'quota_wait'", [], 0),
      open_provider_circuits:
        Sql.scalar(
          "select count(*) from provider_runtime_state where circuit_state = 'open'",
          [],
          0
        ),
      stale_series_count:
        Sql.scalar(
          "select count(*) from latest_series_state where freshness_status = 'stale'",
          [],
          0
        ),
      conflict_count:
        Sql.scalar(
          "select count(*) from latest_series_state where conflict_present = true",
          [],
          0
        )
    }

    conn
    |> put_public_status_headers()
    |> json(%{
      status: "ok",
      public_pages_depend_on_backend: false,
      snapshot_storage: "local_oci",
      metrics: metrics
    })
  end

  def provider_status(conn, _params),
    do: conn |> put_public_status_headers() |> json(Providers.public_status())

  def snapshot_manifest_proxy(conn, _params) do
    conn
    |> put_public_status_headers()
    |> json(%{manifest_url: "/public/latest/manifest.json", mode: "local_oci"})
  end

  def trump_disclosures_summary(conn, params) do
    case parse_bounded_int(params["limit"], 50, 1, 250) do
      {:ok, limit} ->
        conn |> put_public_status_headers() |> json(Sources.disclosure_summary(limit))

      {:error, message} ->
        validation_error(conn, ["query", "limit"], message)
    end
  end

  def filings(conn, params) do
    with {:ok, validated} <- validate_disclosure_params(params, 250) do
      conn |> put_public_status_headers() |> json(Sources.filings(validated))
    else
      {:error, loc, message} -> validation_error(conn, loc, message)
    end
  end

  def transactions(conn, params) do
    with {:ok, validated} <- validate_disclosure_params(params, 500) do
      conn |> put_public_status_headers() |> json(Sources.transactions(validated))
    else
      {:error, loc, message} -> validation_error(conn, loc, message)
    end
  end

  def entity_insiders(conn, %{"ticker" => ticker} = params) do
    ticker = ticker |> to_string() |> String.trim()

    with :ok <- validate_ticker(ticker),
         {:ok, limit} <- parse_bounded_int(params["limit"], 100, 1, 500) do
      conn
      |> put_public_status_headers()
      |> json(Sources.insiders(String.upcase(ticker), limit))
    else
      {:error, message} -> validation_error(conn, ["query", "limit"], message)
      {:error, loc, message} -> validation_error(conn, loc, message)
    end
  end

  def market_history(conn, %{"symbols" => symbols, "start" => start_date, "end" => end_date}) do
    case MarketData.history(symbols, start_date, end_date) do
      {:error, :input, reason} ->
        conn
        |> put_public_status_headers()
        |> put_status(400)
        |> json(%{detail: reason})

      {:ok, payload} ->
        conn
        |> put_resp_headers(MarketData.cache_headers(payload))
        |> json(payload)
    end
  end

  def market_history(conn, _params),
    do:
      conn
      |> put_public_status_headers()
      |> put_status(400)
      |> json(%{detail: "symbols, start, and end are required"})

  def search(conn, params) when not is_map_key(params, "q") do
    validation_error(conn, ["query", "q"], "Field required")
  end

  def search(conn, %{"q" => q} = params) do
    raw_query = to_string(q)
    query = String.trim(raw_query)

    cond do
      String.length(raw_query) > 80 ->
        validation_error(conn, ["query", "q"], "String should have at most 80 characters")

      String.length(query) < 2 ->
        validation_error(conn, ["query", "q"], "String should have at least 2 characters")

      true ->
        with {:ok, limit} <-
               parse_limit_param(params["limit"], @public_search_limit, 1, @public_search_limit) do
          needle = "%#{escape_like(query)}%"

          rows =
            Sql.all(
              """
              select object_type, object_key, display_name_en, display_name_ko
              from canonical_object
              where active = true
                and (
                  display_name_en ilike $1 escape '!'
                  or display_name_ko ilike $1 escape '!'
                  or object_key ilike $1 escape '!'
                )
              order by object_type, display_name_en, object_key
              limit $2
              """,
              [needle, limit]
            )

          conn
          |> put_public_status_headers()
          |> json(%{results: Enum.map(rows, &stable_search_row/1)})
        else
          {:error, loc, message} -> validation_error(conn, loc, message)
        end
    end
  end

  defp db_snapshot_age do
    Sql.scalar(
      "select extract(epoch from now() - max(generated_at))/60 from publication_snapshot",
      [],
      0
    )
  end

  defp put_resp_headers(conn, headers),
    do: Enum.reduce(headers, conn, fn {key, value}, acc -> put_resp_header(acc, key, value) end)

  defp put_public_status_headers(conn) do
    conn
    |> put_resp_header("cache-control", "no-store")
    |> put_resp_header(
      "strict-transport-security",
      "max-age=31536000; includeSubDomains; preload"
    )
    |> put_resp_header(
      "content-security-policy",
      "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    )
    |> put_resp_header("x-content-type-options", "nosniff")
  end

  defp stable_search_row(row) do
    %{
      object_type: row["object_type"],
      object_key: row["object_key"],
      display_name_en: row["display_name_en"],
      display_name_ko: row["display_name_ko"]
    }
  end

  defp validate_disclosure_params(params, max_limit) do
    with {:ok, limit} <- parse_limit_param(params["limit"], 100, 1, max_limit),
         :ok <- validate_optional_length(params["person"], ["query", "person"], 2, 120),
         :ok <- validate_optional_ticker(params["ticker"]),
         :ok <- validate_optional_source(params["source"]) do
      {:ok,
       params
       |> Map.take(["person", "ticker", "source"])
       |> Map.put("limit", limit)
       |> normalize_disclosure_filters()}
    end
  end

  defp parse_limit_param(value, default, min_value, max_value) do
    case parse_bounded_int(value, default, min_value, max_value) do
      {:ok, limit} -> {:ok, limit}
      {:error, message} -> {:error, ["query", "limit"], message}
    end
  end

  defp normalize_disclosure_filters(params) do
    params
    |> trim_optional("person")
    |> trim_optional("ticker")
    |> trim_optional("source")
  end

  defp trim_optional(params, key) do
    case Map.get(params, key) do
      value when is_binary(value) -> Map.put(params, key, String.trim(value))
      _value -> params
    end
  end

  defp validate_optional_length(nil, _loc, _min, _max), do: :ok

  defp validate_optional_length(value, loc, min, max) do
    length = value |> to_string() |> String.trim() |> String.length()

    cond do
      length < min -> {:error, loc, "String should have at least #{min} characters"}
      length > max -> {:error, loc, "String should have at most #{max} characters"}
      true -> :ok
    end
  end

  defp validate_optional_source(nil), do: :ok
  defp validate_optional_source(""), do: :ok

  defp validate_optional_source(value) do
    source = value |> to_string() |> String.trim() |> String.upcase()

    if source in @disclosure_sources do
      :ok
    else
      {:error, ["query", "source"], "String should match OGE or SEC"}
    end
  end

  defp validate_optional_ticker(nil), do: :ok
  defp validate_optional_ticker(""), do: :ok

  defp validate_optional_ticker(value) do
    ticker = value |> to_string() |> String.trim()

    cond do
      ticker == "" -> :ok
      Regex.match?(@ticker_regex, ticker) -> :ok
      true -> {:error, ["query", "ticker"], "String should match pattern ^[A-Za-z0-9.-]{1,16}$"}
    end
  end

  defp validate_ticker(ticker) do
    if Regex.match?(@ticker_regex, ticker |> to_string() |> String.trim()) do
      :ok
    else
      {:error, ["path", "ticker"], "String should match pattern ^[A-Za-z0-9.-]{1,16}$"}
    end
  end

  defp parse_bounded_int(nil, default, _min_value, _max_value), do: {:ok, default}

  defp parse_bounded_int(value, _default, min_value, max_value) when is_integer(value),
    do: validate_int_bounds(value, min_value, max_value)

  defp parse_bounded_int(value, _default, min_value, max_value) do
    case value |> to_string() |> String.trim() |> Integer.parse() do
      {int, ""} -> validate_int_bounds(int, min_value, max_value)
      _ -> {:error, "Input should be a valid integer"}
    end
  end

  defp validate_int_bounds(value, min_value, max_value) do
    cond do
      value < min_value -> {:error, "Input should be greater than or equal to #{min_value}"}
      value > max_value -> {:error, "Input should be less than or equal to #{max_value}"}
      true -> {:ok, value}
    end
  end

  defp escape_like(value) do
    value
    |> String.replace("!", "!!")
    |> String.replace("%", "!%")
    |> String.replace("_", "!_")
  end

  defp validation_error(conn, loc, msg) do
    conn
    |> put_public_status_headers()
    |> put_status(422)
    |> json(%{
      detail: [
        %{
          loc: loc,
          msg: msg,
          type: "value_error"
        }
      ]
    })
  end
end
