defmodule StonksBackend.Repo.Migrations.AddAuditPayload do
  use Ecto.Migration

  def up do
    execute("""
    alter table audit_log
      add column if not exists after_json jsonb not null default '{}'::jsonb
    """)
  end

  def down do
    # Audit evidence is retained across application rollbacks.
    :ok
  end
end
