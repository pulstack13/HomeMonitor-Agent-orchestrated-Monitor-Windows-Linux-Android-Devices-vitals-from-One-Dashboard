"""Agent main loop with offline tolerance, approval polling and metrics upload."""

from __future__ import annotations

import logging
import signal
import threading
import time
from pathlib import Path
from typing import Any

from agent.collector import Collector
from agent.config import AgentConfig
from agent.transport import (
    ApiError,
    ControllerClient,
    ControllerUnavailable,
    discover_controllers,
)
from common.protocol import VERSION

logger = logging.getLogger("homemonitor.agent")

PENDING_LOG_INTERVAL = 60.0


class FatalAgentError(Exception):
    pass


class RetryLater(Exception):
    def __init__(self, seconds: float, message: str):
        super().__init__(message)
        self.seconds = seconds


class AgentRunner:
    def __init__(
        self,
        config: AgentConfig,
        config_path: Path,
        pairing_code: str = "",
        collector: Collector | None = None,
        client: ControllerClient | None = None,
    ):
        self.config = config
        self.config_path = config_path
        self.pairing_code = pairing_code.strip()
        self.collector = collector or Collector()
        self.client = client or ControllerClient(config.normalized_controller_url())
        self.stop_event = threading.Event()
        self.approved = False
        self.failures = 0
        self._last_pending_log = 0.0
        self._signals_installed = False

    # ------------------------------------------------------------------ signals
    def _install_signals(self) -> None:
        if self._signals_installed or threading.current_thread() is not threading.main_thread():
            return
        try:
            signal.signal(signal.SIGINT, self._handle_signal)
            signal.signal(signal.SIGTERM, self._handle_signal)
            self._signals_installed = True
        except (ValueError, OSError):
            pass

    def _handle_signal(self, signum, frame) -> None:  # noqa: ANN001
        logger.info("Shutdown signal received; stopping cleanly")
        self.stop_event.set()

    # ------------------------------------------------------------------ registration
    def _register(self) -> None:
        if not self.pairing_code:
            raise FatalAgentError(
                "No device token. Start the agent once with --pairing-code CODE."
            )
        device = self.collector.describe(self.config.name, self.config.device_id)
        logger.info(
            "Registering '%s' with %s", self.config.name, self.client.base_url
        )
        try:
            response = self.client.register(self.pairing_code, device)
        except ApiError as exc:
            if exc.status in (401, 403):
                raise RetryLater(
                    30.0,
                    f"Pairing rejected: {exc.message}. Check the pairing code on the controller.",
                ) from exc
            if exc.status == 429:
                raise RetryLater(exc.retry_after or 60.0, "Controller rate limit hit") from exc
            if exc.status in (400, 404, 405):
                raise FatalAgentError(f"Controller rejected registration: {exc.message}") from exc
            raise
        token = response.get("token")
        device_id = response.get("device_id")
        if not isinstance(token, str) or not token:
            raise FatalAgentError("Controller did not return a device token")
        if isinstance(device_id, str) and device_id:
            self.config.device_id = device_id
        self.config.token = token
        self._apply_intervals(response)
        self.config.save(self.config_path)
        self.pairing_code = ""
        logger.info("Registered as device %s", self.config.device_id)
        logger.info("Waiting for approval in the dashboard before metrics are accepted")

    def pair_once(self) -> int:
        """Register, save the device token and exit without starting telemetry."""
        self._install_signals()
        if not self.client.base_url:
            raise FatalAgentError("No controller URL configured")
        self.config.save(self.config_path)
        logger.info("HomeMonitor agent %s pairing as '%s'", VERSION, self.config.name)
        logger.info("Controller: %s", self.client.base_url)
        try:
            self._register()
        except (FatalAgentError, RetryLater) as exc:
            logger.error("%s", exc)
            return 3
        except ApiError as exc:
            logger.error("Controller rejected pairing: %s (%s)", exc.message, exc.code)
            return 3
        except ControllerUnavailable as exc:
            logger.error("Controller unreachable: %s", exc)
            return 3
        logger.info("Pairing saved to %s", self.config_path)
        logger.info("Approve the device in the dashboard, then start the service/agent")
        return 0

    # ------------------------------------------------------------------ loop
    def run(self) -> int:
        self._install_signals()
        if not self.client.base_url:
            raise FatalAgentError("No controller URL configured")
        self.config.save(self.config_path)
        logger.info("HomeMonitor agent %s starting as '%s'", VERSION, self.config.name)
        logger.info("Controller: %s", self.client.base_url)
        next_heartbeat = 0.0
        next_metrics = 0.0
        try:
            while not self.stop_event.is_set():
                try:
                    if not self.config.token:
                        self._register()
                        next_heartbeat = 0.0
                        next_metrics = 0.0

                    now = time.monotonic()
                    if now >= next_heartbeat:
                        response = self.client.heartbeat(
                            self.config.device_id,
                            self.config.token,
                            self.collector.quick_status(),
                        )
                        self.failures = 0
                        was_approved = self.approved
                        self.approved = bool(response.get("approved", True))
                        self._apply_intervals(response)
                        if self.approved and not was_approved:
                            logger.info("Device approved; starting metrics upload")
                            next_metrics = 0.0
                        elif not self.approved:
                            self._log_pending()
                        next_heartbeat = time.monotonic() + max(
                            2, self.config.heartbeat_interval
                        )

                    if self.approved and time.monotonic() >= next_metrics:
                        metrics = self.collector.collect()
                        try:
                            self.client.send_metrics(
                                self.config.device_id, self.config.token, metrics
                            )
                        except ApiError as exc:
                            if exc.status == 403 and exc.code == "pending_approval":
                                self.approved = False
                                self._log_pending(force=True)
                            else:
                                raise
                        else:
                            next_metrics = time.monotonic() + max(
                                2, self.config.metrics_interval
                            )

                    due = next_heartbeat
                    if self.approved:
                        due = min(due, next_metrics)
                    wait = max(0.2, min(10.0, due - time.monotonic()))
                    self.stop_event.wait(wait)

                except RetryLater as exc:
                    logger.warning("%s Retrying in %.0fs.", exc, exc.seconds)
                    self.stop_event.wait(exc.seconds)
                except FatalAgentError:
                    raise
                except ApiError as exc:
                    if exc.status == 401:
                        logger.error(
                            "Controller rejected this device token (%s). "
                            "The agent must be paired again.",
                            exc.message,
                        )
                        self.config.token = ""
                        self.config.save(self.config_path)
                        if not self.pairing_code:
                            raise FatalAgentError(
                                "Re-pair required: run the agent with --pairing-code CODE."
                            ) from exc
                        self.stop_event.wait(1.0)
                    elif exc.status == 403 and exc.code == "revoked":
                        raise FatalAgentError(
                            "This device was revoked on the controller. "
                            "Approve a new pairing to resume monitoring."
                        ) from exc
                    elif exc.status == 403 and exc.code == "pairing_denied":
                        logger.error("Pairing code was rejected by the controller")
                        self.stop_event.wait(60.0)
                    elif exc.status == 429:
                        wait = exc.retry_after or 30.0
                        logger.warning("Controller rate limit; retrying in %.0fs", wait)
                        self.stop_event.wait(wait)
                    else:
                        logger.warning("Controller error: %s (%s)", exc.message, exc.code)
                        self.stop_event.wait(10.0)
                except ControllerUnavailable as exc:
                    self.failures += 1
                    if self.failures == 1 or self.failures % 6 == 0:
                        logger.warning(
                            "Controller unreachable (%s); retrying automatically", exc
                        )
                    if (
                        self.config.auto_discover
                        and self.failures >= 3
                        and self.failures % 3 == 0
                    ):
                        self._rediscover()
                    delay = min(30.0, 2.0 ** min(self.failures, 4))
                    self.stop_event.wait(delay)
                except Exception:
                    logger.exception("Unexpected agent error; continuing")
                    self.stop_event.wait(10.0)
        except FatalAgentError as exc:
            logger.error("%s", exc)
            return 3
        finally:
            logger.info("Agent stopped")
        return 0

    # ------------------------------------------------------------------ helpers
    def _apply_intervals(self, response: dict[str, Any]) -> None:
        changed = False
        for key in ("heartbeat_interval", "metrics_interval"):
            value = response.get(key)
            if (
                isinstance(value, int)
                and not isinstance(value, bool)
                and 2 <= value <= 60
                and getattr(self.config, key) != value
            ):
                setattr(self.config, key, value)
                changed = True
        if changed:
            self.config.save(self.config_path)
            logger.info(
                "Intervals updated: heartbeat %ss, metrics %ss",
                self.config.heartbeat_interval,
                self.config.metrics_interval,
            )

    def _log_pending(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_pending_log < PENDING_LOG_INTERVAL:
            return
        self._last_pending_log = now
        logger.info(
            "Awaiting approval — open the dashboard and approve '%s' (%s)",
            self.config.name,
            self.config.device_id,
        )

    def _rediscover(self) -> None:
        logger.info("Trying UDP discovery for a moved controller...")
        try:
            found = discover_controllers(timeout=2.0)
        except OSError as exc:
            logger.debug("Discovery failed: %s", exc)
            return
        for item in found:
            url = item["base_url"]
            if url != self.client.base_url:
                logger.info("Found controller at %s; switching", url)
                self.config.controller_url = url
                self.config.save(self.config_path)
                self.client = ControllerClient(url)
                return
