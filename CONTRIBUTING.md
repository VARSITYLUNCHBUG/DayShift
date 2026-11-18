# Contributing

Thanks for helping. Bug reports, fixes and features are all welcome. For anything big, open an
issue first so we can agree on the approach before you spend time on it.

## Getting set up

The [developer guide](docs/dev/README.md) covers everything: the dev stack against a Discord
simulator (`scripts/fixture_to_test.sh`), the control panel, the tests and cleaning up. You need
Docker and [uv](https://docs.astral.sh/uv/), plus Node 22 for the control panel. On Windows, each
script has a `.bat` twin.

## Making a change

- Branch from `main`, and keep one feature or fix per pull request.
- Write focused commits whose messages say what they change ("Add ...", "Fix ...").
- Add or update tests with the change: `tests/` for the bot and web app,
  `services/discord-sim/tests/` for the simulator, and `tests/e2e/` for flows players see.
- A model change needs its migration; see
  [writing a migration](docs/dev/README.md#writing-a-migration).
- Update the docs your change affects: `README.md` for players and admins, `docs/` for
  developers and operators.
- Never commit secrets, real tokens, `.env` files or server inventories. Secret scanning blocks
  pushes that contain known token formats, but don't rely on it.
- `.gitattributes` sets line endings; leave them as they are.

Before you open the pull request, run the checks CI runs:
[tests](docs/dev/README.md#tests) and [lint and type checks](docs/dev/README.md#lint-and-type-checks).

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
