defmodule StonksBackend.Instruments.Normalization do
  @moduledoc "Reference and query normalization helpers shared by instrument search, resolve, and provider lookup paths."

  def search_query(value) do
    value
    |> to_string()
    |> String.trim()
    |> String.downcase()
  end

  def symbol(nil), do: ""

  def symbol(value) do
    value
    |> to_string()
    |> String.upcase()
    |> String.replace(~r/[^A-Z0-9]/, "")
  end

  def provider_symbol_list(value) when is_list(value) do
    value
    |> Enum.map(&provider_symbol/1)
    |> Enum.reject(&blank?/1)
    |> Enum.uniq()
  end

  def provider_symbol_list(value) when is_binary(value) do
    value
    |> String.split(",", trim: true)
    |> provider_symbol_list()
  end

  def provider_symbol_list(_value), do: []

  def provider_symbol(value) do
    value
    |> to_string()
    |> String.trim()
    |> String.upcase()
    |> String.replace(~r/[^A-Z0-9.\-]/, "")
  end

  defp blank?(nil), do: true
  defp blank?(value) when is_binary(value), do: String.trim(value) == ""
  defp blank?(_value), do: false
end
