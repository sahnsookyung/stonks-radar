defmodule StonksBackend.Snapshots.SchemaResolver do
  @moduledoc "JSV resolver for repo-local snapshot schemas."
  @behaviour JSV.Resolver

  @schema_base "https://stonks-radar.local/schemas/"

  def schema_base, do: @schema_base

  @impl JSV.Resolver
  def resolve(uri, schema_root) when is_binary(uri) do
    with {:ok, filename} <- schema_filename(uri),
         path = Path.join(to_string(schema_root), filename),
         true <- File.regular?(path),
         {:ok, content} <- File.read(path),
         {:ok, schema} <- Jason.decode(content) do
      {:ok, Map.put(schema, "$id", @schema_base <> filename)}
    else
      false -> {:error, {:snapshot_schema_missing, uri}}
      {:error, reason} -> {:error, reason}
    end
  end

  def resolve(_uri, _schema_root), do: {:error, :invalid_schema_uri}

  defp schema_filename(@schema_base <> filename), do: safe_schema_filename(filename)

  defp schema_filename(uri) do
    case URI.parse(uri) do
      %URI{scheme: nil, path: path} when is_binary(path) ->
        path |> Path.basename() |> safe_schema_filename()

      _ ->
        {:error, {:unsupported_schema_uri, uri}}
    end
  end

  defp safe_schema_filename(filename) do
    cond do
      filename in ["_envelope.schema.json", "_news.schema.json"] ->
        {:ok, filename}

      String.ends_with?(filename, "_snapshot.schema.json") ->
        {:ok, filename}

      true ->
        {:error, {:unsupported_snapshot_schema, filename}}
    end
  end
end
