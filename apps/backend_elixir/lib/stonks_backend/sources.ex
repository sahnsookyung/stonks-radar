defmodule StonksBackend.Sources do
  @moduledoc "Source ingestion/disclosure placeholders over preserved tables."

  alias StonksBackend.Sql

  @legal_use_warning "OGE public financial disclosure reports may not be obtained or used for unlawful purposes, commercial purposes other than news/media dissemination to the public, credit-rating purposes, or solicitation purposes."
  @disclosure_limitations [
    "This is a source-linked public disclosure database, not a copy-trading signal.",
    "OGE data is delayed; Form 278-T may be filed up to 45 days after a transaction.",
    "OGE values are amount ranges, not exact trade sizes.",
    "OGE covers Donald J. Trump, spouse, and dependent-child transactions only where reportable in his filings.",
    "Adult family members are tracked only when they appear in SEC filings or issuer disclosures.",
    "SEC Form 144 is proposed sale intent, not proof the sale occurred.",
    "Schedule 13D/G is large beneficial ownership disclosure, not every trade.",
    "Ticker extraction from PDFs can be wrong; every row links back to the source filing."
  ]
  @public_transaction_min_confidence 0.9

  def sources, do: Sql.all("select * from data_source order by source_key")

  def create_source(payload) do
    Sql.scalar(
      """
      insert into data_source(source_key, display_name, source_type, base_url)
      values ($1, $2, $3, $4)
      returning id
      """,
      [
        payload["source_key"],
        payload["display_name"],
        payload["source_type"],
        payload["base_url"]
      ]
    )
  end

  def source_document(id), do: Sql.one("select * from source_document where id = $1", [id])

  def ingest_url(_payload),
    do: {:error, "safe_fetch_ingestion_not_enabled_until_fetch_sandbox_contract_is_configured"}

  def ingest_disclosures(payload),
    do: {:ok, %{status: "queued_disclosure_ingest", payload: payload}}

  def filings(params) do
    limit = parse_limit(params["limit"], 100, 250)
    {conditions, values} = disclosure_filters("sf", params, [])
    limit_index = length(values) + 1

    rows =
      Sql.all(
        """
        select sf.*,
               (select count(*) from security_transactions st where st.filing_id = sf.id) as transaction_count
        from source_filings sf
        where #{Enum.join(conditions, " and ")}
        order by coalesce(sf.doc_date, cast(sf.created_at as date)) desc, sf.id desc
        limit $#{limit_index}
        """,
        values ++ [limit]
      )

    %{filings: rows, limitations: @disclosure_limitations}
  end

  def transactions(params) do
    limit = parse_limit(params["limit"], 100, 500)

    base_conditions = [
      "coalesce(st.confidence, 0) >= $1",
      "(st.source <> 'OGE' or st.ticker is not null)"
    ]

    base_values = [@public_transaction_min_confidence]
    {conditions, values} = disclosure_filters("st", params, {base_conditions, base_values})
    limit_index = length(values) + 1

    rows =
      Sql.all(
        """
        select st.*, sf.source_url, sf.form_type, sf.filed_at, sf.doc_date
        from security_transactions st
        join source_filings sf on sf.id = st.filing_id
        where #{Enum.join(conditions, " and ")}
        order by st.transaction_date desc nulls last, sf.doc_date desc nulls last, st.id desc
        limit $#{limit_index}
        """,
        values ++ [limit]
      )

    %{
      transactions: rows,
      limitations: @disclosure_limitations,
      min_confidence: @public_transaction_min_confidence
    }
  end

  def insiders(ticker, limit) do
    payload =
      transactions(%{
        "ticker" => ticker,
        "source" => "SEC",
        "limit" => limit
      })

    insiders =
      payload.transactions
      |> Enum.reduce(%{}, fn row, owners ->
        owner = row["owner_name"] || row["person_name"] || "Unknown owner"

        current =
          Map.get(owners, owner, %{
            "owner_name" => owner,
            "transactions" => 0,
            "latest_transaction_date" => nil
          })

        latest = latest_date(current["latest_transaction_date"], row["transaction_date"])

        Map.put(owners, owner, %{
          "owner_name" => owner,
          "transactions" => current["transactions"] + 1,
          "latest_transaction_date" => latest
        })
      end)
      |> Map.values()
      |> Enum.sort_by(&{&1["latest_transaction_date"] || "", &1["owner_name"]}, :desc)

    payload
    |> Map.put(:ticker, ticker |> to_string() |> String.upcase())
    |> Map.put(:insiders, insiders)
  end

  def disclosure_summary(limit) do
    limit = parse_limit(limit, 50, 250)

    %{
      legal_use_warning: @legal_use_warning,
      limitations: @disclosure_limitations,
      filings: filings(%{"limit" => limit}).filings,
      transactions: transactions(%{"limit" => limit}).transactions,
      watched_people: watched_people(),
      open_review_items:
        Sql.scalar("select count(*) from parse_review_queue where status = 'open'", [], 0)
    }
  end

  defp disclosure_filters(alias_name, params, initial) when is_map(params) do
    {conditions, values} = normalize_initial_filters(initial)

    {conditions, values}
    |> add_source_filter(alias_name, params["source"])
    |> add_ticker_filter(alias_name, params["ticker"])
    |> add_person_filter(alias_name, params["person"])
  end

  defp disclosure_filters(_alias_name, _params, initial), do: normalize_initial_filters(initial)

  defp normalize_initial_filters([]), do: {["true"], []}
  defp normalize_initial_filters({conditions, values}), do: {conditions, values}

  defp add_source_filter(filters, _alias_name, nil), do: filters
  defp add_source_filter(filters, _alias_name, ""), do: filters

  defp add_source_filter({conditions, values}, alias_name, source) do
    source = source |> to_string() |> String.upcase()
    add_condition({conditions, values}, "#{alias_name}.source = $IDX", source)
  end

  defp add_ticker_filter(filters, _alias_name, nil), do: filters
  defp add_ticker_filter(filters, _alias_name, ""), do: filters

  defp add_ticker_filter({conditions, values}, alias_name, ticker) do
    add_condition(
      {conditions, values},
      "upper(#{alias_name}.ticker) = $IDX",
      ticker |> to_string() |> String.upcase()
    )
  end

  defp add_person_filter(filters, _alias_name, nil), do: filters
  defp add_person_filter(filters, _alias_name, ""), do: filters

  defp add_person_filter({conditions, values}, "sf", person) do
    condition = """
    (
      sf.filer_name ilike $IDX escape '!'
      or exists (
        select 1 from security_transactions st
        where st.filing_id = sf.id
          and (st.person_name ilike $IDX escape '!' or st.owner_name ilike $IDX escape '!')
      )
    )
    """

    add_condition({conditions, values}, condition, "%#{escape_like(person)}%")
  end

  defp add_person_filter({conditions, values}, alias_name, person) do
    add_condition(
      {conditions, values},
      "(#{alias_name}.person_name ilike $IDX escape '!' or #{alias_name}.owner_name ilike $IDX escape '!')",
      "%#{escape_like(person)}%"
    )
  end

  defp add_condition({conditions, values}, condition, value) do
    index = length(values) + 1
    {[String.replace(condition, "$IDX", "$#{index}") | conditions], values ++ [value]}
  end

  defp watched_people do
    Sql.all("""
    select canonical_name, category, aliases, tickers, sec_ciks, oge_names, notes
    from watched_people
    order by
      case category
        when 'donald_trump' then 1
        when 'spouse' then 2
        when 'dependent_child' then 3
        when 'adult_family' then 4
        else 5
      end,
      canonical_name
    """)
  end

  defp latest_date(nil, candidate), do: candidate
  defp latest_date(current, nil), do: current
  defp latest_date(current, candidate) when candidate > current, do: candidate
  defp latest_date(current, _candidate), do: current

  defp parse_limit(value, default, max_value) do
    value
    |> parse_int(default)
    |> max(1)
    |> min(max_value)
  end

  defp parse_int(value, _default) when is_integer(value), do: value

  defp parse_int(value, default) do
    case Integer.parse(to_string(value || default)) do
      {parsed, ""} -> parsed
      _ -> default
    end
  end

  defp escape_like(value) do
    value
    |> to_string()
    |> String.replace("!", "!!")
    |> String.replace("%", "!%")
    |> String.replace("_", "!_")
  end
end
