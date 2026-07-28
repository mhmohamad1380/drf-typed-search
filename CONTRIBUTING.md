# Contributing

Thanks for your interest in improving **drf-typed-search**!

## Development setup

```bash
git clone https://github.com/mhmohamad1380/drf-typed-search
cd drf-typed-search
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Quality gates

All PRs must pass:

```bash
ruff check .          # lint
black --check .       # format
mypy                  # types (strict)
pytest                # tests
```

Run everything at once:

```bash
make check   # if you use the Makefile, otherwise run the commands above
```

## Testing

- Tests live in `tests/` and run against SQLite by default.
- To exercise PostgreSQL-specific paths and benchmarks:

  ```bash
  DYNAMIC_SEARCH_TEST_DB=postgres pytest -m benchmark
  ```

- Please keep coverage **> 95%** and add regression tests for bug fixes.

## Design principles

Please respect the architecture:

- **No business-specific logic** in the package (no baked-in regexes).
- **Open/Closed**: new matchers are added via settings, never by editing source.
- **Low coupling**: only `backend.py` may import DRF; `engine.py` stays framework-agnostic.
- **Strong typing**: everything is typed; `mypy --strict` must pass.

## Commit & release

- Use clear, conventional commit messages.
- Update `CHANGELOG.md` under `[Unreleased]`.
- Releases follow [SemVer](https://semver.org/); maintainers tag `vX.Y.Z`,
  which triggers the publish workflow.

## Reporting bugs

Open an issue with a minimal reproducible example (models, config, query, and
the observed vs. expected SQL/results).
