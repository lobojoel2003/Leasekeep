# Contributing to Leasekeep

Thanks for helping community land trusts keep homes affordable. Bug reports, fixes, new
formula options, reports your funders ask for and documentation are all welcome.

## Set up

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python manage.py migrate
python manage.py seed_demo --with-users
python manage.py runserver
```

Sign in as `staff` / `leasekeep-demo`, or as the homeowner
`ana.rivera@riverbendclt.example` / `leasekeep-demo`.

## Before you open a pull request

```bash
ruff format .
ruff check .
pytest
python manage.py makemigrations --check --dry-run
```

- Add or update tests with every change. Formula changes need an engine test, ideally one
  that reproduces a published example with a citation in its docstring.
- Keep the formula engine (`leasekeep/formulas/engine.py`) free of Django imports.
- Money is `Decimal`, never `float`.
- Homeowners must only ever see their own household's records. Add a test when you touch the
  portal.
- Describe user-visible changes under `## [Unreleased]` in `CHANGELOG.md`.
- If you change a screen shown in the README, regenerate the screenshots with `make screenshots`.

## Releasing (maintainers)

1. Move the `[Unreleased]` notes into a new `## [x.y.z] - YYYY-MM-DD` section of
   `CHANGELOG.md` and update the links at the bottom.
2. Set `__version__` in `leasekeep/__init__.py` to `x.y.z`.
3. Merge to `main`, then push a tag: `git tag -a vx.y.z -m "Leasekeep vx.y.z" && git push origin vx.y.z`.

The release workflow checks the tag against the version and changelog, runs the tests,
publishes the image to GHCR and creates the GitHub Release.

## Code of conduct

Everyone taking part is expected to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
