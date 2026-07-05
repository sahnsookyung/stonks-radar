defmodule StonksBackend.PortfolioWorkspaces do
  @moduledoc "Authenticated portfolio workspace persistence over a small JSONB document table."

  alias StonksBackend.Sql

  @portfolio_id_regex ~r/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/
  @storage_version 1
  @max_workspace_bytes 250_000

  def get(user_id, portfolio_id) do
    with {:ok, normalized_user_id} <- normalize_user_id(user_id),
         {:ok, normalized_portfolio_id} <- normalize_portfolio_id(portfolio_id) do
      row =
        Sql.one(
          """
          select portfolio_id, workspace, updated_at
          from portfolio_workspace
          where user_id = $1 and portfolio_id = $2
          """,
          [normalized_user_id, normalized_portfolio_id]
        )

      if row do
        {:ok,
         %{
           portfolio_id: row["portfolio_id"],
           workspace: decode_workspace(row["workspace"]),
           updated_at: row["updated_at"]
         }}
      else
        {:error, :not_found}
      end
    end
  end

  def put(user_id, portfolio_id, workspace) do
    with {:ok, normalized_user_id} <- normalize_user_id(user_id),
         {:ok, normalized_portfolio_id} <- normalize_portfolio_id(portfolio_id),
         {:ok, encoded_workspace} <- validate_workspace(workspace) do
      Sql.execute(
        """
        insert into portfolio_workspace(user_id, portfolio_id, workspace)
        values ($1, $2, $3::jsonb)
        on conflict (user_id, portfolio_id) do update
        set workspace = excluded.workspace,
            updated_at = now()
        """,
        [normalized_user_id, normalized_portfolio_id, encoded_workspace]
      )

      get(user_id, normalized_portfolio_id)
    end
  rescue
    _ -> {:error, :storage_unavailable}
  end

  defp normalize_user_id(user_id) when is_binary(user_id) and byte_size(user_id) == 16,
    do: {:ok, user_id}

  defp normalize_user_id(user_id) do
    case Ecto.UUID.cast(user_id) do
      {:ok, normalized} -> {:ok, Ecto.UUID.dump!(normalized)}
      :error -> {:error, :invalid_user}
    end
  end

  defp normalize_portfolio_id(portfolio_id) when is_binary(portfolio_id) do
    normalized = String.trim(portfolio_id)

    if Regex.match?(@portfolio_id_regex, normalized) do
      {:ok, normalized}
    else
      {:error, :invalid_portfolio_id}
    end
  end

  defp normalize_portfolio_id(_), do: {:error, :invalid_portfolio_id}

  defp validate_workspace(workspace) when is_map(workspace) do
    encoded = Jason.encode!(workspace)

    cond do
      byte_size(encoded) > @max_workspace_bytes ->
        {:error, :workspace_too_large}

      workspace["version"] != @storage_version ->
        {:error, :invalid_workspace}

      not is_map(workspace["portfolio"]) ->
        {:error, :invalid_workspace}

      not is_list(workspace["manualInstruments"] || []) ->
        {:error, :invalid_workspace}

      not is_list(workspace["reviewRequests"] || []) ->
        {:error, :invalid_workspace}

      not is_map(workspace["assumptions"] || %{}) ->
        {:error, :invalid_workspace}

      true ->
        {:ok, encoded}
    end
  rescue
    _ -> {:error, :invalid_workspace}
  end

  defp validate_workspace(_), do: {:error, :invalid_workspace}

  defp decode_workspace(workspace) when is_map(workspace), do: workspace

  defp decode_workspace(workspace) when is_binary(workspace) do
    case Jason.decode(workspace) do
      {:ok, decoded} when is_map(decoded) -> decoded
      _ -> %{}
    end
  end

  defp decode_workspace(_), do: %{}
end
