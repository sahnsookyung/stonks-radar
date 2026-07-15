defmodule StonksBackend.Repo.Migrations.AllowFractionalFinraDailyVolume do
  use Ecto.Migration

  @fields ~w(short_volume short_exempt_volume total_volume)

  def up do
    set_field_types("number")
  end

  def down do
    set_field_types("integer")
  end

  defp set_field_types(type) do
    Enum.each(@fields, fn field ->
      execute("""
      update fact_type_registry
      set json_schema = jsonb_set(
        json_schema,
        '{properties,#{field},type}',
        '"#{type}"'::jsonb,
        true
      )
      where fact_type = 'short_volume'
      """)
    end)
  end
end
