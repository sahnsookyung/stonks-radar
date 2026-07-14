defmodule StonksBackend.InstrumentCacheTest do
  use ExUnit.Case, async: false

  alias StonksBackend.InstrumentCache

  setup do
    InstrumentCache.invalidate_index()
    on_exit(&InstrumentCache.invalidate_index/0)
    :ok
  end

  test "owns the index across callers until invalidated" do
    parent = self()

    assert {[:built], :miss} =
             InstrumentCache.fetch_index(300_000, fn ->
               send(parent, :built)
               [:built]
             end)

    assert_receive :built

    task = Task.async(fn -> InstrumentCache.fetch_index(300_000, fn -> [:unexpected] end) end)
    assert Task.await(task) == {[:built], :hit}

    InstrumentCache.invalidate_index()
    assert {[:rebuilt], :miss} = InstrumentCache.fetch_index(300_000, fn -> [:rebuilt] end)
  end

  test "removes expired provider entries without losing supervised ownership" do
    now = System.monotonic_time(:millisecond)
    assert :ok = InstrumentCache.put_provider({:test, now}, now - 1, [])
    assert :ok = InstrumentCache.cleanup()
    assert Process.alive?(Process.whereis(InstrumentCache))
    assert InstrumentCache.stats().provider_entries >= 0
  end
end
