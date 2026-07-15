defmodule StonksBackend.TickerAlerts do
  @moduledoc "User-owned ticker alert rules, event deduplication, cooldowns, and catch-up watermarks."

  alias StonksBackend.{Jobs, PrivateMarketData, Sql}

  @types ~w(price_threshold rsi macd_cross volume_spike sec_filing news_spike short_interest_update option_iv_threshold)
  @symbol_regex ~r/^[A-Z0-9.\-]{1,16}$/
  @max_configuration_bytes 16_384

  def list_rules(user_id) do
    {:ok,
     Sql.all(
       """
       select id, symbol, rule_type, configuration, cooldown_seconds, email_enabled,
              active, last_evaluated_source_at, created_at, updated_at
       from ticker_alert_rule
       where user_id = $1
       order by updated_at desc
       """,
       [user_id]
     )}
  rescue
    _ -> {:error, :storage_unavailable}
  end

  def create_rule(user_id, attrs) do
    with {:ok, rule} <- validate_rule(attrs) do
      row =
        Sql.one(
          """
          insert into ticker_alert_rule(
            user_id, symbol, rule_type, configuration, cooldown_seconds, email_enabled, active
          )
          values ($1, $2, $3, $4::text::jsonb, $5, $6, $7)
          returning id, symbol, rule_type, configuration, cooldown_seconds, email_enabled,
                    active, last_evaluated_source_at, created_at, updated_at
          """,
          [
            user_id,
            rule.symbol,
            rule.rule_type,
            Jason.encode!(rule.configuration),
            rule.cooldown_seconds,
            rule.email_enabled,
            rule.active
          ]
        )

      if row, do: {:ok, row}, else: {:error, :storage_unavailable}
    end
  end

  def update_rule(user_id, rule_id, attrs) do
    with {:ok, rule} <- validate_rule(attrs) do
      row =
        Sql.one(
          """
          update ticker_alert_rule set
            symbol = $3,
            rule_type = $4,
            configuration = $5::text::jsonb,
            cooldown_seconds = $6,
            email_enabled = $7,
            active = $8,
            updated_at = now()
          where id = $1 and user_id = $2
          returning id, symbol, rule_type, configuration, cooldown_seconds, email_enabled,
                    active, last_evaluated_source_at, created_at, updated_at
          """,
          [
            rule_id,
            user_id,
            rule.symbol,
            rule.rule_type,
            Jason.encode!(rule.configuration),
            rule.cooldown_seconds,
            rule.email_enabled,
            rule.active
          ]
        )

      if row, do: {:ok, row}, else: {:error, :not_found}
    end
  end

  def delete_rule(user_id, rule_id) do
    result =
      Sql.execute("delete from ticker_alert_rule where id = $1 and user_id = $2", [
        rule_id,
        user_id
      ])

    if result.num_rows > 0, do: :ok, else: {:error, :not_found}
  rescue
    _ -> {:error, :storage_unavailable}
  end

  def list_events(user_id, limit \\ 100) do
    {:ok,
     Sql.all(
       """
       select event.id, event.rule_id, rule.symbol, rule.rule_type,
              event.source_event_key, event.source_at, event.reason, event.payload,
              event.delivery_status, event.read_at, event.created_at
       from ticker_alert_event event
       join ticker_alert_rule rule on rule.id = event.rule_id
       where event.user_id = $1
       order by event.created_at desc
       limit $2
       """,
       [user_id, limit |> max(1) |> min(250)]
     )}
  rescue
    _ -> {:error, :storage_unavailable}
  end

  def mark_read(user_id, event_id) do
    row =
      Sql.one(
        """
        update ticker_alert_event set read_at = coalesce(read_at, now())
        where id = $1 and user_id = $2
        returning id, read_at
        """,
        [event_id, user_id]
      )

    if row, do: {:ok, row}, else: {:error, :not_found}
  end

  def create_event(rule, source_event_key, source_at, reason, payload \\ %{}) do
    row =
      Sql.one(
        """
        insert into ticker_alert_event(
          rule_id, user_id, source_event_key, source_at, reason, payload, delivery_status
        )
        select $1, $2, $3, $4, $5, $6::text::jsonb, 'in_app'
        where not exists (
          select 1 from ticker_alert_event
          where rule_id = $1
            and source_at > $4::timestamptz - ($7 * interval '1 second')
        )
        on conflict (rule_id, source_event_key) do nothing
        returning id
        """,
        [
          rule["id"] || rule[:id],
          rule["user_id"] || rule[:user_id],
          source_event_key,
          source_at,
          reason,
          Jason.encode!(payload),
          rule["cooldown_seconds"] || rule[:cooldown_seconds] || 3600
        ]
      )

    if row do
      maybe_enqueue_email(rule, row["id"])
      {:ok, %{id: to_string(row["id"]), deduplicated: false}}
    else
      {:ok, %{id: nil, deduplicated: true}}
    end
  rescue
    _ -> {:error, :storage_unavailable}
  end

  def evaluate(rule, observation) when is_map(rule) and is_map(observation) do
    type = to_string(rule["rule_type"] || rule[:rule_type])
    config = rule["configuration"] || rule[:configuration] || %{}

    triggered =
      case type do
        "price_threshold" ->
          compare(observation_value(observation, "price"), config)

        "rsi" ->
          compare(observation_value(observation, "rsi"), config)

        "option_iv_threshold" ->
          compare(observation_value(observation, "iv"), config)

        "volume_spike" ->
          observation_value(observation, "volume_ratio") >= number(config, "value")

        "macd_cross" ->
          to_string(observation["direction"] || observation[:direction]) ==
            to_string(config["direction"] || config[:direction])

        event_type when event_type in ["sec_filing", "news_spike", "short_interest_update"] ->
          observation["matched"] == true or observation[:matched] == true

        _ ->
          false
      end

    if triggered do
      {:triggered,
       %{
         reason: "#{type} rule matched",
         source_event_key:
           to_string(
             observation["source_event_key"] || observation[:source_event_key] ||
               observation["source_at"] || observation[:source_at]
           )
       }}
    else
      :not_triggered
    end
  end

  def validate_rule(attrs) when is_map(attrs) do
    symbol = attrs |> value("symbol") |> to_string() |> String.trim() |> String.upcase()
    rule_type = attrs |> value("rule_type") |> to_string()
    configuration = value(attrs, "configuration") || %{}
    cooldown = int_value(value(attrs, "cooldown_seconds"), 3600)
    email_enabled = truthy?(value(attrs, "email_enabled"))
    active = if is_nil(value(attrs, "active")), do: true, else: truthy?(value(attrs, "active"))

    cond do
      not Regex.match?(@symbol_regex, symbol) ->
        {:error, :invalid_symbol}

      rule_type not in @types ->
        {:error, :invalid_rule_type}

      not is_map(configuration) ->
        {:error, :invalid_configuration}

      byte_size(Jason.encode!(configuration)) > @max_configuration_bytes ->
        {:error, :configuration_too_large}

      cooldown not in 0..2_592_000 ->
        {:error, :invalid_cooldown}

      not valid_configuration?(rule_type, configuration) ->
        {:error, :invalid_configuration}

      true ->
        {:ok,
         %{
           symbol: symbol,
           rule_type: rule_type,
           configuration: stringify_keys(configuration),
           cooldown_seconds: cooldown,
           email_enabled: email_enabled,
           active: active
         }}
    end
  rescue
    _ -> {:error, :invalid_rule}
  end

  def validate_rule(_attrs), do: {:error, :invalid_rule}

  def catch_up(payload \\ %{}, opts \\ []) do
    rules =
      Keyword.get_lazy(opts, :rules, fn ->
        Sql.all("""
        select id, user_id, symbol, rule_type, configuration, cooldown_seconds,
               email_enabled, last_evaluated_source_at
        from ticker_alert_rule
        where active = true
        order by updated_at
        """)
      end)

    observation_fun = Keyword.get(opts, :observation_fun, &latest_observations/1)
    create_event_fun = Keyword.get(opts, :create_event_fun, &create_event/5)
    watermark_fun = Keyword.get(opts, :watermark_fun, &maybe_advance_watermark/2)

    result =
      Enum.reduce(rules, %{rules_seen: 0, observations_seen: 0, events_created: 0}, fn rule,
                                                                                       acc ->
        try do
          observations = observation_fun.(rule)

          {created, latest_source_at} =
            Enum.reduce(observations, {0, nil}, fn observation, {created, latest} ->
              source_at = observation[:source_at] || observation["source_at"]

              created =
                case evaluate(rule, observation) do
                  {:triggered, event} ->
                    case create_event_fun.(
                           rule,
                           event.source_event_key,
                           source_at,
                           event.reason,
                           Map.drop(observation, [:source_event_key, :source_at])
                         ) do
                      {:ok, %{deduplicated: false}} -> created + 1
                      _ -> created
                    end

                  :not_triggered ->
                    created
                end

              {created, later_source_at(latest, source_at)}
            end)

          watermark_fun.(rule, latest_source_at)

          %{
            rules_seen: acc.rules_seen + 1,
            observations_seen: acc.observations_seen + length(observations),
            events_created: acc.events_created + created
          }
        rescue
          _ -> %{acc | rules_seen: acc.rules_seen + 1}
        end
      end)

    Map.merge(result, %{
      status: "ready",
      mode: "hourly_watermark",
      watermark_window: payload["watermark_window"] || payload[:watermark_window]
    })
  end

  defp latest_observations(rule) do
    case to_string(rule["rule_type"] || rule[:rule_type]) do
      type when type in ["price_threshold", "rsi", "macd_cross", "volume_spike"] ->
        market_observation(rule) |> List.wrap()

      "sec_filing" ->
        event_observations(rule, :filing)

      "news_spike" ->
        event_observations(rule, :news)

      "short_interest_update" ->
        event_observations(rule, :short)

      "option_iv_threshold" ->
        option_observation(rule) |> List.wrap()

      _ ->
        []
    end
  end

  defp market_observation(rule) do
    symbol = rule["symbol"] || rule[:symbol]

    rows =
      Sql.all(
        """
        select distinct on (price_date)
               price_date, close, volume, provider_price_timestamp, ingested_at
        from market_price_bar
        where symbol = $1 and interval = '1day' and quality_state = 'valid'
        order by price_date desc, ingested_at desc
        limit 80
        """,
        [symbol]
      )
      |> Enum.reverse()

    latest = List.last(rows)

    if latest do
      closes = Enum.map(rows, &numeric(&1["close"]))
      volumes = Enum.map(rows, &numeric(&1["volume"]))
      {current_macd, previous_macd} = macd_histograms(closes)
      source_at = latest["provider_price_timestamp"] || latest["ingested_at"]

      %{
        price: List.last(closes),
        rsi: rsi(closes),
        volume_ratio: volume_ratio(volumes),
        direction: macd_direction(current_macd, previous_macd),
        source_at: source_at,
        source_event_key: "market-price:#{symbol}:#{latest["price_date"]}"
      }
    end
  end

  defp event_observations(rule, :filing) do
    symbol = rule["symbol"] || rule[:symbol]
    since = watermark(rule)

    Sql.all(
      """
      select id, coalesce(filed_at, doc_date::timestamptz, created_at) as source_at,
             form_type, source_url
      from source_filings
      where upper(ticker) = upper($1)
        and coalesce(filed_at, doc_date::timestamptz, created_at) > $2
      order by source_at
      limit 100
      """,
      [symbol, since]
    )
    |> Enum.map(fn row ->
      %{
        matched: true,
        source_at: row["source_at"],
        source_event_key: "filing:#{row["id"]}",
        form_type: row["form_type"],
        source_url: row["source_url"]
      }
    end)
  end

  defp event_observations(rule, :news) do
    symbol = rule["symbol"] || rule[:symbol]
    since = watermark(rule)

    Sql.all(
      """
      select c.id, c.last_seen_at as source_at, c.canonical_title, c.severity
      from news_event_entity e
      join news_event_cluster c on c.id = e.event_id
      where upper(e.entity_key) = upper($1)
        and c.last_seen_at > $2
        and c.status = 'active'
      order by c.last_seen_at
      limit 100
      """,
      [symbol, since]
    )
    |> Enum.map(fn row ->
      %{
        matched: true,
        source_at: row["source_at"],
        source_event_key: "news:#{row["id"]}",
        title: row["canonical_title"],
        severity: row["severity"]
      }
    end)
  end

  defp event_observations(rule, :short) do
    symbol = rule["symbol"] || rule[:symbol]
    since = watermark(rule)

    Sql.all(
      """
      select id, created_at as source_at, fact_type, object_json
      from source_fact
      where fact_type in ('short_interest', 'short_volume')
        and upper(object_json->>'symbol') = upper($1)
        and created_at > $2
      order by created_at
      limit 100
      """,
      [symbol, since]
    )
    |> Enum.map(fn row ->
      %{
        matched: true,
        source_at: row["source_at"],
        source_event_key: "short:#{row["id"]}",
        fact_type: row["fact_type"]
      }
    end)
  end

  defp option_observation(rule) do
    user_id = rule["user_id"] || rule[:user_id]
    symbol = rule["symbol"] || rule[:symbol]

    case PrivateMarketData.options(user_id, symbol, nil) do
      {:ok, %{chain: chain, as_of: as_of}, _cache} when is_list(chain) and chain != [] ->
        iv =
          chain
          |> Enum.map(&numeric(&1[:implied_volatility] || &1["implied_volatility"]))
          |> Enum.filter(&is_number/1)
          |> Enum.max(fn -> 0.0 end)

        %{
          iv: iv,
          source_at: normalized_source_at(as_of),
          source_event_key: "option-iv:#{symbol}:#{as_of}"
        }

      _ ->
        nil
    end
  end

  defp maybe_advance_watermark(_rule, nil), do: :ok

  defp maybe_advance_watermark(rule, source_at) do
    Sql.execute(
      """
      update ticker_alert_rule
      set last_evaluated_source_at = greatest(coalesce(last_evaluated_source_at, $3), $3),
          updated_at = now()
      where id = $1 and user_id = $2
      """,
      [rule["id"] || rule[:id], rule["user_id"] || rule[:user_id], source_at]
    )

    :ok
  end

  defp watermark(rule) do
    rule["last_evaluated_source_at"] || rule[:last_evaluated_source_at] ||
      DateTime.add(DateTime.utc_now(), -3_600, :second)
  end

  defp later_source_at(nil, right), do: right
  defp later_source_at(left, nil), do: left

  defp later_source_at(left, right),
    do: if(to_string(right) > to_string(left), do: right, else: left)

  defp normalized_source_at(value) when is_integer(value) do
    DateTime.from_unix!(value, if(value > 10_000_000_000, do: :millisecond, else: :second))
  end

  defp normalized_source_at(value), do: value || DateTime.utc_now()

  defp volume_ratio(volumes) do
    latest = List.last(volumes) || 0.0
    previous = volumes |> Enum.drop(-1) |> Enum.take(-20)
    average = if previous == [], do: 0.0, else: Enum.sum(previous) / length(previous)
    if average > 0, do: latest / average, else: 0.0
  end

  defp rsi(values) when length(values) < 15, do: 0.0

  defp rsi(values) do
    changes =
      values
      |> Enum.take(-15)
      |> Enum.chunk_every(2, 1, :discard)
      |> Enum.map(fn [left, right] -> right - left end)

    gains = changes |> Enum.filter(&(&1 > 0)) |> Enum.sum()
    losses = changes |> Enum.filter(&(&1 < 0)) |> Enum.map(&abs/1) |> Enum.sum()
    if losses == 0, do: 100.0, else: 100.0 - 100.0 / (1.0 + gains / losses)
  end

  defp macd_histograms(values) when length(values) < 35, do: {0.0, 0.0}

  defp macd_histograms(values) do
    macd = zip_subtract(ema_series(values, 12), ema_series(values, 26))
    signal = ema_series(macd, 9)
    histogram = zip_subtract(macd, signal)
    {List.last(histogram) || 0.0, Enum.at(histogram, -2) || 0.0}
  end

  defp ema_series([], _period), do: []

  defp ema_series([first | rest], period) do
    multiplier = 2.0 / (period + 1)

    Enum.scan(rest, first, fn value, previous -> (value - previous) * multiplier + previous end)
    |> then(&[first | &1])
  end

  defp zip_subtract(left, right),
    do: Enum.zip_with(left, right, fn left_value, right_value -> left_value - right_value end)

  defp macd_direction(current, previous) when current >= 0 and previous < 0, do: "bullish"
  defp macd_direction(current, previous) when current <= 0 and previous > 0, do: "bearish"
  defp macd_direction(_current, _previous), do: "none"

  defp valid_configuration?(type, config)
       when type in ["price_threshold", "rsi", "option_iv_threshold"] do
    to_string(value(config, "operator")) in ["above", "below"] and
      is_number_value?(value(config, "value"))
  end

  defp valid_configuration?("volume_spike", config), do: number(config, "value") > 1

  defp valid_configuration?("macd_cross", config),
    do: to_string(value(config, "direction")) in ["bullish", "bearish"]

  defp valid_configuration?(type, _config),
    do: type in ["sec_filing", "news_spike", "short_interest_update"]

  defp compare(actual, config) do
    threshold = number(config, "value")
    if value(config, "operator") == "below", do: actual < threshold, else: actual > threshold
  end

  defp observation_value(observation, key), do: observation |> value(key) |> numeric()
  defp number(config, key), do: config |> value(key) |> numeric()
  defp numeric(value) when is_number(value), do: value * 1.0

  defp numeric(value) when is_binary(value) do
    case Float.parse(value) do
      {number, _} -> number
      _ -> 0.0
    end
  end

  defp numeric(_value), do: 0.0

  defp is_number_value?(value),
    do: is_number(value) or (is_binary(value) and match?({_, ""}, Float.parse(value)))

  defp int_value(value, _default) when is_integer(value), do: value

  defp int_value(value, default) do
    case Integer.parse(to_string(value || "")) do
      {number, ""} -> number
      _ -> default
    end
  end

  defp truthy?(value), do: value in [true, 1, "1", "true", "yes", "on"]

  defp value(map, key) do
    Map.get(map, key) ||
      Enum.find_value(map, fn
        {map_key, map_value} when is_atom(map_key) ->
          if Atom.to_string(map_key) == key, do: map_value

        _entry ->
          nil
      end)
  end

  defp stringify_keys(map) do
    Map.new(map, fn {key, value} -> {to_string(key), value} end)
  end

  defp maybe_enqueue_email(rule, event_id) do
    if truthy?(rule["email_enabled"] || rule[:email_enabled]) do
      Jobs.enqueue("ticker_alert_email", %{"event_id" => to_string(event_id)},
        idempotency_key: "ticker-alert-email:#{event_id}",
        queue: :default
      )
    end

    :ok
  end
end
