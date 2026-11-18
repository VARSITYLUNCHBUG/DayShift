"""compose.yaml keeps its production shape: pooled connections, hardened and pinned services."""

from __future__ import annotations

import configparser
import ipaddress
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
SERVICES: dict[str, dict[str, Any]] = yaml.safe_load((ROOT / "compose.yaml").read_text())[
    "services"
]


def test_the_long_running_services_go_through_pgbouncer() -> None:
    for name in ("web", "bot", "scheduler"):
        env = SERVICES[name]["environment"]
        assert "@pgbouncer:6432/" in env["DATABASE_URL"], name
        assert env["DB_PGBOUNCER"] == "true", name
        assert "@db:5432/" in env["DATABASE_DIRECT_URL"], name
    migrate = SERVICES["migrate"]["environment"]
    assert "@db:5432/" in migrate["DATABASE_URL"]
    assert migrate["DB_PGBOUNCER"] == "false"


def test_pgbouncer_pools_transactions_over_scram() -> None:
    ini = configparser.ConfigParser()
    ini.read(ROOT / "infra" / "pgbouncer" / "pgbouncer.ini")
    assert ini["pgbouncer"]["pool_mode"] == "transaction"
    assert ini["pgbouncer"]["auth_type"] == "scram-sha-256"
    # Written at start, on tmpfs: no password is ever committed.
    assert ini["pgbouncer"]["auth_file"].startswith("/run/pgbouncer/")
    assert "password" not in ini["databases"]["draftbot"]


@pytest.mark.parametrize("name", sorted(SERVICES))
def test_every_service_is_hardened(name: str) -> None:
    service = SERVICES[name]
    assert service["init"] is True
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert service["security_opt"] == ["no-new-privileges:true"]
    assert service["logging"]["options"]["max-size"]
    assert service["mem_limit"] and service["cpus"] and service["pids_limit"]
    if name != "migrate":
        assert service["healthcheck"]["start_period"]
        assert service["restart"] == "unless-stopped"


def _images() -> list[tuple[str, str]]:
    observability = yaml.safe_load((ROOT / "compose.observability.yaml").read_text())["services"]
    found = [
        (name, service["image"])
        for services in (SERVICES, observability)
        for name, service in services.items()
        if "image" in service
    ]
    for dockerfile in ("Dockerfile", "scripts/docker/tests.Dockerfile"):
        for line in (ROOT / dockerfile).read_text().splitlines():
            words = line.split()
            if words[:1] == ["FROM"] and "/" not in words[1] and ":" in words[1]:
                found.append((dockerfile, words[1]))
            found += [
                (dockerfile, word.split("=", 1)[1])
                for word in words
                if word.startswith("--from=") and ":" in word
            ]
    return found


@pytest.mark.parametrize(("where", "image"), _images())
def test_every_image_is_pinned_by_version_and_digest(where: str, image: str) -> None:
    # The app's own image is pinned by DRAFTBOT_IMAGE_TAG (deploy/ requires it); the rest by a
    # version tag, and by digest so a re-pushed tag can't change what runs. Dependabot moves both.
    if image.endswith(":${DRAFTBOT_IMAGE_TAG:-latest}"):
        return
    name, _, digest = image.partition("@sha256:")
    tag = name.rsplit(":", 1)[1]
    assert any(char.isdigit() for char in tag) and "latest" not in tag, (where, image)
    assert len(digest) == 64 and all(char in "0123456789abcdef" for char in digest), (where, image)


def test_only_the_edge_and_postgres_are_published_and_only_on_loopback() -> None:
    published = {name: service["ports"] for name, service in SERVICES.items() if "ports" in service}
    assert set(published) == {"edge", "db"}
    for ports in published.values():
        assert all(port.startswith("127.0.0.1:") for port in ports)


class _ComposeLoader(yaml.SafeLoader):
    """Reads compose's merge tags (`!override`, `!reset`) as the plain values they wrap."""


def _untagged(loader: yaml.SafeLoader, _suffix: str, node: yaml.Node) -> Any:
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    return loader.construct_scalar(node)  # type: ignore[arg-type]


_ComposeLoader.add_multi_constructor("!", _untagged)


