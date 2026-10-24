# Contributing

Small, tested changes are welcome. Open an issue describing the expected behavior, a minimal reproducer, and your Python/OS versions. Do not include credentials, private cluster paths, or unpublished datasets.

## Development

```bash
python -m venv .venv
# Activate the environment for your shell.
python -m pip install -e ".[plots]"
python -m unittest discover -s tests -v
```

The core has no third-party runtime dependencies. Keep it that way unless a dependency removes substantial complexity. Tests use `unittest`; rendering tests run when Matplotlib is installed. CI exercises Python 3.11-3.14 on Linux and Windows, including the command-line quickstart.

## Before a Pull Request

- Add a regression test for a bug fix or a focused test for new behavior.
- Preserve deterministic task identities and exact checkpoint replay. A change to the sampling algorithm requires a new engine version and explicit compatibility documentation.
- Do not weaken validation to accept incomplete results.
- Do not add automatic job submission, unconditional retries, or automatic stale-lock removal.
- Keep generated run directories out of Git. Documentation figures must come from the public example and include a reproducible configuration.
- Update the CLI or workflow documentation when behavior changes.

Contributions are provided under this repository's MIT license. Submit only material you are authorized to share.
