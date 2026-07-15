defmodule StonksBackend.JsonbSqlContractTest do
  use ExUnit.Case, async: true

  test "encoded JSON parameters are parsed from text instead of double encoded" do
    lib_root = Path.expand("../../lib", __DIR__)

    offenders =
      lib_root
      |> Path.join("**/*.ex")
      |> Path.wildcard()
      |> Enum.flat_map(fn path ->
        path
        |> File.read!()
        |> String.split("\n")
        |> Enum.with_index(1)
        |> Enum.filter(fn {line, _line_number} ->
          Regex.match?(~r/\$\d+::jsonb/, line)
        end)
        |> Enum.map(fn {_line, line_number} -> "#{path}:#{line_number}" end)
      end)

    assert offenders == [],
           "JSON text parameters must use ::text::jsonb; invalid casts: #{Enum.join(offenders, ", ")}"
  end
end
