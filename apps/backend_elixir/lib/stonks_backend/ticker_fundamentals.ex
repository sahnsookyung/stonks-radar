defmodule StonksBackend.TickerFundamentals do
  @moduledoc "Scheduled SEC CompanyFacts ingestion and normalized public fundamentals."

  alias StonksBackend.{Settings, Sql, TrackedTickers}
  require Logger

  @sec_base "https://data.sec.gov/api/xbrl/companyfacts"
  @forms ~w(10-K 10-Q 20-F 40-F)
  @concepts %{
    revenue: ~w(RevenueFromContractWithCustomerExcludingAssessedTax Revenues SalesRevenueNet),
    net_income: ~w(NetIncomeLoss ProfitLoss),
    operating_income: ~w(OperatingIncomeLoss),
    operating_cash_flow: ~w(NetCashProvidedByUsedInOperatingActivities),
    capital_expenditure: ~w(PaymentsToAcquirePropertyPlantAndEquipment),
    cash:
      ~w(CashAndCashEquivalentsAtCarryingValue CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents),
    debt:
      ~w(LongTermDebtAndFinanceLeaseObligationsCurrent LongTermDebtCurrent LongTermDebtNoncurrent),
    shares: ~w(EntityCommonStockSharesOutstanding)
  }

  def get(symbol) do
    symbol = normalize_symbol(symbol)

    case Sql.one(
           """
           select symbol, cik, status, coverage_reason, metrics, provenance, period_end,
                  form, filing_url, source_filed_at, fetched_at, stale_after
           from ticker_fundamental_snapshot
           where symbol = $1
           order by fetched_at desc
           limit 1
           """,
           [symbol]
         ) do
      nil -> unavailable_for(symbol)
      row -> {:ok, Map.put(row, "status", freshness_status(row))}
    end
  rescue
    _ -> {:error, :storage_unavailable}
  end

  def refresh(payload \\ %{}, opts \\ []) do
    symbols =
      case payload["symbol"] || payload[:symbol] do
        nil ->
          tracked_cik_entities()

        symbol ->
          tracked_cik_entities()
          |> Enum.filter(&(normalize_symbol(&1["symbol"]) == normalize_symbol(symbol)))
      end

    request_delay_ms =
      Keyword.get(
        opts,
        :request_delay_ms,
        if(Keyword.has_key?(opts, :request_fun), do: 0, else: 125)
      )

    delay_fun = Keyword.get(opts, :delay_fun, &Process.sleep/1)

    results =
      symbols
      |> Enum.with_index()
      |> Enum.map(fn {entity, index} ->
        if index > 0 and request_delay_ms > 0, do: delay_fun.(request_delay_ms)
        refresh_entity(entity, opts)
      end)

    {:ok,
     %{
       status: "completed",
       requested: length(symbols),
       refreshed: Enum.count(results, &match?({:ok, _}, &1)),
       unavailable: Enum.count(results, &match?({:error, _}, &1))
     }}
  end

  def normalize_company_facts(payload, symbol, cik, now \\ DateTime.utc_now())
      when is_map(payload) do
    facts = get_in(payload, ["facts", "us-gaap"]) || %{}

    values =
      Map.new(@concepts, fn {metric, concepts} ->
        {metric, latest_concept_value(facts, concepts)}
      end)

    revenue = metric_value(values.revenue)
    net_income = metric_value(values.net_income)
    operating_income = metric_value(values.operating_income)
    operating_cash_flow = metric_value(values.operating_cash_flow)
    capital_expenditure = metric_value(values.capital_expenditure)
    shares = metric_value(values.shares)

    metrics = %{
      "revenue" => revenue,
      "revenue_growth" => growth(values.revenue),
      "operating_margin" => ratio(operating_income, revenue),
      "net_margin" => ratio(net_income, revenue),
      "net_income" => net_income,
      "free_cash_flow" => subtract(operating_cash_flow, capital_expenditure),
      "cash" => metric_value(values.cash),
      "debt" => metric_value(values.debt),
      "shares" => shares,
      "dilution" => growth(values.shares),
      "valuation_ratios" => nil,
      "missing_reasons" => missing_reasons(values)
    }

    anchor =
      values.revenue.current || Enum.find_value(values, fn {_key, value} -> value.current end)

    %{
      symbol: normalize_symbol(symbol),
      cik: normalize_cik(cik),
      status: if(anchor, do: "ready", else: "unavailable"),
      coverage_reason: if(anchor, do: nil, else: "no_supported_us_gaap_companyfacts"),
      metrics: metrics,
      provenance: provenance(values),
      period_end: anchor && anchor["end"],
      form: anchor && anchor["form"],
      filing_url: anchor && filing_url(cik, anchor),
      source_filed_at: anchor && anchor["filed"],
      fetched_at: DateTime.to_iso8601(now),
      stale_after: now |> DateTime.add(7, :day) |> DateTime.to_iso8601()
    }
  end

  defp refresh_entity(entity, opts) do
    symbol = entity["symbol"]
    cik = normalize_cik(entity["sec_cik"])
    request_fun = Keyword.get(opts, :request_fun, &Req.get/2)
    url = "#{@sec_base}/CIK#{String.pad_leading(cik, 10, "0")}.json"

    case request_fun.(url,
           headers: [
             {"accept", "application/json"},
             {"user-agent", Settings.get(:sec_user_agent)}
           ],
           receive_timeout: 15_000,
           retry: false
         ) do
      {:ok, %{status: status, body: body}} when status in 200..299 and is_map(body) ->
        normalized = normalize_company_facts(body, symbol, cik)
        persist(normalized)

      {:ok, %{status: 404}} ->
        persist_unavailable(symbol, cik, "sec_companyfacts_not_found")

      _ ->
        {:error, :sec_unavailable}
    end
  end

  defp persist(snapshot) do
    result =
      Sql.execute(
        """
        insert into ticker_fundamental_snapshot(
          symbol, cik, status, coverage_reason, metrics, provenance, period_end,
          form, filing_url, source_filed_at, fetched_at, stale_after
        )
        values (
          $1, $2, $3, $4, $5::text::jsonb, $6::text::jsonb, $7::text::date,
          $8, $9, $10::text::timestamptz, $11::text::timestamptz,
          $12::text::timestamptz
        )
        """,
        [
          snapshot.symbol,
          snapshot.cik,
          snapshot.status,
          snapshot.coverage_reason,
          Jason.encode!(snapshot.metrics),
          Jason.encode!(snapshot.provenance),
          snapshot.period_end,
          snapshot.form,
          snapshot.filing_url,
          snapshot.source_filed_at,
          snapshot.fetched_at,
          snapshot.stale_after
        ]
      )

    if result.num_rows == 1, do: {:ok, snapshot.symbol}, else: {:error, :storage_unavailable}
  rescue
    error ->
      Logger.error("Ticker fundamental persistence failed symbol=#{snapshot.symbol}")
      {:error, {:storage_unavailable, error.__struct__}}
  end

  defp persist_unavailable(symbol, cik, reason) do
    now = DateTime.utc_now()

    persist(%{
      symbol: normalize_symbol(symbol),
      cik: cik,
      status: "unavailable",
      coverage_reason: reason,
      metrics: empty_metrics(reason),
      provenance: %{"source" => "SEC CompanyFacts"},
      period_end: nil,
      form: nil,
      filing_url: nil,
      source_filed_at: nil,
      fetched_at: DateTime.to_iso8601(now),
      stale_after: now |> DateTime.add(1, :day) |> DateTime.to_iso8601()
    })
  end

  defp unavailable_for(symbol) do
    entity =
      Enum.find(TrackedTickers.ticker_entities(), &(normalize_symbol(&1["symbol"]) == symbol))

    reason =
      cond do
        is_nil(entity) -> "ticker_not_tracked"
        blank?(entity["sec_cik"]) -> "issuer_has_no_compatible_sec_cik_coverage"
        true -> "fundamentals_not_ingested_yet"
      end

    {:ok,
     %{
       "symbol" => symbol,
       "status" => "unavailable",
       "coverage_reason" => reason,
       "metrics" => empty_metrics(reason),
       "provenance" => %{"source" => "SEC CompanyFacts"}
     }}
  end

  defp latest_concept_value(facts, concepts) do
    entries =
      Enum.find_value(concepts, [], fn concept ->
        units = get_in(facts, [concept, "units"]) || %{}
        values = units["USD"] || units["shares"] || []
        supported = Enum.filter(values, &(&1["form"] in @forms and not is_nil(&1["val"])))
        if supported == [], do: nil, else: Enum.map(supported, &Map.put(&1, "concept", concept))
      end)

    sorted = Enum.sort_by(entries, &{&1["filed"] || "", &1["end"] || ""}, :desc)
    %{current: Enum.at(sorted, 0), previous: comparable_previous(sorted)}
  end

  defp comparable_previous([current | rest]) do
    Enum.find(rest, fn item -> item["end"] != current["end"] and item["fp"] == current["fp"] end)
  end

  defp comparable_previous(_), do: nil
  defp metric_value(%{current: %{"val" => value}}), do: value
  defp metric_value(_), do: nil

  defp growth(%{current: %{"val" => current}, previous: %{"val" => previous}})
       when is_number(current) and is_number(previous) and previous != 0,
       do: (current - previous) / abs(previous)

  defp growth(_), do: nil

  defp ratio(value, denominator)
       when is_number(value) and is_number(denominator) and denominator != 0,
       do: value / denominator

  defp ratio(_value, _denominator), do: nil
  defp subtract(left, right) when is_number(left) and is_number(right), do: left - right
  defp subtract(_left, _right), do: nil

  defp missing_reasons(values) do
    Map.new(values, fn {key, value} ->
      {to_string(key), if(value.current, do: nil, else: "concept_not_reported")}
    end)
    |> Map.put("valuation_ratios", "market_price_not_part_of_companyfacts")
  end

  defp provenance(values) do
    %{
      "source" => "SEC CompanyFacts",
      "concepts" =>
        Map.new(values, fn {key, value} ->
          {to_string(key), value.current && value.current["concept"]}
        end)
    }
  end

  defp empty_metrics(reason) do
    %{
      "revenue" => nil,
      "revenue_growth" => nil,
      "operating_margin" => nil,
      "net_margin" => nil,
      "net_income" => nil,
      "free_cash_flow" => nil,
      "cash" => nil,
      "debt" => nil,
      "shares" => nil,
      "dilution" => nil,
      "valuation_ratios" => nil,
      "missing_reasons" => %{"all" => reason}
    }
  end

  defp filing_url(cik, %{"accn" => accession}) when is_binary(accession) do
    accession_compact = String.replace(accession, "-", "")

    "https://www.sec.gov/Archives/edgar/data/#{String.to_integer(normalize_cik(cik))}/#{accession_compact}/"
  end

  defp filing_url(_cik, _fact), do: nil

  defp freshness_status(%{"status" => "ready", "stale_after" => stale_after}) do
    case DateTime.from_iso8601(to_string(stale_after)) do
      {:ok, datetime, _} ->
        if(DateTime.compare(DateTime.utc_now(), datetime) == :gt, do: "stale", else: "ready")

      _ ->
        "stale"
    end
  end

  defp freshness_status(row), do: row["status"]

  defp tracked_cik_entities,
    do: Enum.reject(TrackedTickers.ticker_entities(), &blank?(&1["sec_cik"]))

  defp normalize_symbol(value), do: value |> to_string() |> String.trim() |> String.upcase()

  defp normalize_cik(value),
    do: value |> to_string() |> String.replace(~r/\D/, "") |> String.trim_leading("0")

  defp blank?(value), do: value |> to_string() |> String.trim() == ""
end
