defmodule StonksBackend.TrackedTickers do
  @moduledoc """
  Shared access to the configured tracked ticker universe.

  The JSON watchlist is the source of truth; this module keeps backend search,
  news filters, source ingestion, and instrument indexing from inventing
  independent ticker lists.
  """

  alias StonksBackend.Settings

  @repo_root Path.expand(Path.join(__DIR__, "../../../.."))

  def payload do
    watchlist_path_candidates()
    |> Enum.find_value(&read_watchlist_payload/1)
    |> case do
      nil -> {:error, :watchlist_missing}
      result -> {:ok, result}
    end
  end

  def entities do
    case payload() do
      {:ok, %{"entities" => entities}} when is_list(entities) -> entities
      _ -> []
    end
  end

  def ticker_entities do
    entities()
    |> Enum.filter(&(Map.get(&1, "route_kind") == "ticker"))
  end

  def ticker_filter_options(event_counts \\ %{}, label_overrides \\ %{}) do
    ticker_entities()
    |> Enum.map(fn entity ->
      key = entity["symbol"] || entity["display_symbol"]

      %{
        "key" => key,
        "label" => label_overrides[key] || entity["name_en"] || entity["legal_name"] || key,
        "count" => Map.get(event_counts, key, 0)
      }
    end)
    |> Enum.reject(&(to_string(&1["key"]) == ""))
    |> Enum.uniq_by(& &1["key"])
    |> Enum.sort_by(&{-to_int(&1["count"], 0), &1["key"]})
  end

  def gdelt_terms do
    ticker_entities()
    |> Enum.flat_map(&gdelt_terms_for_entity/1)
    |> Enum.uniq()
  end

  def ticker_profiles do
    ticker_entities()
    |> Enum.map(fn entity ->
      %{
        symbol: entity["symbol"] || entity["display_symbol"],
        legal_name: entity["legal_name"],
        name: entity["name_en"],
        aliases: List.wrap(entity["aliases"]),
        official_domains: List.wrap(entity["official_domains"]),
        topics: List.wrap(entity["topics"]) ++ List.wrap(entity["theme_keys"])
      }
    end)
  end

  def source_issues do
    ticker_entities()
    |> Enum.flat_map(&source_issues_for_entity/1)
  end

  defp gdelt_terms_for_entity(entity) do
    [
      entity["symbol"],
      entity["display_symbol"],
      entity["legal_name"],
      entity["name_en"],
      entity["name_ko"]
    ]
    |> Kernel.++(List.wrap(entity["aliases"]))
    |> Enum.map(&gdelt_term/1)
    |> Enum.reject(&(&1 == ""))
    |> Enum.uniq()
  end

  defp gdelt_term(value) do
    value =
      value
      |> to_string()
      |> String.replace(~r/["]/, " ")
      |> String.replace(~r/\s+/, " ")
      |> String.trim()

    cond do
      value == "" -> ""
      String.contains?(value, " ") -> ~s|"#{value}"|
      true -> value
    end
  end

  defp source_issues_for_entity(entity) do
    symbol = entity["symbol"] || entity["display_symbol"] || entity["entity_id"] || "unknown"

    [
      missing_issue(symbol, "symbol", entity["symbol"]),
      missing_issue(symbol, "tradingview_symbol", entity["tradingview_symbol"]),
      placeholder_issue(symbol, "name_en", entity["name_en"]),
      placeholder_issue(symbol, "legal_name", entity["legal_name"]),
      source_list_issue(symbol, entity["sources"])
    ]
    |> List.flatten()
    |> Enum.reject(&is_nil/1)
  end

  defp missing_issue(symbol, field, value) do
    if blank?(value), do: %{symbol: symbol, field: field, issue: "missing"}, else: nil
  end

  defp placeholder_issue(symbol, field, value) do
    value = to_string(value)

    if Regex.match?(~r/(placeholder|sample|demo|mock)/i, value) do
      %{symbol: symbol, field: field, issue: "placeholder_value"}
    end
  end

  defp source_list_issue(symbol, sources) when is_list(sources) and sources != [] do
    sources
    |> Enum.with_index()
    |> Enum.flat_map(fn {source, index} ->
      [
        missing_issue(symbol, "sources[#{index}].source_key", source["source_key"]),
        missing_issue(symbol, "sources[#{index}].source_name", source["source_name"]),
        url_issue(symbol, "sources[#{index}].base_url", source["base_url"]),
        url_issue(symbol, "sources[#{index}].feed_url", source["feed_url"])
      ]
    end)
  end

  defp source_list_issue(symbol, _sources),
    do: [%{symbol: symbol, field: "sources", issue: "missing"}]

  defp url_issue(_symbol, _field, value) when value in [nil, ""], do: nil

  defp url_issue(symbol, field, value) do
    value = to_string(value)

    if String.starts_with?(value, ["https://", "http://"]) do
      nil
    else
      %{symbol: symbol, field: field, issue: "invalid_url"}
    end
  end

  defp read_watchlist_payload(nil), do: nil

  defp read_watchlist_payload(path) do
    if File.regular?(path) do
      with {:ok, content} <- File.read(path),
           {:ok, %{"entities" => entities} = payload} when is_list(entities) <-
             Jason.decode(content) do
        payload
      else
        _ -> nil
      end
    end
  end

  defp watchlist_path_candidates do
    [
      Settings.get(:news_ticker_watchlist_path),
      app_priv_path("ticker_watchlist.generated.json"),
      app_priv_path("tracked_entities.json"),
      Path.join(@repo_root, "packages/shared-config/ticker-watchlist.generated.json"),
      Path.expand("packages/shared-config/ticker-watchlist.generated.json", File.cwd!()),
      Path.expand("../../packages/shared-config/ticker-watchlist.generated.json", File.cwd!()),
      Path.expand("../config/tracked_entities.json", File.cwd!()),
      Path.expand("../../config/tracked_entities.json", File.cwd!())
    ]
    |> Enum.reject(&blank?/1)
    |> Enum.uniq()
  end

  defp app_priv_path(filename) do
    Application.app_dir(:stonks_backend, Path.join(["priv", "news_sources", filename]))
  rescue
    _ -> nil
  end

  defp blank?(value), do: value |> to_string() |> String.trim() == ""

  defp to_int(value, _default) when is_integer(value), do: value

  defp to_int(value, default) do
    case Integer.parse(to_string(value)) do
      {integer, _} -> integer
      _ -> default
    end
  end
end
