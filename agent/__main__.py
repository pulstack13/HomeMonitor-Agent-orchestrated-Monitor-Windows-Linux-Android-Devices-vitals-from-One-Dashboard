"""CLI entry point for the HomeMonitor desktop agent.

Examples
--------
Pair and run:
    python -m agent --controller http://controller.local:8787 --pairing-code K7M4-P2QX

Pair once, save the token, then exit (used by installers):
    python -m agent --controller http://controller.local:8787 \
        --pairing-code K7M4-P2QX --pair-only

Run with a saved configuration:
    python -m agent

Print one metrics sample without networking:
    python -m agent --once

Find controllers on the LAN:
    python -m agent --discover

Environment variables:
    HOMEMONITOR_CONFIG       path to agent.json
    HOMEMONITOR_CONTROLLER   controller base URL
    HOMEMONITOR_PAIRING_CODE one-time pairing code
    HOMEMONITOR_NAME         friendly device name
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from agent.collector import Collector
from agent.config import AgentConfig, default_config_path
from agent.runner import AgentRunner, FatalAgentError
from agent.transport import discover_controllers
from common.protocol import VERSION


def setup_logging(config_path: Path, verbose: bool) -> None:
    from logging.handlers import RotatingFileHandler

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)
    log_dir = config_path.parent / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / "agent.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError:
        pass


def _print_discovery() -> int:
    try:
        found = discover_controllers(timeout=3.0)
    except OSError as exc:
        print(f"Discovery failed: {exc}", file=sys.stderr)
        return 1
    if not found:
        print("No HomeMonitor controller answered. Check the LAN and UDP port 45892.")
        return 1
    print(f"Found {len(found)} controller(s):")
    for item in found:
        host = f" ({item.get('hostname')})" if item.get("hostname") else ""
        print(f"  {item['base_url']}{host}")
    return 0


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, "").strip() or default


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m agent", description="HomeMonitor monitoring agent"
    )
    parser.add_argument(
        "--config",
        default=str(default_config_path()),
        help="path to the agent JSON configuration (env: HOMEMONITOR_CONFIG)",
    )
    parser.add_argument(
        "--controller",
        default=_env("HOMEMONITOR_CONTROLLER"),
        help="controller base URL, e.g. http://controller.local:8787 "
        "(env: HOMEMONITOR_CONTROLLER)",
    )
    parser.add_argument(
        "--pairing-code",
        default=_env("HOMEMONITOR_PAIRING_CODE"),
        help="pairing code shown on the controller (env: HOMEMONITOR_PAIRING_CODE)",
    )
    parser.add_argument(
        "--name",
        default=None,
        help="friendly device name shown in the dashboard (env: HOMEMONITOR_NAME)",
    )
    parser.add_argument("--discover", action="store_true", help="find controllers and exit")
    parser.add_argument("--once", action="store_true", help="print one metrics sample and exit")
    parser.add_argument(
        "--pair-only",
        action="store_true",
        help="register with --pairing-code, save the token and exit",
    )
    parser.add_argument("--version", action="version", version=f"HomeMonitor agent {VERSION}")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    if args.discover:
        return _print_discovery()

    if args.once:
        collector = Collector()
        print(json.dumps(collector.collect(), indent=2, allow_nan=False))
        return 0

    config_path = Path(args.config).expanduser()
    try:
        config = AgentConfig.load(config_path) if config_path.exists() else AgentConfig()
    except (OSError, ValueError) as exc:
        print(f"Could not load config {config_path}: {exc}", file=sys.stderr)
        return 2

    env_name = _env("HOMEMONITOR_NAME")
    if args.name:
        config.name = args.name.strip()
    elif env_name:
        config.name = env_name
    if args.controller:
        config.controller_url = args.controller.strip()
    config.controller_url = config.normalized_controller_url()

    if not config.controller_url:
        print("No controller configured; searching the LAN...")
        try:
            found = discover_controllers(timeout=3.0)
        except OSError as exc:
            print(f"Discovery failed: {exc}", file=sys.stderr)
            return 2
        if not found:
            print(
                "No controller found. Pass --controller http://IP:8787 or start the controller.",
                file=sys.stderr,
            )
            return 2
        config.controller_url = found[0]["base_url"]
        print(f"Using controller {config.controller_url}")

    pairing_code = (args.pairing_code or "").strip()
    if not config.token and not pairing_code:
        print(
            "This agent is not paired yet.\n"
            "  1. Start the controller and note its pairing code.\n"
            f"  2. Run: python -m agent --controller {config.controller_url} "
            "--pairing-code CODE\n"
            "  (or set HOMEMONITOR_PAIRING_CODE)",
            file=sys.stderr,
        )
        return 2

    try:
        config.save(config_path)
    except OSError as exc:
        print(f"Could not save config {config_path}: {exc}", file=sys.stderr)
        return 2

    setup_logging(config_path, args.verbose)
    logging.getLogger("homemonitor.agent").info("Configuration: %s", config_path)
    runner = AgentRunner(
        config=config,
        config_path=config_path,
        pairing_code=pairing_code,
        collector=Collector(),
    )
    try:
        if args.pair_only:
            return runner.pair_once()
        return runner.run()
    except FatalAgentError as exc:
        logging.getLogger("homemonitor.agent").error("%s", exc)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
