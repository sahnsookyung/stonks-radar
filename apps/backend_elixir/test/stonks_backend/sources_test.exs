defmodule StonksBackend.SourcesTest do
  use ExUnit.Case, async: true

  alias StonksBackend.Sources

  test "metadata dedupe key is canonical across discovery providers" do
    gdelt = %{
      "url" => "HTTPS://Example.COM/markets/rocket-lab-acquisition/amp?utm_source=gdelt",
      "dedupe_key" => "gdelt:doc:abc"
    }

    rss = %{
      "canonical_url" => "https://example.com/markets/rocket-lab-acquisition?utm_campaign=rss",
      "dedupe_key" => "google_news_RKLB:def"
    }

    assert Sources.metadata_dedupe_key(gdelt) == Sources.metadata_dedupe_key(rss)
    assert String.starts_with?(Sources.metadata_dedupe_key(gdelt), "news:url:")
  end

  test "metadata dedupe key falls back when no public canonical URL exists" do
    assert Sources.metadata_dedupe_key(%{"title" => "No URL", "dedupe_key" => "source:123"}) ==
             "source:123"
  end
end
