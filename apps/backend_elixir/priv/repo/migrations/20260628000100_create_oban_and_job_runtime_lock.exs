defmodule StonksBackend.Repo.Migrations.CreateObanAndJobRuntimeLock do
  use Ecto.Migration

  def up do
    Oban.Migration.up(version: 12)

    create table(:job_runtime_lock, primary_key: false) do
      add :scope_type, :text, null: false
      add :scope_key, :text, null: false
      add :owner, :text, null: false
      add :lease_expires_at, :utc_datetime_usec, null: false
      add :metadata, :map, null: false, default: %{}
      timestamps(type: :utc_datetime_usec)
    end

    create unique_index(:job_runtime_lock, [:scope_type, :scope_key],
             name: :job_runtime_lock_scope_unique
           )

    create index(:job_runtime_lock, [:lease_expires_at], name: :job_runtime_lock_expiry_idx)
    create index(:job_runtime_lock, [:owner], name: :job_runtime_lock_owner_idx)

    create constraint(:job_runtime_lock, :job_runtime_lock_scope_type_check,
             check: "scope_type in ('provider','source','global')"
           )
  end

  def down do
    drop_if_exists constraint(:job_runtime_lock, :job_runtime_lock_scope_type_check)

    drop_if_exists index(:job_runtime_lock, [:owner], name: :job_runtime_lock_owner_idx)

    drop_if_exists index(:job_runtime_lock, [:lease_expires_at],
                     name: :job_runtime_lock_expiry_idx
                   )

    drop_if_exists index(:job_runtime_lock, [:scope_type, :scope_key],
                     name: :job_runtime_lock_scope_unique
                   )

    drop table(:job_runtime_lock)

    Oban.Migration.down(version: 12)
  end
end
