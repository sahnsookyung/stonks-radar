defmodule StonksBackend.Repo.Migrations.AddShortsFactTypes do
  use Ecto.Migration

  def up do
    execute("""
    insert into fact_type_registry(
      fact_type, display_name_en, display_name_ko, json_schema,
      allowed_predicates, public_allowed_default, requires_review
    )
    values
      (
        'short_volume',
        'Daily short sale volume',
        '일별 공매도 거래량',
        '{"type":"object","required":["symbol","as_of_date","settlement_date","short_volume","short_exempt_volume","total_volume","source_url","dataset","provider_observation_key"],"properties":{"symbol":{"type":"string"},"as_of_date":{"type":"string"},"settlement_date":{"type":"string"},"short_volume":{"type":"integer","minimum":0},"short_exempt_volume":{"type":"integer","minimum":0},"total_volume":{"type":"integer","minimum":0},"short_volume_ratio":{"type":["number","null"]},"source":{"type":"string"},"source_url":{"type":"string"},"dataset":{"type":"string"},"provider_observation_key":{"type":"string"},"retrieved_at":{"type":"string"},"market":{"type":["string","null"]}},"additionalProperties":false}'::jsonb,
        array['reports'],
        true,
        false
      ),
      (
        'short_interest',
        'Short interest',
        '공매도 잔고',
        '{"type":"object","required":["symbol","settlement_date","source_url","dataset","provider_observation_key"],"properties":{"symbol":{"type":"string"},"as_of_date":{"type":"string"},"settlement_date":{"type":"string"},"short_interest":{"type":["integer","string"]},"source":{"type":"string"},"source_url":{"type":"string"},"dataset":{"type":"string"},"provider_observation_key":{"type":"string"},"retrieved_at":{"type":"string"}},"additionalProperties":true}'::jsonb,
        array['reports'],
        true,
        false
      )
    on conflict (fact_type) do update
    set json_schema = excluded.json_schema,
        allowed_predicates = excluded.allowed_predicates,
        public_allowed_default = excluded.public_allowed_default,
        requires_review = excluded.requires_review,
        active = true
    """)

    execute("""
    insert into job_concurrency_limit(scope_type, scope_key, max_running)
    values
      ('job_group', 'shorts', 1),
      ('provider', 'finra', 1)
    on conflict (scope_type, scope_key)
    do update set max_running = excluded.max_running, enabled = true
    """)
  end

  def down do
    execute(
      "delete from job_concurrency_limit where (scope_type, scope_key) in (('job_group', 'shorts'), ('provider', 'finra'))"
    )

    execute(
      "delete from fact_type_registry where fact_type in ('short_volume', 'short_interest')"
    )
  end
end
