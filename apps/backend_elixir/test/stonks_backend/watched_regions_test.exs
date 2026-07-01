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
end
