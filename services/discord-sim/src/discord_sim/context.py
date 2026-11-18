"""The objects one running sim shares between its routes."""

from __future__ import annotations

from dataclasses import dataclass

from aiohttp import web

from discord_sim.config import Config
from discord_sim.deadlock_api import DeadlockApi
from discord_sim.eventlog import EventLog
from discord_sim.faults import Faults
from discord_sim.gateway import Gateway
from discord_sim.interactions import Interactions
from discord_sim.state import SimState


@dataclass
class Sim:
    config: Config
    state: SimState
    log: EventLog
    gateway: Gateway
    interactions: Interactions
    faults: Faults
    deadlock_api: DeadlockApi

    @classmethod
    def create(cls, config: Config) -> Sim:
        state = SimState(config)
        log = EventLog(config.log_size)
        gateway = Gateway(config, state, log)
        return cls(
            config=config,
            state=state,
            log=log,
            gateway=gateway,
            interactions=Interactions(config, state, gateway, log),
            faults=Faults(),
            deadlock_api=DeadlockApi(),
        )

    def base_url(self, request: web.Request) -> str:
        """Where the caller reaches the sim, for attachment URLs in what we send back."""
        return self.config.public_url or f"{request.scheme}://{request.host}"


SIM: web.AppKey[Sim] = web.AppKey("sim", Sim)


def sim_of(request: web.Request) -> Sim:
    return request.app[SIM]
