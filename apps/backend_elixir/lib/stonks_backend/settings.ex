defmodule StonksBackend.Settings do
  @moduledoc "Runtime configuration helpers that preserve the existing environment contract."

  def get(key, default \\ nil) do
    :stonks_backend
    |> Application.get_env(:settings, [])
    |> Keyword.get(key, default)
  end

  def production? do
    get(:app_env, "development")
    |> String.downcase()
    |> Kernel.in(["production", "prod"])
  end

  def cors_origins do
    base = [get(:public_base_url, "http://localhost:5173")]

    extras =
      if production?() do
        []
      else
        get(:dev_cors_origins, "")
        |> split_csv()
      end

    (base ++ extras)
    |> Enum.reject(&(&1 in [nil, ""]))
    |> Enum.uniq()
  end

  def google_oauth_enabled? do
    truthy?(get(:google_oauth_admin_enabled, "false")) and
      present?(get(:google_oauth_client_id)) and
      present?(get(:google_oauth_client_secret))
  end

  def yahoo_admin_enabled?, do: truthy?(get(:yahoo_admin_enabled, "false"))

  def google_allowed_emails do
    emails = split_csv(get(:google_oauth_allowed_emails, ""))
    admin_email = get(:admin_email, "owner@example.com") |> String.downcase()
    Enum.uniq([admin_email | emails])
  end

  def google_allowed_domains do
    get(:google_oauth_allowed_domains, "")
    |> split_csv()
    |> Enum.map(&String.trim_leading(&1, "@"))
  end

  def split_csv(value) when is_binary(value) do
    value
    |> String.split(",", trim: true)
    |> Enum.map(&String.trim/1)
    |> Enum.reject(&(&1 == ""))
  end

  def split_csv(_), do: []

  def truthy?(value) when is_binary(value),
    do: String.downcase(value) in ["1", "true", "yes", "on"]

  def truthy?(value), do: value in [true, 1]

  def present?(value), do: is_binary(value) and String.trim(value) != ""
end
