defmodule StonksBackend.Repo.Migrations.AddEarningsCalendarFactType do
  use Ecto.Migration

  def up do
    execute """
    insert into fact_type_registry(
      fact_type, display_name_en, display_name_ko, json_schema,
      allowed_predicates, public_allowed_default, requires_review, active
    )
    values (
      'earnings_calendar',
      'Earnings calendar',
      '실적 발표 일정',
      '{"type":"object","required":["symbol","company_name","earnings_date","source","source_url","provider_observation_key"],"properties":{"symbol":{"type":"string"},"company_name":{"type":"string"},"earnings_date":{"type":"string"},"time_of_day":{"type":"string"},"fiscal_period":{"type":["string","null"]},"eps_estimate":{"type":["string","null"]},"revenue_estimate":{"type":["string","null"]},"currency":{"type":["string","null"]},"source":{"type":"string"},"source_url":{"type":"string"},"confirmed_status":{"type":"string"},"last_checked_at":{"type":"string"},"dataset":{"type":"string"},"provider_observation_key":{"type":"string"},"ingestion_run_id":{"type":"string"},"release_id":{"type":"string"},"source_policy_version":{"type":"integer"}},"additionalProperties":true}'::jsonb,
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
  end

  def down do
    execute "delete from fact_type_registry where fact_type = 'earnings_calendar'"
  end
end
