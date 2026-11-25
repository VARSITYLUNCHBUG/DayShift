"""Open voice must allow the configured PUG role, not just @everyone."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from tests.test_postmatch import _fake_guild, _gateway


@pytest.mark.parametrize("opened", [False, True])
def test_pooled_voice_sets_pug_connect_to_match_open_setting(opened: bool) -> None:
    gateway = _gateway()
    gateway._set_role_overwrites = AsyncMock()
    asyncio.run(gateway.show_voice_channel(1, 100, opened, viewer_role_ids=[30]))
    overwrites = gateway._set_role_overwrites.call_args.args[1]
    assert overwrites[30].view_channel is True
    assert overwrites[30].connect is opened
    assert overwrites[1].connect is opened


@pytest.mark.parametrize("opened,hidden", [(False, False), (True, False), (True, True)])
def test_new_voice_sets_pug_connect_and_keeps_unused_pool_hidden(
    opened: bool, hidden: bool
) -> None:
    guild = _fake_guild(30)
    guild.create_voice_channel = AsyncMock(return_value=type("Channel", (), {"id": 100})())
    guild.get_channel = lambda _: None
    gateway = _gateway()
    gateway._guild = lambda _: guild
    gateway._voice_pacer = type("Pacer", (), {"run": lambda self, gid, call, **kw: call()})()
    asyncio.run(
        gateway.create_voice_channel(
            1,
            None,
            "Team Voice 1",
            [],
            [],
            open_to_everyone=opened,
            viewer_role_ids=[30],
            hidden=hidden,
        )
    )
    overwrites = guild.create_voice_channel.call_args.kwargs["overwrites"]
    assert overwrites[guild.get_role(30)].connect is (opened and not hidden)
    assert overwrites[guild.default_role].connect is (opened and not hidden)
