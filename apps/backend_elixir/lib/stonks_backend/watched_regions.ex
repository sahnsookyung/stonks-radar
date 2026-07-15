defmodule StonksBackend.WatchedRegions do
  @moduledoc "Versioned watched-region registry shared by news collection, snapshots, and map coverage."

  @repo_root Path.expand("../../../..", __DIR__)
  @default_path Path.join([@repo_root, "packages", "shared-config", "watched-regions.json"])

  @default_map_path Path.join([
                      @repo_root,
                      "packages",
                      "shared-config",
                      "geopolitical-watch-registry.json"
                    ])

  def all do
    registry()
    |> Map.get("regions", [])
  end

  def version do
    registry()
    |> Map.get("version", 1)
  end

  def gather_news do
    Enum.filter(all(), &truthy?(&1["gather_news"]))
  end

  def render_on_map do
    Enum.filter(all(), &truthy?(&1["render_on_map"]))
  end

  def map_areas do
    map_registry()
    |> Map.get("areas", [])
  end

  def nav_visible do
    Enum.filter(all(), &truthy?(&1["nav_visible"]))
  end

  def tracked_country_terms do
    gather_news()
    |> Enum.flat_map(fn region -> region["gdelt_terms"] || [] end)
    |> Enum.reject(&(to_string(&1) == ""))
    |> Enum.uniq()
  end

  def region_keyword_entries do
    gather_news()
    |> Enum.map(fn region ->
      %{
        key: region["key"],
        keywords:
          [
            region["iso3"],
            get_in(region, ["display_names", "en"]),
            get_in(region, ["display_names", "ko"])
          ]
          |> Kernel.++(region["natural_earth_names"] || [])
          |> Kernel.++(region["gdelt_terms"] || [])
          |> Enum.map(&normalize_term/1)
          |> Enum.reject(&(&1 == ""))
          |> Enum.uniq()
      }
    end)
    |> Enum.reject(&(is_nil(&1.key) or &1.key == "" or &1.keywords == []))
  end

  def top30_keys do
    all()
    |> Enum.filter(fn region ->
      region["type"] == "country" and "top30_gdp" in (region["groups"] || [])
    end)
    |> Enum.map(& &1["key"])
  end

  defp registry do
    path = System.get_env("WATCHED_REGIONS_PATH", @default_path)

    path
    |> File.read!()
    |> Jason.decode!()
  end

  defp map_registry do
    path = System.get_env("GEOPOLITICAL_WATCH_REGISTRY_PATH", @default_map_path)

    path
    |> File.read!()
    |> Jason.decode!()
  end

  defp normalize_term(value) do
    value
    |> to_string()
    |> String.replace(~r/^"+|"+$/, "")
    |> String.trim()
    |> String.downcase()
  end

  defp truthy?(value), do: value in [true, "true", "1", 1]
end
