defmodule StonksBackend.Audit do
  @moduledoc "Audit log compatibility writer."

  alias StonksBackend.Sql

  require Logger

  def write(action, opts \\ []) do
    user = Keyword.get(opts, :user)
    target_table = Keyword.get(opts, :target_table)
    target_pk = Keyword.get(opts, :target_pk)
    after_payload = Keyword.get(opts, :after, %{})

    Sql.execute(
      """
      insert into audit_log(actor_user_id, actor_role, action, target_table, target_pk, after_json)
      values ($1, $2, $3, $4, $5, $6::text::jsonb)
      """,
      [
        user && user[:id],
        user && user[:role],
        action,
        target_table,
        target_pk,
        Jason.encode!(after_payload || %{})
      ]
    )
  rescue
    _ ->
      Logger.error("Audit log persistence failed action=#{action}")
      {:error, :storage_unavailable}
  end
end
