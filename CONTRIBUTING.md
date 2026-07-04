# Contributing

Thanks for considering a contribution to Token Triage.

## License

This project is licensed under [Apache-2.0](LICENSE). By submitting a
contribution, you agree that it is licensed under the same terms.

## Developer Certificate of Origin (DCO)

All commits must be signed off, certifying you wrote the contribution or
otherwise have the right to submit it under the project's license (the
[Developer Certificate of Origin](https://developercertificate.org/)).

Add a `Signed-off-by` line to every commit:

```
Signed-off-by: Your Name <your.email@example.com>
```

`git commit -s` adds this automatically. PRs with unsigned commits will be
asked to amend before merge.

## Getting started

```bash
git clone https://github.com/cursed180/Cursed_Token_Triage
cd Cursed_Token_Triage
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest
ruff check .
ruff format --check .
python scripts/privacy_scrub.py
```

See the README's "Privacy" section for what the privacy scrub enforces, and
`scripts/privacy_scrub.py` for the checks that run in CI and as a pre-commit
hook.

## Pull requests

- Keep PRs focused — one change per PR is easier to review and revert.
- Add or update tests for behavior changes.
- Run the checks above locally before opening the PR; CI runs the same ones.
