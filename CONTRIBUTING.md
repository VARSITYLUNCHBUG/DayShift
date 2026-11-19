# Contributing

Thanks for helping. Bug reports, fixes and features are all welcome. For anything big, open an
issue first so we can agree on the approach before you spend time on it.

## Getting set up

The [developer guide](docs/dev/README.md) covers everything: the dev stack against a Discord
simulator (`make dev`), the control panel, the tests and cleaning up. You need Linux with Docker,
make and [uv](https://docs.astral.sh/uv/); on Windows, `scripts\dev-vm.ps1` makes a Multipass VM
with all of them. Run `make setup` once, so the checks run before each commit.

## Making a change

- Branch from `main`, and keep one feature or fix per pull request.
- Write focused commits whose messages say what they change ("Add ...", "Fix ...").
- Add or update tests with the change: `tests/` for the bot and web app,
  `services/discord-sim/tests/` for the simulator, and `tests/e2e/` for flows players see.
- A model change needs its migration, and a new model needs rows in `fixtures/dev` (or a
  written reason it can't have any): see [models and fixtures](docs/dev/README.md#models-and-fixtures).
- Update the docs your change affects: the page under `docs/` that covers it (the
  [index](docs/README.md) lists them), the [deploy guide](deploy/README.md) for hosting, and the
  [wiki](https://github.com/VARSITYLUNCHBUG/DayShift/wiki) if players see the change. Keep
  `README.md` short: it's the landing page, not the reference.
- Never commit secrets, real tokens, `.env` files or server inventories. Secret scanning blocks
  pushes that contain known token formats, but don't rely on it.
- `.gitattributes` sets line endings; leave them as they are.

Before you open the pull request, run the checks CI runs:
[checks and tests](docs/dev/README.md#checks-and-tests).

## Review

- CI runs on your pull request once the maintainer approves the workflow run. GitHub asks for that
  for every outside contributor, so nobody's code runs in CI unseen.
- A pull request merges when the `CI OK` check passes, the maintainer has approved it and every
  review thread is resolved. Pushing new commits after an approval dismisses it.
- Pull requests merge with a merge commit, so your commits land as you wrote them.

## Security problems

Don't open an issue or a pull request; follow [SECURITY.md](SECURITY.md).

## License

By contributing, you agree that your contributions are licensed under the
[Apache License 2.0](LICENSE), the same as the rest of the project.
