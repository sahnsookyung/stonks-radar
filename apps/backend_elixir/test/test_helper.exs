excluded_tags =
  if System.get_env("RUN_DB_TESTS") == "true" do
    []
  else
    [db: true]
  end

ExUnit.start(exclude: excluded_tags)
