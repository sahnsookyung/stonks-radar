defmodule StonksBackend.Repo.Migrations.DisableLegacyYahooFinanceRss do
  use Ecto.Migration

  def up do
    execute("""
    update source_health_status
    set status = 'disabled',
        last_checked_at = now(),
        last_success_at = null,
        details = coalesce(details, '{}'::jsonb) || jsonb_build_object(
          'reason', 'retired_endpoint',
          'endpoint_status', 404,
          'replacement', 'google_news_rss'
        )
    where source_key like 'yahoo_finance_%'
    """)

    execute("""
    update oban_jobs
    set state = 'discarded',
        discarded_at = coalesce(discarded_at, now())
    where args ->> 'job_type' = 'news.fetch_source'
      and args -> 'payload' ->> 'source_key' like 'yahoo_finance_%'
      and state in ('available', 'scheduled', 'retryable', 'executing')
    """)
  end

  def down do
    execute("""
    delete from source_health_status
    where source_key like 'yahoo_finance_%'
      and details ->> 'reason' = 'retired_endpoint'
    """)
  end
end
