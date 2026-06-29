defmodule StonksBackendWeb.InstrumentsController do
  use StonksBackendWeb, :controller

  alias StonksBackend.Instruments

  @contexts ["HOLDING_ENTRY", "TAX_LOT", "BUILDER", "IMPORT_RECONCILIATION", "CSV_IMPORT"]
  @instrument_id_regex ~r/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/
  @symbol_regex ~r/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/
  @listing_id_regex ~r/^[A-Za-z0-9][A-Za-z0-9._-]{0,31}:[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/

  def search(conn, params) when not is_map_key(params, "q") do
    validation_error(conn, ["query", "q"], "Field required")
  end

  def search(conn, %{"q" => _query} = params) do
    filters = normalized_search_params(params)

    with :ok <- validate_length(filters.query, ["query", "q"], 1, 64),
         :ok <- validate_optional_length(filters.country, ["query", "country"], 2, 64),
         :ok <- validate_optional_length(filters.exchange, ["query", "exchange"], 2, 32),
         :ok <- validate_optional_length(filters.asset_class, ["query", "asset_class"], 0, 64),
         :ok <-
           validate_optional_length(
             filters.instrument_type,
             ["query", "instrument_type"],
             0,
             64
           ),
         {:ok, limit} <- parse_bounded_int(filters.limit, 10, 1, 25, ["query", "limit"]),
         {:ok, include_advanced} <-
           parse_bool(filters.include_advanced, ["query", "include_advanced"]),
         {:ok, include_inactive} <-
           parse_bool(filters.include_inactive, ["query", "include_inactive"]),
         :ok <- validate_context(filters.context, ["query", "context"]) do
      conn
      |> put_public_no_store_headers()
      |> json(
        Instruments.search(filters.query,
          limit: limit,
          country: filters.country,
          exchange: filters.exchange,
          asset_class: filters.asset_class,
          instrument_type: filters.instrument_type,
          include_advanced: include_advanced,
          include_inactive: include_inactive,
          context: filters.context
        )
      )
    else
      {:error, loc, message} -> validation_error(conn, loc, message)
    end
  end

  def resolve(conn, params) do
    normalized = normalized_resolve_params(params)

    cond do
      blank?(normalized["symbol"]) ->
        validation_error(conn, ["body", "symbol"], "Field required")

      not Regex.match?(@symbol_regex, normalized["symbol"]) ->
        validation_error(
          conn,
          ["body", "symbol"],
          "String should match a supported symbol pattern"
        )

      String.length(to_string(normalized["symbol"])) > 64 ->
        validation_error(conn, ["body", "symbol"], "String should have at most 64 characters")

      present?(normalized["name"]) and String.length(to_string(normalized["name"])) > 160 ->
        validation_error(conn, ["body", "name"], "String should have at most 160 characters")

      present?(normalized["exchange"]) and String.length(to_string(normalized["exchange"])) > 32 ->
        validation_error(conn, ["body", "exchange"], "String should have at most 32 characters")

      present?(normalized["currency"]) and String.length(to_string(normalized["currency"])) != 3 ->
        validation_error(
          conn,
          ["body", "currency"],
          "String should have at least 3 and at most 3 characters"
        )

      present?(normalized["isin"]) and String.length(to_string(normalized["isin"])) > 32 ->
        validation_error(conn, ["body", "isin"], "String should have at most 32 characters")

      not context_valid?(normalized["context"]) ->
        validation_error(conn, ["body", "context"], "Input should be a valid context")

      true ->
        conn
        |> put_public_no_store_headers()
        |> json(Instruments.resolve(normalized))
    end
  end

  def detail(conn, %{"instrument_id" => id} = params) do
    with {:ok, instrument_id} <-
           validate_pattern(id, ["path", "instrument_id"], @instrument_id_regex),
         {:ok, listing_id} <- validate_optional_listing_id(params["listing_id"]) do
      case Instruments.detail(instrument_id, listing_id) do
        nil ->
          conn
          |> put_public_no_store_headers()
          |> put_status(404)
          |> json(%{detail: "Instrument not found"})

        payload ->
          conn
          |> put_public_no_store_headers()
          |> json(payload)
      end
    else
      {:error, loc, message} -> validation_error(conn, loc, message)
    end
  end

  def create_review_request(conn, params) do
    peer = conn.remote_ip |> Tuple.to_list() |> Enum.join(".")
    ip_hash = Instruments.client_identity_hash(peer)

    case Instruments.create_review_request(params, ip_hash) do
      {:ok, payload} ->
        conn
        |> put_public_no_store_headers()
        |> json(payload)

      {:error, status, payload} ->
        conn
        |> put_public_no_store_headers()
        |> put_status(status)
        |> json(payload)
    end
  end

  defp parse_bounded_int(nil, default, _min_value, _max_value, _loc), do: {:ok, default}

  defp parse_bounded_int(value, _default, min_value, max_value, loc) do
    case value |> to_string() |> String.trim() |> Integer.parse() do
      {int, ""} -> validate_int_bounds(int, min_value, max_value, loc)
      _ -> {:error, loc, "Input should be a valid integer"}
    end
  end

  defp validate_int_bounds(value, min_value, max_value, loc) do
    cond do
      value < min_value -> {:error, loc, "Input should be greater than or equal to #{min_value}"}
      value > max_value -> {:error, loc, "Input should be less than or equal to #{max_value}"}
      true -> {:ok, value}
    end
  end

  defp parse_bool(nil, _loc), do: {:ok, false}
  defp parse_bool(value, _loc) when is_boolean(value), do: {:ok, value}

  defp parse_bool(value, loc) do
    case value |> to_string() |> String.trim() |> String.downcase() do
      value when value in ["true", "1", "t", "yes", "on"] -> {:ok, true}
      value when value in ["false", "0", "f", "no", "off"] -> {:ok, false}
      _value -> {:error, loc, "Input should be a valid boolean"}
    end
  end

  defp validate_context(context, loc) do
    if context_valid?(context), do: :ok, else: {:error, loc, "Input should be a valid context"}
  end

  defp context_valid?(context), do: context in @contexts

  defp validate_optional_listing_id(nil), do: {:ok, nil}

  defp validate_optional_listing_id(value) do
    validate_pattern(value, ["query", "listing_id"], @listing_id_regex)
  end

  defp validate_pattern(value, loc, regex) do
    normalized = trim_param(value)

    cond do
      normalized == "" ->
        {:error, loc, "Field required"}

      Regex.match?(regex, normalized) ->
        {:ok, normalized}

      true ->
        {:error, loc, "String should match a supported instrument identifier pattern"}
    end
  end

  defp validate_length(value, loc, min, max) do
    length = value |> to_string() |> String.trim() |> String.length()

    cond do
      length < min -> {:error, loc, "String should have at least #{min} character"}
      length > max -> {:error, loc, "String should have at most #{max} characters"}
      true -> :ok
    end
  end

  defp validate_optional_length(nil, _loc, _min, _max), do: :ok
  defp validate_optional_length("", _loc, _min, _max), do: :ok

  defp validate_optional_length(value, loc, min, max) do
    length = value |> to_string() |> String.trim() |> String.length()

    cond do
      length < min -> {:error, loc, "String should have at least #{min} characters"}
      length > max -> {:error, loc, "String should have at most #{max} characters"}
      true -> :ok
    end
  end

  defp validation_error(conn, loc, msg) do
    conn
    |> put_public_no_store_headers()
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

  defp put_public_no_store_headers(conn), do: put_resp_header(conn, "cache-control", "no-store")

  defp normalized_search_params(params) do
    %{
      query: trim_param(params["q"]),
      country: trim_blank_to_nil(params["country"]),
      exchange: trim_blank_to_nil(params["exchange"]),
      asset_class: trim_blank_to_nil(params["asset_class"]),
      instrument_type: trim_blank_to_nil(params["instrument_type"]),
      include_advanced: params["include_advanced"],
      include_inactive: params["include_inactive"],
      limit: params["limit"],
      context: trim_blank_to_nil(params["context"]) || "HOLDING_ENTRY"
    }
  end

  defp normalized_resolve_params(params) do
    %{
      "symbol" => trim_param(params["symbol"]),
      "name" => trim_blank_to_nil(params["name"]),
      "exchange" => trim_blank_to_nil(params["exchange"]),
      "currency" => trim_blank_to_nil(params["currency"]),
      "isin" => trim_blank_to_nil(params["isin"]),
      "context" => trim_blank_to_nil(params["context"]) || "CSV_IMPORT"
    }
  end

  defp trim_blank_to_nil(value) do
    case trim_param(value) do
      "" -> nil
      trimmed -> trimmed
    end
  end

  defp trim_param(nil), do: ""
  defp trim_param(value), do: value |> to_string() |> String.trim()

  defp blank?(nil), do: true
  defp blank?(value) when is_binary(value), do: String.trim(value) == ""
  defp blank?(_value), do: false

  defp present?(value), do: not blank?(value)
end
