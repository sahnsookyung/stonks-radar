defmodule StonksBackend.Snapshots.PublicGuards do
  @moduledoc "Compatibility guards that keep public snapshot payloads free of raw private data and seed-only display text."

  @prohibited_public_fields [
    "api_key",
    "api_key_name",
    "article_body",
    "body_text",
    "credential_status",
    "db_id",
    "document_id",
    "environment_variable",
    "full_text",
    "fact_id",
    "full_article_text",
    "html",
    "internal_id",
    "llm_prompt",
    "private_note",
    "prompt",
    "prompt_text",
    "provider_budget",
    "provider_internal",
    "provider_status",
    "quota_state",
    "raw_html",
    "raw_payload",
    "raw_response",
    "restricted_source_text",
    "secret",
    "source_document_id"
  ]

  @public_placeholder_guard_keys [
    "catalyst_type",
    "description",
    "detail",
    "label",
    "methodology",
    "one_sentence_summary",
    "overview",
    "reasoning",
    "risk_summary",
    "source",
    "source_note",
    "source_strength",
    "summary",
    "thesis",
    "title",
    "value"
  ]

  def assert_no_raw_private(value, path) when is_map(value) do
    Enum.reduce_while(value, :ok, fn {key, nested}, :ok ->
      if String.downcase(to_string(key)) in @prohibited_public_fields do
        {:halt, {:error, "#{path} contains prohibited public field #{key}"}}
      else
        case assert_no_raw_private(nested, path) do
          :ok -> {:cont, :ok}
          {:error, reason} -> {:halt, {:error, reason}}
        end
      end
    end)
  end

  def assert_no_raw_private(value, path) when is_list(value) do
    Enum.reduce_while(value, :ok, fn nested, :ok ->
      case assert_no_raw_private(nested, path) do
        :ok -> {:cont, :ok}
        {:error, reason} -> {:halt, {:error, reason}}
      end
    end)
  end

  def assert_no_raw_private(_value, _path), do: :ok

  def scrub_placeholder_metadata(value), do: scrub_placeholder_metadata(value, nil)

  defp scrub_placeholder_metadata(value, _key) when is_map(value) do
    Map.new(value, fn {key, nested} -> {key, scrub_placeholder_metadata(nested, key)} end)
  end

  defp scrub_placeholder_metadata(value, _key) when is_list(value) do
    Enum.map(value, &scrub_placeholder_metadata(&1, nil))
  end

  defp scrub_placeholder_metadata(value, key) when is_binary(value) do
    cond do
      id_like_key?(key) or url_like_key?(key) ->
        value

      source_policy_key?(key) and value == "seed" ->
        "snapshot"

      key_string(key) == "source_strength" ->
        value
        |> String.replace("_seed", "")
        |> scrub_placeholder_text()

      true ->
        scrub_placeholder_text(value)
    end
  end

  defp scrub_placeholder_metadata(value, _key), do: value

  def assert_no_placeholder_display_terms(value, path),
    do: assert_no_placeholder_display_terms(value, path, nil)

  defp assert_no_placeholder_display_terms(value, path, _key) when is_map(value) do
    Enum.reduce_while(value, :ok, fn {key, nested}, :ok ->
      case assert_no_placeholder_display_terms(nested, path, key) do
        :ok -> {:cont, :ok}
        {:error, reason} -> {:halt, {:error, reason}}
      end
    end)
  end

  defp assert_no_placeholder_display_terms(value, path, _key) when is_list(value) do
    Enum.reduce_while(value, :ok, fn nested, :ok ->
      case assert_no_placeholder_display_terms(nested, path, nil) do
        :ok -> {:cont, :ok}
        {:error, reason} -> {:halt, {:error, reason}}
      end
    end)
  end

  defp assert_no_placeholder_display_terms(value, path, key) when is_binary(value) do
    if placeholder_guard_key?(key) and placeholder_display_text?(value) do
      {:error, "#{path} contains prohibited placeholder display text in #{key}"}
    else
      :ok
    end
  end

  defp assert_no_placeholder_display_terms(_value, _path, _key), do: :ok

  defp scrub_placeholder_text(value) do
    value
    |> replace_text(~r/\bcurrent seed snapshot\b/i, "current public snapshot")
    |> replace_text(~r/\bseed snapshot\b/i, "public snapshot")
    |> replace_text(~r/\bThe seed event demonstrates\b/i, "This source-linked item shows")
    |> replace_text(~r/\bseed event\b/i, "source-linked item")
    |> replace_text(~r/\bSource policy seed\b/i, "Source policy")
    |> replace_text(~r/\bapproved,\s*source-linked news event\(s\)/i, "source-linked item(s)")
    |> replace_text(~r/\bsource-linked news event\(s\)/i, "source-linked item(s)")
    |> replace_text(~r/\bsource-linked news events\b/i, "source-linked items")
    |> String.replace("reviewed_structured_seed", "reviewed_structured")
    |> String.replace("official_calendar_seed", "official_calendar")
    |> String.replace("unrelated fallback events", "unrelated substitute items")
  end

  defp replace_text(value, pattern, replacement), do: Regex.replace(pattern, value, replacement)

  defp placeholder_display_text?(value) do
    Regex.match?(
      ~r/\b(seed snapshot|current seed snapshot|seed event|Source policy seed|GDELT event|GDELT GKG)\b|reviewed_structured_seed|official_calendar_seed/i,
      value
    ) or Regex.match?(~r/\bsource-linked news event(?:\(s\)|s)?\b/i, value)
  end

  defp placeholder_guard_key?(key), do: key_string(key) in @public_placeholder_guard_keys

  defp id_like_key?(key),
    do: key_string(key) in ["id", "object_key", "event_id", "dedupe_key", "job_id"]

  defp source_policy_key?(key), do: key_string(key) in ["source_key", "source_policy_key"]

  defp url_like_key?(key) do
    key = key_string(key)
    String.ends_with?(key, "_url") or String.ends_with?(key, "_path")
  end

  defp key_string(key) when is_binary(key), do: key
  defp key_string(key) when is_atom(key), do: Atom.to_string(key)
  defp key_string(key), do: to_string(key)
end