def _load(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.load((ROOT / name).read_text(), Loader=_ComposeLoader)
    return loaded


def _default(value: str) -> str:
    """`${NAME:-default}` -> `default`."""
    assert value.startswith("${") and ":-" in value, value
    return value.split(":-", 1)[1].rstrip("}")


@pytest.mark.parametrize(
    ("file", "prefix"),
    [("compose.yaml", ""), ("compose.dev.yaml", "DEV_"), ("compose.test.yaml", "TEST_")],
)
def test_web_trusts_proxy_headers_from_the_edges_fixed_address_only(file: str, prefix: str) -> None:
    services = _load(file)["services"]
    trusted = services["web"]["environment"]["FORWARDED_ALLOW_IPS"]
    edge_ip = services["edge"]["networks"]["edge"]["ipv4_address"]
    assert trusted == edge_ip == f"${{{prefix}EDGE_IP:-{_default(edge_ip)}}}"
    ipam = _load(file)["networks"]["edge"]["ipam"]["config"][0]
    subnet = ipaddress.ip_network(_default(ipam["subnet"]))
    dynamic = ipaddress.ip_network(_default(ipam["ip_range"]))
    address = ipaddress.ip_address(_default(edge_ip))
    # A single host, inside the network, never one Docker could hand to another container, and
    # not the gateway (the subnet's first address).
    assert "/" not in _default(trusted)
    assert address in subnet and dynamic.subnet_of(subnet)  # type: ignore[arg-type]
    assert address not in dynamic and address != next(subnet.hosts())


def _megabytes(size: str) -> int:
    number, unit = int(size[:-1]), size[-1].lower()
    return number * {"m": 1, "g": 1024}[unit]


@pytest.mark.parametrize("name", ["edge", "migrate", "web", "bot", "scheduler"])
def test_tmp_is_sized_under_the_memory_limit(name: str) -> None:
    service = SERVICES[name]
    tmp = next(mount for mount in service["tmpfs"] if mount.split(":")[0] == "/tmp")
    options = dict(option.split("=") for option in tmp.split(":", 1)[1].split(","))
    assert _megabytes(options["size"]) < _megabytes(service["mem_limit"]) * 3 // 4, name


def test_the_app_never_gets_the_observability_secrets() -> None:
    observability = _load("compose.observability.yaml")["services"]
    secret_files = {
        name
        for name, service in observability.items()
        if any(".env.observability" in str(entry) for entry in service.get("env_file", []))
    }
    assert secret_files == {"grafana", "alertmanager"}
    for name in ("migrate", "web", "bot", "scheduler"):
        env = SERVICES[name]["environment"]
        assert env["DB_MONITOR_PASSWORD"] == "", name
        assert not [key for key in env if key.startswith(("GRAFANA", "ALERTMANAGER"))], name
    # Only migrate (which creates the role) and pgbouncer (its stats user) are given it back.
    given = {
        name
        for name, service in observability.items()
        if "DB_MONITOR_PASSWORD" in service.get("environment", {})
    }
    assert given == {"migrate", "pgbouncer"}


def test_the_exporters_log_in_as_the_monitoring_role() -> None:
    observability = _load("compose.observability.yaml")["services"]
    assert observability["postgres-exporter"]["environment"]["DATA_SOURCE_USER"] == (
        "draftbot_monitor"
    )
    assert (
        "user=draftbot_monitor"
        in (
            observability["pgbouncer-exporter"]["environment"][
                "PGBOUNCER_EXPORTER_CONNECTION_STRING"
            ]
        )
    )
    ini = configparser.ConfigParser()
    ini.read(ROOT / "infra" / "pgbouncer" / "pgbouncer.ini")
    assert ini["pgbouncer"]["stats_users"] == "draftbot_monitor"


def test_the_app_logs_in_as_its_own_role_without_the_superusers_password() -> None:
    for name in ("web", "bot", "scheduler"):
        env = SERVICES[name]["environment"]
        assert env["DATABASE_URL"].startswith("postgres://draftbot_app:"), name
        assert env["DATABASE_DIRECT_URL"].startswith("postgres://draftbot_app:"), name
        # .env has it, for compose; the containers get it blanked.
        assert env["POSTGRES_PASSWORD"] == "", name
        # Its own password; POSTGRES_PASSWORD only stands in while an older .env lacks one.
        assert (
            env["DATABASE_URL"]
            .split("@")[0]
            .endswith(":${DB_APP_PASSWORD:-${POSTGRES_PASSWORD:-change-me}}")
        ), name
    migrate = SERVICES["migrate"]
    assert migrate["environment"]["DATABASE_URL"].startswith("postgres://draftbot:")
    assert "DB_APP_PASSWORD" in migrate["environment"]
    assert "python -m config.app_role" in migrate["command"][-1]
    assert "DB_APP_PASSWORD" in SERVICES["pgbouncer"]["environment"]


def _networks(service: dict[str, Any]) -> set[str]:
    networks = service.get("networks", ["default"])
    return set(networks)


def test_grafana_and_alertmanager_cant_reach_the_database_or_the_app() -> None:
    observability = _load("compose.observability.yaml")["services"]
    merged = {name: dict(service) for name, service in SERVICES.items()}
    for name, service in observability.items():
        merged.setdefault(name, {}).update(service)
    for name in ("grafana", "alertmanager", "node-exporter"):
        reach = _networks(merged[name])
        for target in ("db", "pgbouncer", "web", "bot", "scheduler", "migrate"):
            assert not reach & _networks(merged[target]), (name, target)
    # Postgres is on its own network, with only what logs in to it directly.
    on_data = {name for name, service in merged.items() if "data" in _networks(service)}
    assert on_data == {
        "db",
        "pgbouncer",
        "migrate",
        "web",
        "postgres-exporter",
        "pgbouncer-exporter",
    }
    # Nothing in compose.yaml is on the network the observability services share.
    assert not [name for name, service in SERVICES.items() if "default" in _networks(service)]


def test_the_bot_healthcheck_reads_the_heartbeat_without_booting_django() -> None:
    test = SERVICES["bot"]["healthcheck"]["test"]
    assert test[:2] == ["CMD", "python"] and "manage.py" not in test
    assert "BOT_HEARTBEAT_FILE" in test[-1] and "> 60" in test[-1]
    assert SERVICES["scheduler"]["healthcheck"] == SERVICES["bot"]["healthcheck"]
    for file in ("compose.dev.yaml", "compose.test.yaml"):
        for name in ("bot", "scheduler"):
            # Only the interval differs; the check itself is compose.yaml's.
            assert set(_load(file)["services"][name]["healthcheck"]) == {"interval"}, (file, name)


def test_pgbouncer_stops_on_sigint_after_its_transactions() -> None:
    assert SERVICES["pgbouncer"]["stop_signal"] == "SIGINT"
    assert SERVICES["pgbouncer"]["stop_grace_period"]


def test_the_edge_network_is_dual_stack_in_production_only() -> None:
    edge = yaml.safe_load((ROOT / "compose.yaml").read_text())["networks"]["edge"]
    assert edge["enable_ipv6"] is True
    v6 = ipaddress.ip_network(_default(edge["ipam"]["config"][1]["subnet"]))
    assert v6.version == 6 and v6.is_private and v6.prefixlen == 64
    for file in ("compose.dev.yaml", "compose.test.yaml"):
        assert _load(file)["networks"]["edge"]["enable_ipv6"] is False, file
    for template in ("http", "https"):
        conf = (ROOT / "infra" / "nginx" / "templates" / template / "app.conf.template").read_text()
        assert "listen [::]:8080" in conf, template


def test_dev_and_test_stacks_build_the_dev_target_and_production_doesnt() -> None:
    assert "target" not in SERVICES["web"]["build"]
    for file in ("compose.dev.yaml", "compose.test.yaml"):
        for name in ("migrate", "web", "bot", "scheduler"):
            assert _load(file)["services"][name]["build"]["target"] == "dev", (file, name)
    dockerfile = (ROOT / "Dockerfile").read_text()
    stages = [line.split()[-1] for line in dockerfile.splitlines() if line.startswith("FROM ")]
    # The last stage is what a plain build (CI's published image) makes.
    assert stages[-1] == "runtime" and "dev" in stages
    runtime = dockerfile.split("AS runtime", 1)[1]
    base = dockerfile.split("AS base", 1)[1].split("AS dev", 1)[0]
    assert "COPY . ." not in base and "COPY devtools/" not in base and "COPY fixtures/" not in base
    assert "COPY" not in runtime


def test_only_web_drops_its_database_connection_after_each_request() -> None:
    assert SERVICES["web"]["environment"]["DB_CONN_MAX_AGE"] == "0"
    for name in ("bot", "scheduler", "migrate"):
        assert "DB_CONN_MAX_AGE" not in SERVICES[name]["environment"], name


def test_the_edge_serves_the_static_files_migrate_copies() -> None:
    assert "static:/srv/static:ro" in SERVICES["edge"]["volumes"]
    assert "static:/srv/static" in SERVICES["migrate"]["volumes"]
    assert "cp -R /app/staticfiles/. /srv/static/" in SERVICES["migrate"]["command"][-1]


@pytest.mark.parametrize("name", ["chrome", "e2e", "discord-sim", "control-panel"])
def test_the_test_only_services_are_hardened(name: str) -> None:
    service = _load("compose.test.yaml")["services"][name]
    if "extends" in service:
        # The dev stack's own definition, which both stacks share.
        assert service["extends"] == {"file": "compose.dev.yaml", "service": name}
        service = _load("compose.dev.yaml")["services"][name]
    assert service["init"] is True
    # e2e's root stays writable for pytest-playwright's output folder (compose.test.yaml).
    assert service["read_only"] is (name != "e2e")
    assert service["cap_drop"] == ["ALL"]
    assert service["security_opt"] == ["no-new-privileges:true"]
    if name in ("chrome", "e2e"):
        assert service["mem_limit"] and service["cpus"] and service["pids_limit"]
