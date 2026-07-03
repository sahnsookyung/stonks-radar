defmodule StonksBackend.Providers do
  @moduledoc "Admin-only provider budget helpers."

  alias StonksBackend.Sql

  def budgets do
    Sql.all("""
    select id, provider_key, provider_type, routing_mode, kill_switch_enabled,
           current_period_usage, hard_limit
    from provider_budget
    order by provider_key
    """)
  end

  def set_kill_switch(id, enabled) do
    Sql.execute("update provider_budget set kill_switch_enabled = $1 where id = $2", [enabled, id])
  end
end
