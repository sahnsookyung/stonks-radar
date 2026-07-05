defmodule StonksBackend.Repo.Migrations.AddPortfolioWorkspaces do
  use Ecto.Migration

  def up do
    execute("""
    create table if not exists portfolio_workspace (
      user_id uuid not null references app_user(id) on delete cascade,
      portfolio_id text not null,
      workspace jsonb not null,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now(),
      primary key (user_id, portfolio_id)
    )
    """)

    execute("""
    create index if not exists portfolio_workspace_updated_idx
      on portfolio_workspace(updated_at desc)
    """)
  end

  def down do
    execute("drop table if exists portfolio_workspace;")
  end
end
