defmodule StonksBackend.Repo.Migrations.AddDataReliabilityRolloutIndexes do
  use Ecto.Migration
  require Logger

  @disable_ddl_transaction true

  def up do
    execute "set lock_timeout = '30s'"
    execute "set statement_timeout = '30min'"

    execute """
    insert into fact_type_registry(
      fact_type, display_name_en, display_name_ko, json_schema,
      allowed_predicates, public_allowed_default, requires_review, active
    )
    values (
      'yield_curve_observation',
      'Yield curve observation',
      '수익률 곡선 관측치',
      '{"type":"object","required":["country","tenor","series_key","as_of_date","value","source_url"],"additionalProperties":true}'::jsonb,
      array['reports'],
      true,
      false,
      true
    )
    on conflict (fact_type) do update
    set display_name_en = excluded.display_name_en,
        display_name_ko = excluded.display_name_ko,
        json_schema = excluded.json_schema,
        allowed_predicates = excluded.allowed_predicates,
        public_allowed_default = excluded.public_allowed_default,
        requires_review = excluded.requires_review,
        active = excluded.active
    """

    create_runtime_index("""
    create index concurrently if not exists source_document_news_runtime_idx
    on source_document(acquisition_mode, retention_class, status, source_published_at desc)
    where acquisition_mode = 'news_metadata'
    """)

    create_runtime_index("""
    create index concurrently if not exists source_document_news_classified_idx
    on source_document(source_published_at desc)
    where metadata ? 'news_classified_at'
    """)

    create_runtime_index("""
    create index concurrently if not exists source_document_canonical_identity_idx
    on source_document((md5(lower(coalesce(canonical_url, original_url, dedupe_key, '')))))
    where canonical_url is not null or original_url is not null or dedupe_key is not null
    """)

    create_runtime_index("""
    create index concurrently if not exists news_event_document_document_idx
    on news_event_document(document_id)
    """)

    create_runtime_index("""
    create index concurrently if not exists source_fact_public_type_idx
    on source_fact(fact_type, review_status, public_allowed, created_at desc)
    """)

    create_runtime_index("""
    create index concurrently if not exists source_fact_yield_curve_lookup_idx
    on source_fact(
      (object_json->>'country'),
      (object_json->>'tenor'),
      (object_json->>'as_of_date')
    )
    where fact_type = 'yield_curve_observation'
      and public_allowed = true
    """)

    create_runtime_index("""
    create index concurrently if not exists market_price_bar_quality_lookup_idx
    on market_price_bar(symbol, interval, quality_state, price_date desc)
    """)
  end

  def down do
    execute "drop index concurrently if exists market_price_bar_quality_lookup_idx"
    execute "drop index concurrently if exists source_fact_yield_curve_lookup_idx"
    execute "drop index concurrently if exists source_fact_public_type_idx"
    execute "drop index concurrently if exists news_event_document_document_idx"
    execute "drop index concurrently if exists source_document_canonical_identity_idx"
    execute "drop index concurrently if exists source_document_news_classified_idx"
    execute "drop index concurrently if exists source_document_news_runtime_idx"
  end

  defp create_runtime_index(sql) do
    sql = maybe_disable_concurrently_for_test(sql)

    try do
      execute(sql)
    rescue
      error in Postgrex.Error ->
        if lock_not_available?(error) do
          Logger.warning(
            "Skipping rollout index because Postgres lock was unavailable: #{index_name(sql)}"
          )
        else
          reraise error, __STACKTRACE__
        end
    end
  end

  defp maybe_disable_concurrently_for_test(sql) do
    if System.get_env("MIX_ENV") == "test" do
      String.replace(sql, "create index concurrently", "create index")
    else
      sql
    end
  end

  defp lock_not_available?(%Postgrex.Error{postgres: %{code: :lock_not_available}}), do: true
  defp lock_not_available?(_error), do: false

  defp index_name(sql) do
    case Regex.run(~r/create index(?: concurrently)? if not exists\s+([^\s]+)/i, sql) do
      [_match, name] -> name
      _other -> "unknown"
    end
  end
end
