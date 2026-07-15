defmodule StonksBackend.WatchedRegionsTest do
  use ExUnit.Case, async: true

  alias StonksBackend.WatchedRegions

  test "top-30 GDP countries are tracked as country rows" do
    top30 =
      WatchedRegions.all()
      |> Enum.filter(&(&1["type"] == "country" and "top30_gdp" in (&1["groups"] || [])))

    assert length(top30) == 30
    assert "USA" in Enum.map(top30, & &1["key"])
    assert "CHN" in Enum.map(top30, & &1["key"])
    assert "DEU" in Enum.map(top30, & &1["key"])
  end

  test "map-rendered watched countries include Natural Earth names" do
    missing =
      WatchedRegions.render_on_map()
      |> Enum.filter(&(&1["type"] == "country"))
      |> Enum.reject(&match?([_ | _], &1["natural_earth_names"]))

    assert missing == []
  end

  test "every map-rendered region has authoritative coordinates" do
    map_areas = Map.new(WatchedRegions.map_areas(), &{&1["key"], &1})

    missing =
      WatchedRegions.render_on_map()
      |> Enum.reject(fn region ->
        case map_areas[region["key"]] do
          %{"latitude" => latitude, "longitude" => longitude} ->
            is_number(latitude) and is_number(longitude)

          _ ->
            false
        end
      end)
      |> Enum.map(& &1["key"])

    assert missing == []
    assert map_areas["AUS"]["latitude"] == -25.2744
  end

  test "news-gathered regions include GDELT terms" do
    missing =
      WatchedRegions.gather_news()
      |> Enum.reject(&match?([_ | _], &1["gdelt_terms"]))

    assert missing == []
  end

  test "tracked GDELT terms come from the registry" do
    terms = WatchedRegions.tracked_country_terms()

    assert ~s("United States") in terms
    assert "China" in terms
    assert "Norway" in terms
    assert ~s("South Africa") in terms
  end

  test "region keyword entries expose normalized searchable aliases" do
    entries = WatchedRegions.region_keyword_entries()
    usa = Enum.find(entries, &(&1.key == "USA"))

    assert usa
    assert "united states" in usa.keywords
    assert "usa" in usa.keywords
    assert "federal reserve" in usa.keywords
    refute Enum.any?(usa.keywords, &String.contains?(&1, "\""))

    japan = Enum.find(entries, &(&1.key == "JPN"))
    assert "bank of japan" in japan.keywords

    norway = Enum.find(entries, &(&1.key == "NOR"))
    assert "norges bank" in norway.keywords
  end
end
