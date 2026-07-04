defmodule StonksBackend.Sql do
  @moduledoc "Small raw-SQL helpers for preserved-schema compatibility."

  alias StonksBackend.Repo

  def all(sql, params \\ %{}) do
    Repo
    |> Ecto.Adapters.SQL.query!(sql, named_params(params))
    |> rows_to_maps()
  rescue
    _ -> []
  end

  def one(sql, params \\ %{}) do
    sql
    |> all(params)
    |> List.first()
  end

  def scalar(sql, params \\ %{}, default \\ nil) do
    result = Ecto.Adapters.SQL.query!(Repo, sql, named_params(params))

    case result.rows do
      [[value | _] | _] -> value || default
      _ -> default
    end
  rescue
    _ -> default
  end

  def execute(sql, params \\ %{}) do
    Ecto.Adapters.SQL.query!(Repo, sql, named_params(params))
  end

  defp rows_to_maps(%Postgrex.Result{columns: columns, rows: rows}) do
    Enum.map(rows, fn row ->
      columns
      |> Enum.zip(row)
      |> Map.new(fn {key, value} -> {key, normalize(value)} end)
    end)
  end

  defp rows_to_maps(%{columns: columns, rows: rows}) do
    Enum.map(rows, fn row ->
      columns
      |> Enum.zip(row)
      |> Map.new(fn {key, value} -> {key, normalize(value)} end)
    end)
  end

  defp normalize(%Decimal{} = decimal), do: Decimal.to_string(decimal)
  defp normalize(%DateTime{} = dt), do: DateTime.to_iso8601(dt)
  defp normalize(%NaiveDateTime{} = dt), do: NaiveDateTime.to_iso8601(dt)
  defp normalize(%Date{} = date), do: Date.to_iso8601(date)
  defp normalize(%Time{} = time), do: Time.to_iso8601(time)
  defp normalize(value), do: value

  defp named_params(params) when is_map(params) do
    Enum.map(params, fn {_key, value} -> value end)
  end

  defp named_params(params), do: params
end
