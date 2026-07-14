defmodule StonksBackend.TickerWorkspaces do
  @moduledoc "Versioned, user-owned ticker workspaces with bounded merge semantics."

  alias StonksBackend.Sql

  @max_watchlist 100
  @max_notes 500
  @max_note_chars 20_000
  @max_comparisons 50
  @max_comparison_symbols 4
  @max_bytes 500_000
  @symbol_regex ~r/^[A-Z0-9.\-]{1,16}$/
  @id_regex ~r/^[A-Za-z0-9._:-]{1,80}$/

  def empty_workspace do
    %{"version" => 1, "watchlist" => [], "notes" => %{}, "comparisons" => []}
  end

  def get(user_id) do
    case Sql.one(
           "select revision, workspace, updated_at from ticker_workspace where user_id = $1",
           [user_id]
         ) do
      nil -> {:ok, %{revision: 0, workspace: empty_workspace(), updated_at: nil}}
      row -> {:ok, workspace_payload(row)}
    end
  rescue
    _ -> {:error, :storage_unavailable}
  end

  def put(user_id, workspace, expected_revision) do
    with {:ok, normalized} <- validate(workspace),
         true <- is_integer(expected_revision) and expected_revision >= 0 do
      row =
        Sql.one(
          """
          insert into ticker_workspace(user_id, revision, workspace)
          select $1, 1, $2::jsonb
          where $3 = 0
          on conflict (user_id) do update set
            revision = ticker_workspace.revision + 1,
            workspace = excluded.workspace,
            updated_at = now()
          where ticker_workspace.revision = $3
          returning revision, workspace, updated_at
          """,
          [user_id, Jason.encode!(normalized), expected_revision]
        )

      if row do
        {:ok, workspace_payload(row)}
      else
        case get(user_id) do
          {:ok, current} -> {:error, :conflict, current}
          error -> error
        end
      end
    else
      false -> {:error, :invalid_revision}
      {:error, reason} -> {:error, reason}
    end
  rescue
    _ -> {:error, :storage_unavailable}
  end

  def merge(user_id, local_workspace, expected_revision) do
    with {:ok, current} <- get(user_id),
         true <- current.revision == expected_revision,
         {:ok, merged} <- merge_workspaces(current.workspace, local_workspace) do
      put(user_id, merged, current.revision)
    else
      false ->
        case get(user_id) do
          {:ok, current} -> {:error, :conflict, current}
          error -> error
        end

      {:error, reason} ->
        {:error, reason}
    end
  end

  def validate(workspace) when is_map(workspace) do
    normalized = normalize_workspace(workspace)

    cond do
      normalized["version"] != 1 -> {:error, :invalid_workspace}
      length(normalized["watchlist"]) > @max_watchlist -> {:error, :watchlist_limit}
      map_size(normalized["notes"]) > @max_notes -> {:error, :notes_limit}
      length(normalized["comparisons"]) > @max_comparisons -> {:error, :comparisons_limit}
      Enum.any?(normalized["watchlist"], &(not valid_symbol?(&1))) -> {:error, :invalid_symbol}
      invalid_notes?(normalized["notes"]) -> {:error, :invalid_notes}
      invalid_comparisons?(normalized["comparisons"]) -> {:error, :invalid_comparisons}
      byte_size(Jason.encode!(normalized)) > @max_bytes -> {:error, :workspace_too_large}
      true -> {:ok, normalized}
    end
  rescue
    _ -> {:error, :invalid_workspace}
  end

  def validate(_workspace), do: {:error, :invalid_workspace}

  def merge_workspaces(server, local) do
    with {:ok, server} <- validate(server),
         {:ok, local} <- validate(local) do
      merged = %{
        "version" => 1,
        "watchlist" => Enum.uniq(server["watchlist"] ++ local["watchlist"]),
        "notes" => merge_notes(server["notes"], local["notes"]),
        "comparisons" => merge_comparisons(server["comparisons"], local["comparisons"])
      }

      validate(merged)
    end
  end

  defp normalize_workspace(workspace) do
    %{
      "version" => workspace["version"] || workspace[:version],
      "watchlist" => normalize_watchlist(workspace["watchlist"] || workspace[:watchlist]),
      "notes" => normalize_notes(workspace["notes"] || workspace[:notes]),
      "comparisons" => normalize_comparisons(workspace["comparisons"] || workspace[:comparisons])
    }
  end

  defp normalize_watchlist(value) when is_list(value) do
    value
    |> Enum.map(&normalize_symbol/1)
    |> Enum.reject(&(&1 == ""))
    |> Enum.uniq()
  end

  defp normalize_watchlist(_value), do: []

  defp normalize_notes(value) when is_map(value) do
    value
    |> Enum.map(fn {symbol, note} -> {normalize_symbol(symbol), normalize_note(note)} end)
    |> Enum.reject(fn {symbol, _note} -> symbol == "" end)
    |> Map.new()
  end

  defp normalize_notes(_value), do: %{}

  defp normalize_note(value) when is_binary(value),
    do: %{"content" => value, "updated_at" => nil, "conflicts" => []}

  defp normalize_note(value) when is_map(value) do
    %{
      "content" => to_string(value["content"] || value[:content] || ""),
      "updated_at" => nullable_text(value["updated_at"] || value[:updated_at]),
      "conflicts" => normalize_conflicts(value["conflicts"] || value[:conflicts])
    }
  end

  defp normalize_note(_value), do: %{"content" => "", "updated_at" => nil, "conflicts" => []}

  defp normalize_conflicts(value) when is_list(value) do
    value
    |> Enum.filter(&is_map/1)
    |> Enum.take(20)
    |> Enum.map(fn conflict ->
      %{
        "content" => to_string(conflict["content"] || conflict[:content] || ""),
        "updated_at" => nullable_text(conflict["updated_at"] || conflict[:updated_at]),
        "source" => "merge"
      }
    end)
  end

  defp normalize_conflicts(_value), do: []

  defp normalize_comparisons(value) when is_list(value) do
    value
    |> Enum.filter(&is_map/1)
    |> Enum.map(fn comparison ->
      %{
        "id" => to_string(comparison["id"] || comparison[:id] || ""),
        "symbols" => normalize_watchlist(comparison["symbols"] || comparison[:symbols]),
        "updated_at" => nullable_text(comparison["updated_at"] || comparison[:updated_at])
      }
    end)
  end

  defp normalize_comparisons(_value), do: []

  defp invalid_notes?(notes) do
    Enum.any?(notes, fn {symbol, note} ->
      not valid_symbol?(symbol) or String.length(note["content"]) > @max_note_chars or
        Enum.any?(note["conflicts"], &(String.length(&1["content"]) > @max_note_chars))
    end)
  end

  defp invalid_comparisons?(comparisons) do
    Enum.any?(comparisons, fn comparison ->
      not Regex.match?(@id_regex, comparison["id"]) or comparison["symbols"] == [] or
        length(comparison["symbols"]) > @max_comparison_symbols or
        Enum.any?(comparison["symbols"], &(not valid_symbol?(&1)))
    end)
  end

  defp merge_notes(server, local) do
    Map.merge(server, local, fn _symbol, server_note, local_note ->
      cond do
        server_note["content"] == local_note["content"] ->
          newer_note(server_note, local_note)

        newer?(local_note["updated_at"], server_note["updated_at"]) ->
          with_conflict(local_note, server_note)

        true ->
          with_conflict(server_note, local_note)
      end
    end)
  end

  defp newer_note(left, right),
    do: if(newer?(right["updated_at"], left["updated_at"]), do: right, else: left)

  defp with_conflict(primary, older) do
    conflict = %{
      "content" => older["content"],
      "updated_at" => older["updated_at"],
      "source" => "merge"
    }

    Map.put(
      primary,
      "conflicts",
      Enum.uniq([conflict | primary["conflicts"] ++ older["conflicts"]]) |> Enum.take(20)
    )
  end

  defp merge_comparisons(server, local) do
    (server ++ local)
    |> Enum.reduce(%{}, fn comparison, acc ->
      Map.update(acc, comparison["id"], comparison, fn existing ->
        if newer?(comparison["updated_at"], existing["updated_at"]),
          do: comparison,
          else: existing
      end)
    end)
    |> Map.values()
    |> Enum.sort_by(& &1["id"])
  end

  defp newer?(nil, nil), do: false
  defp newer?(value, nil), do: is_binary(value)
  defp newer?(nil, _value), do: false

  defp newer?(left, right) do
    with {:ok, left, _} <- DateTime.from_iso8601(left),
         {:ok, right, _} <- DateTime.from_iso8601(right) do
      DateTime.compare(left, right) == :gt
    else
      _ -> left > right
    end
  end

  defp normalize_symbol(value), do: value |> to_string() |> String.trim() |> String.upcase()
  defp valid_symbol?(symbol), do: is_binary(symbol) and Regex.match?(@symbol_regex, symbol)
  defp nullable_text(nil), do: nil
  defp nullable_text(value), do: value |> to_string() |> String.slice(0, 64)

  defp workspace_payload(row) do
    %{
      revision: to_integer(row["revision"]),
      workspace: row["workspace"],
      updated_at: row["updated_at"]
    }
  end

  defp to_integer(value) when is_integer(value), do: value
  defp to_integer(value) when is_binary(value), do: String.to_integer(value)
end
