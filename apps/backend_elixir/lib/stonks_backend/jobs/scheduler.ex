defmodule StonksBackend.Jobs.Scheduler do
  @moduledoc "Elixir job-spec generator for Oban-backed scheduled backend components."

  alias StonksBackend.{Jobs, News.SourceFetcher, Settings, Shorts}

  @market_history_window_key "rolling_3y"

  def schedule_due_jobs(opts \\ []) do
    enqueue = Keyword.get(opts, :enqueue_fun, &Jobs.enqueue/3)

    leading_specs =
      snapshot_refresh_job_specs(opts) ++
        market_history_job_specs(opts) ++
        instrument_search_index_job_specs(opts) ++
        shorts_job_specs(opts) ++
        news_fetch_job_specs(opts)

    ids = enqueue_specs(leading_specs, enqueue, [])

    {ids, _previous_id} =
      Enum.reduce(news_pipeline_job_specs(opts), {ids, nil}, fn spec, {ids, previous_id} ->
        case enqueue_spec(spec, enqueue, previous_id) do
          nil -> {ids, previous_id}
          job_id -> {ids ++ [job_id], job_id}
        end
      end)

    enqueue_specs(trump_disclosure_job_specs(opts), enqueue, ids)
  end

  def trump_disclosure_job_specs(opts \\ []) do
    settings = Keyword.get(opts, :settings)

    if scheduler_enabled?(settings) do
      now = now(opts)
      timestamp = DateTime.to_unix(now)

      []
      |> maybe_add_sec_disclosure_spec(settings, timestamp)
      |> maybe_add_oge_disclosure_spec(settings, timestamp)
    else
      []
    end
  end

  def snapshot_refresh_job_specs(opts \\ []) do
    settings = Keyword.get(opts, :settings)
    refresh_seconds = int_setting(settings, :snapshot_refresh_seconds, 900)

    if scheduler_enabled?(settings) and refresh_seconds > 0 do
      window = div(DateTime.to_unix(now(opts)), refresh_seconds)

      [
        %{
          job_type: "snapshot_refresh",
          idempotency_key: "snapshot-refresh:#{window}",
          payload: %{},
          job_group: "snapshots",
          priority: 60,
          provider_key: "snapshot_refresh"
        }
      ]
    else
      []
    end
  end

  def news_fetch_job_specs(opts \\ []) do
    settings = Keyword.get(opts, :settings)
    refresh_seconds = int_setting(settings, :news_source_refresh_seconds, 900)

    if scheduler_enabled?(settings) and refresh_seconds > 0 do
      sources = enabled_news_sources(settings)
      offsets = source_offsets(sources, settings)
      timestamp = DateTime.to_unix(now(opts))

      Enum.map(sources, fn source ->
        poll_seconds = source_poll_seconds(source, settings)
        window = div(timestamp, poll_seconds)
        window_start = DateTime.from_unix!(window * poll_seconds)
        run_after = DateTime.add(window_start, Map.get(offsets, source.source_key, 0), :second)

        %{
          job_type: "news.fetch_source",
          idempotency_key: "news-fetch:#{source.source_key}:#{window}",
          payload:
            %{
              "source_key" => source.source_key,
              "max_documents" => source_max_documents(source, settings)
            }
            |> put_optional("query", Map.get(source, :default_query)),
          job_group: "news",
          priority: 70,
          provider_key: source.rate_limit_provider_key,
          run_after: run_after
        }
      end)
    else
      []
    end
  end

  def news_pipeline_job_specs(opts \\ []) do
    settings = Keyword.get(opts, :settings)
    interval_seconds = int_setting(settings, :news_publication_interval_seconds, 300)

    if scheduler_enabled?(settings) and news_pipeline_runtime_enabled?(settings) and
         interval_seconds > 0 do
      timestamp = DateTime.to_unix(now(opts))
      window = div(timestamp, interval_seconds)
      purge_window = div(timestamp, 86_400)
      processing_limit = int_setting(settings, :news_processing_batch_limit, 500)

      [
        %{
          job_type: "news.read_pages",
          idempotency_key: "news-read-pages:#{window}",
          payload: %{"limit" => int_setting(settings, :news_page_read_batch_limit, 25)},
          job_group: "news",
          priority: 68,
          provider_key: "company_ir"
        },
        %{
          job_type: "news.normalize_document",
          idempotency_key: "news-normalize:#{window}",
          payload: %{"limit" => processing_limit},
          job_group: "news",
          priority: 68,
          provider_key: "local"
        },
        %{
          job_type: "news.classify_entities",
          idempotency_key: "news-classify:#{window}",
          payload: %{"limit" => processing_limit},
          job_group: "news",
          priority: 68,
          provider_key: "local"
        },
        %{
          job_type: "news.cluster_events",
          idempotency_key: "news-cluster:#{window}",
          payload: %{"limit" => processing_limit},
          job_group: "news",
          priority: 68,
          provider_key: "local"
        },
        %{
          job_type: "news.score_events",
          idempotency_key: "news-score:#{window}",
          payload: %{},
          job_group: "news",
          priority: 68,
          provider_key: "local"
        },
        %{
          job_type: "news.purge_email_raw",
          idempotency_key: "news-purge-email-raw:#{purge_window}",
          payload: %{"limit" => 500},
          job_group: "news",
          priority: 68,
          provider_key: "local"
        },
        %{
          job_type: "news.prune_metadata",
          idempotency_key: "news-prune-metadata:#{purge_window}",
          payload: %{
            "discovery_retention_days" =>
              int_setting(settings, :news_discovery_retention_days, 30),
            "metadata_retention_days" => int_setting(settings, :news_metadata_retention_days, 90),
            "event_retention_days" => int_setting(settings, :news_event_retention_days, 365)
          },
          job_group: "news",
          priority: 40,
          provider_key: "local"
        }
      ]
    else
      []
    end
  end

  def market_history_job_specs(opts \\ []) do
    settings = Keyword.get(opts, :settings)

    cond do
      not scheduler_enabled?(settings) ->
        []

      not truthy_setting?(settings, :market_data_scheduled_refresh_enabled, true) ->
        []

      true ->
        symbols =
          settings
          |> setting(:market_data_refresh_symbol_list, nil)
          |> normalize_symbol_list(setting(settings, :market_data_refresh_symbols, ""))

        if symbols == [] do
          []
        else
          session_date = target_us_market_session(now(opts))
          anchor = market_history_session_anchor(session_date, settings)

          spread_seconds =
            max(60, int_setting(settings, :market_data_refresh_spread_minutes, 240) * 60)

          window_days = int_setting(settings, :market_data_snapshot_window_days, 1095)
          start = Date.add(session_date, -window_days)

          Enum.map(symbols, fn symbol ->
            offset = stable_offset(symbol, spread_seconds)

            %{
              job_type: "market_data.refresh_history",
              idempotency_key:
                "market-history:#{@market_history_window_key}:#{symbol}:#{Date.to_iso8601(session_date)}",
              payload: %{
                "symbol" => symbol,
                "mode" => "rolling_3y_snapshot",
                "window_key" => @market_history_window_key,
                "window_days" => window_days,
                "market_session_date" => Date.to_iso8601(session_date),
                "start" => Date.to_iso8601(start),
                "end" => Date.to_iso8601(session_date)
              },
              job_group: "market_data",
              priority: 65,
              provider_key: "market_data",
              run_after: DateTime.add(anchor, offset, :second)
            }
          end)
        end
    end
  end

  def instrument_search_index_job_specs(opts \\ []) do
    settings = Keyword.get(opts, :settings)
    refresh_seconds = int_setting(settings, :instrument_universe_refresh_seconds, 14_400)

    if scheduler_enabled?(settings) and refresh_seconds > 0 do
      refresh_seconds = max(3_600, refresh_seconds)
      timestamp = DateTime.to_unix(now(opts))
      window = div(timestamp, refresh_seconds)
      window_start = DateTime.from_unix!(window * refresh_seconds)
      offset = stable_offset("instrument-universe", min(refresh_seconds, 3_600))

      [
        %{
          job_type: "instrument_search_index_update",
          idempotency_key: "instrument-universe:#{window}",
          payload: %{"source" => "CONFIGURED_FREE_SOURCES", "mode" => "FULL"},
          job_group: "instruments",
          priority: 85,
          provider_key: "instrument_universe",
          run_after: DateTime.add(window_start, offset, :second)
        }
      ]
    else
      []
    end
  end

  def shorts_job_specs(opts \\ []) do
    settings = Keyword.get(opts, :settings)

    if scheduler_enabled?(settings) and truthy_setting?(settings, :shorts_ingestion_enabled, true) do
      now = now(opts)
      trade_date = Shorts.default_trade_date(now)
      date_key = Date.to_iso8601(trade_date)
      short_interest_window = div(DateTime.to_unix(now), 86_400)

      [
        %{
          job_type: "shorts.finra_daily_short_volume",
          idempotency_key: "shorts:finra-daily-short-volume:#{date_key}",
          payload: %{"date" => date_key},
          job_group: "shorts",
          priority: 70,
          provider_key: "finra",
          run_after: Shorts.finra_daily_publication_anchor(trade_date)
        },
        %{
          job_type: "shorts.finra_short_interest_release",
          idempotency_key: "shorts:finra-short-interest:#{short_interest_window}",
          payload: %{},
          job_group: "shorts",
          priority: 75,
          provider_key: "finra",
          run_after: DateTime.add(now, 300, :second)
        },
        %{
          job_type: "shorts.short_research_metadata",
          idempotency_key: "shorts:short-research-metadata:#{short_interest_window}",
          payload: %{},
          job_group: "shorts",
          priority: 90,
          provider_key: "public_web",
          run_after: DateTime.add(now, 600, :second)
        }
      ]
    else
      []
    end
  end

  def enabled_news_sources(settings \\ nil) do
    SourceFetcher.scheduled_profiles()
    |> Enum.map(&scheduler_source/1)
    |> Enum.filter(&source_enabled?(&1, settings))
  end

  defp scheduler_source(profile) do
    %{
      source_key: profile.source_key,
      rate_limit_provider_key: profile.rate_limit_provider_key,
      rate_limit_endpoint_key: profile.rate_limit_endpoint_key,
      scheduled_fetch: Map.get(profile, :scheduled_fetch, false),
      fetch_kind: Map.get(profile, :fetch_kind, "feed"),
      default_query: Map.get(profile, :default_query)
    }
  end

  def source_poll_seconds(source, settings \\ nil) do
    configured = int_value(Map.get(source, :poll_seconds), 0)

    cond do
      configured > 0 ->
        max(300, configured)

      source.source_key == "who" or source.rate_limit_provider_key == "who" ->
        3_600

      source.fetch_kind in ["html_index", "html_article"] or
          source.rate_limit_endpoint_key == "html" ->
        1_800

      source.rate_limit_provider_key in [
        "google_news_rss",
        "yahoo_finance_rss",
        "sec_edgar",
        "federal_reserve",
        "gdelt"
      ] ->
        max(300, int_setting(settings, :news_source_refresh_seconds, 900))

      true ->
        max(300, int_setting(settings, :news_source_refresh_seconds, 900))
    end
  end

  def source_max_documents(source, settings \\ nil) do
    cap = int_setting(settings, :news_max_documents_per_source_per_run, 100)

    cap =
      cond do
        source.rate_limit_provider_key in [
          "google_news_rss",
          "yahoo_finance_rss",
          "sec_edgar",
          "who",
          "federal_reserve"
        ] ->
          min(cap, 20)

        source.rate_limit_provider_key == "company_ir" or
            source.fetch_kind in ["html_index", "html_article"] ->
          min(cap, 10)

        source.rate_limit_provider_key == "gdelt" and
            source.fetch_kind in ["gdelt_event_file", "gdelt_gkg_file"] ->
          min(cap, int_setting(settings, :gdelt_bulk_max_documents, 500))

        source.rate_limit_provider_key == "gdelt" ->
          min(cap, int_setting(settings, :gdelt_doc_max_records, 250))

        true ->
          cap
      end

    max(1, cap)
  end

  defp enqueue_specs(specs, enqueue, ids) do
    Enum.reduce(specs, ids, fn spec, ids ->
      case enqueue_spec(spec, enqueue, Map.get(spec, :depends_on_job_id)) do
        nil -> ids
        job_id -> ids ++ [job_id]
      end
    end)
  end

  defp enqueue_spec(spec, enqueue, depends_on_job_id) do
    opts = enqueue_opts(spec, depends_on_job_id)

    case enqueue.(spec.job_type, spec.payload, opts) do
      {:ok, job_id} -> job_id
      job_id when is_binary(job_id) -> job_id
      _ -> nil
    end
  end

  defp enqueue_opts(spec, depends_on_job_id) do
    [
      queue: spec.job_group,
      priority: spec.priority,
      idempotency_key: spec.idempotency_key,
      provider_key: spec.provider_key,
      run_after: Map.get(spec, :run_after),
      depends_on_job_id: depends_on_job_id
    ]
    |> Enum.reject(fn {_key, value} -> is_nil(value) end)
  end

  defp maybe_add_sec_disclosure_spec(specs, settings, timestamp) do
    poll_seconds = int_setting(settings, :trump_disclosure_sec_poll_seconds, 1_800)

    if poll_seconds > 0 do
      window = div(timestamp, poll_seconds)

      specs ++
        [
          %{
            job_type: "trump_disclosures_ingest",
            idempotency_key: "trump-disclosures:sec:#{window}",
            payload: %{"include_sec" => true, "include_oge" => false},
            job_group: "disclosures",
            priority: 40,
            provider_key: "sec_edgar"
          }
        ]
    else
      specs
    end
  end

  defp maybe_add_oge_disclosure_spec(specs, settings, timestamp) do
    poll_seconds = int_setting(settings, :trump_disclosure_oge_poll_seconds, 86_400)
    pdf_limit = int_setting(settings, :trump_disclosure_oge_pdf_limit, 12)

    if poll_seconds > 0 and pdf_limit > 0 do
      window = div(timestamp, poll_seconds)

      specs ++
        [
          %{
            job_type: "trump_disclosures_ingest",
            idempotency_key: "trump-disclosures:oge:#{window}",
            payload: %{"include_sec" => false, "include_oge" => true},
            job_group: "disclosures",
            priority: 80,
            provider_key: "oge_disclosures"
          }
        ]
    else
      specs
    end
  end

  defp source_offsets(sources, settings) do
    sources
    |> Enum.group_by(fn source ->
      {source.rate_limit_provider_key, source.rate_limit_endpoint_key,
       source_poll_seconds(source, settings)}
    end)
    |> Enum.flat_map(fn {{_provider, _endpoint, poll_seconds}, group} ->
      ordered = Enum.sort_by(group, & &1.source_key)
      size = max(1, length(ordered))

      ordered
      |> Enum.with_index()
      |> Enum.map(fn {source, index} ->
        {source.source_key, trunc(index * poll_seconds / size)}
      end)
    end)
    |> Map.new()
  end

  defp source_enabled?(source, settings) do
    cond do
      source.source_key in ["gdelt_events", "gdelt_gkg"] ->
        truthy_setting?(settings, :news_gdelt_enabled, false) and
          truthy_setting?(settings, :gdelt_bulk_runtime_enabled, false)

      source.source_key == "gdelt" ->
        truthy_setting?(settings, :news_gdelt_enabled, false)

      source.source_key == "who" ->
        truthy_setting?(settings, :news_public_health_enabled, true)

      source.rate_limit_provider_key in ["google_news_rss", "yahoo_finance_rss"] ->
        truthy_setting?(settings, :news_rss_enabled, true)

      true ->
        true
    end
  end

  defp scheduler_enabled?(settings),
    do: truthy_setting?(settings, :worker_scheduler_enabled, true)

  defp news_pipeline_runtime_enabled?(settings),
    do: truthy_setting?(settings, :news_pipeline_runtime_enabled, false)

  defp target_us_market_session(now) do
    local_date = eastern_local_date(now)

    if weekday?(local_date) do
      local_date
    else
      previous_weekday(local_date)
    end
  end

  defp market_history_session_anchor(session_date, settings) do
    delay_minutes = int_setting(settings, :market_data_refresh_after_close_minutes, 45)
    local_close = NaiveDateTime.new!(session_date, us_market_close_time(session_date))
    utc_offset_hours = eastern_utc_offset_hours(session_date)

    local_close
    |> DateTime.from_naive!("Etc/UTC")
    |> DateTime.add(-utc_offset_hours * 3_600 + delay_minutes * 60, :second)
  end

  defp eastern_local_date(now) do
    now
    |> DateTime.add(eastern_utc_offset_hours(DateTime.to_date(now)) * 3_600, :second)
    |> DateTime.to_date()
  end

  defp eastern_utc_offset_hours(date) do
    dst_start = nth_weekday(date.year, 3, 7, 2)
    dst_end = nth_weekday(date.year, 11, 7, 1)

    if Date.compare(date, dst_start) in [:gt, :eq] and Date.compare(date, dst_end) == :lt do
      -4
    else
      -5
    end
  end

  defp us_market_close_time(session_date) do
    if us_market_early_close?(session_date), do: ~T[13:00:00], else: ~T[16:00:00]
  end

  defp us_market_early_close?(session_date) do
    thanksgiving = nth_weekday(session_date.year, 11, 4, 4)

    cond do
      session_date == Date.add(thanksgiving, 1) -> true
      session_date.month == 12 and session_date.day == 24 and weekday?(session_date) -> true
      session_date.month == 7 and session_date.day == 3 and weekday?(session_date) -> true
      true -> false
    end
  end

  defp nth_weekday(year, month, weekday_1_to_7, n) do
    first = Date.new!(year, month, 1)
    offset = rem(weekday_1_to_7 - Date.day_of_week(first) + 7, 7)
    Date.add(first, offset + (n - 1) * 7)
  end

  defp previous_weekday(date) do
    date = Date.add(date, -1)
    if weekday?(date), do: date, else: previous_weekday(date)
  end

  defp weekday?(date), do: Date.day_of_week(date) in 1..5

  defp now(opts), do: Keyword.get(opts, :now, DateTime.utc_now())

  defp stable_offset(key, modulo_seconds) do
    digest = :crypto.hash(:sha256, to_string(key))
    <<prefix::32, _rest::binary>> = digest
    rem(prefix, max(1, modulo_seconds))
  end

  defp normalize_symbol_list(value, fallback) when is_list(value) do
    value
    |> Enum.map(&(&1 |> to_string() |> String.trim() |> String.upcase()))
    |> Enum.reject(&(&1 == ""))
    |> Enum.uniq()
    |> case do
      [] -> normalize_symbol_list(fallback, "")
      symbols -> symbols
    end
  end

  defp normalize_symbol_list(value, _fallback) do
    value
    |> to_string()
    |> Settings.split_csv()
    |> Enum.map(&String.upcase/1)
    |> Enum.uniq()
  end

  defp truthy_setting?(settings, key, default),
    do: setting(settings, key, default) |> Settings.truthy?()

  defp int_setting(settings, key, default),
    do: setting(settings, key, default) |> int_value(default)

  defp setting(nil, key, default), do: Settings.get(key, default)
  defp setting(settings, key, default) when is_map(settings), do: Map.get(settings, key, default)

  defp setting(settings, key, default) when is_list(settings),
    do: Keyword.get(settings, key, default)

  defp setting(_settings, _key, default), do: default

  defp int_value(value, _default) when is_integer(value), do: value

  defp int_value(value, default) when is_binary(value) do
    case Integer.parse(String.trim(value)) do
      {integer, ""} -> integer
      _ -> default
    end
  end

  defp int_value(_, default), do: default

  defp put_optional(map, _key, nil), do: map
  defp put_optional(map, _key, ""), do: map
  defp put_optional(map, key, value), do: Map.put(map, key, value)
end
