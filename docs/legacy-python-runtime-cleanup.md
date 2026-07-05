# Legacy Python Runtime Cleanup

Stonks Radar now treats `apps/backend_elixir` as the only runtime backend. The old Python `apps/api` and `apps/worker` trees are not part of the tracked runtime, CI, compose, deploy, or snapshot-publish path.

Local residue that may still appear under those paths is generated development output only:

- `apps/api/.venv/`
- `apps/worker/.venv/`
- `apps/api/src/*.egg-info/`
- `apps/worker/src/*.egg-info/`

Those files are ignored by `.gitignore` and can be deleted locally. Do not add new tracked runtime code under `apps/api` or `apps/worker`; backend work should go through Phoenix/Ecto/Oban in `apps/backend_elixir`.

The contract test suite pins this boundary by rejecting tracked files under the retired Python runtime roots and by asserting CI/deploy/compose do not reference Python backend images or scripts.
