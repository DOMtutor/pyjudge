import argparse
import asyncio
import enum
import json
import logging
import os
import pathlib
import time

import aiohttp
import apprise
import yaml
from dateutil import parser


class EventType(enum.Enum):
    ServerStatus = 0
    JudgehostStatus = 1
    Clarification = 2

    @staticmethod
    def get_by_name(key: str) -> "EventType | None":
        for ev in EventType:
            if ev.name == key:
                return ev
        return None


def truncate_text(string: str, total_length=200, line_count=5) -> str:
    lines = [
        line
        for line in string.splitlines(keepends=False)
        if line and not line.startswith(">")
    ]
    lines_truncated = False
    if len(lines) > line_count:
        lines = lines[:line_count]
        lines_truncated = True

    string = "".join(lines)
    if len(string) >= total_length:
        return string[:total_length] + "..."
    if lines_truncated:
        return string + "..."
    return string


class StateManager:
    def __init__(self, state_path: pathlib.Path):
        self.state_path = state_path
        self.state = {}
        if self.state_path.exists():
            try:
                with self.state_path.open("r") as f:
                    self.state = json.load(f)
            except Exception as e:
                logging.error("Failed to load state file %s: %s", self.state_path, e)

    def get_last_clarification_update(self, judge_name: str) -> float:
        if (
            judge_name not in self.state
            or "last_clarification_update" not in self.state[judge_name]
        ):
            current_time = time.time()
            self.save_last_clarification_update(judge_name, current_time)
            return current_time
        return self.state[judge_name]["last_clarification_update"]

    def save_last_clarification_update(self, judge_name: str, timestamp: float):
        if judge_name not in self.state:
            self.state[judge_name] = {}
        self.state[judge_name]["last_clarification_update"] = timestamp
        try:
            with self.state_path.open("w") as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            logging.error("Failed to save state file %s: %s", self.state_path, e)


class Watcher:
    def __init__(
        self,
        name: str,
        url: str,
        session: aiohttp.ClientSession,
        apprise_obj: apprise.Apprise,
        event_channels: dict[EventType, list[str]],
        state_manager: StateManager,
    ):
        self.name = name
        self.judge_url = url.rstrip("/")
        self.api_url = f"{self.judge_url}/api/v4"
        self.judge_session = session
        self.apprise = apprise_obj
        self.event_channels = event_channels
        self.state_manager = state_manager
        self.last_clarification_update = (
            self.state_manager.get_last_clarification_update(self.name)
        )
        self.judge_status = True
        self.hosts_status: bool = True

    async def send_event(self, event_type: EventType, message: str):
        tags = self.event_channels[event_type]
        if not tags:
            return

        title = f"[{self.name}] {event_type.name}"
        await self.apprise.async_notify(body=message, title=title, tag=tags)

    async def update_judge_status(self, status: bool, message: str):
        if status == self.judge_status:
            return
        self.judge_status = status
        await self.send_event(EventType.ServerStatus, message)

    async def check_judge_api_status(self):
        try:
            status_request = await self.judge_session.get(f"{self.api_url}/")
            if status_request.ok:
                await self.update_judge_status(
                    True, f"Reconnected to judge {self.name}"
                )
            else:
                await self.update_judge_status(
                    False,
                    f"Failed to connect to judge {self.name}: {status_request.status}",
                )
        except aiohttp.ClientError as e:
            print(e)
            await self.update_judge_status(
                False, f"Failed to connect to judge {self.name}: {e}"
            )

    async def request_from_judge_api(self, suffix: str, **kwargs):
        url = f"{self.api_url}{suffix}"
        try:
            response = await self.judge_session.get(url, **kwargs)

            if not response.ok:
                logging.debug("Error during request %s: %d", url, response.status)
                await self.update_judge_status(
                    False,
                    f"Failed to query judge {self.name} on {url}: {response.status}",
                )
                return None
            return await response.json()
        except aiohttp.ClientError as e:
            logging.debug("Error during request %s: %s", url, e)
            await self.update_judge_status(
                False, f"Failed to query judge {self.name}: {e}"
            )
            return None

    async def query_judge_host_status(self):
        judge_hosts = await self.request_from_judge_api("/judgehosts")
        if judge_hosts is None or not judge_hosts:
            return
        assert isinstance(judge_hosts, list)

        all_healthy = all(
            time.time() - float(host.get("polltime", 0)) < 30 for host in judge_hosts
        )
        if all_healthy:
            if not self.hosts_status:
                await self.send_event(
                    EventType.JudgehostStatus,
                    f"All judgehosts for {self.name} are up again.",
                )
            self.hosts_status = True
        elif self.hosts_status:
            await self.send_event(
                EventType.JudgehostStatus,
                f"Some judgehosts for {self.name} went offline.",
            )
            self.hosts_status = False

    async def query_clarifications(self):
        contests = await self.request_from_judge_api("/contests?enabled=true")
        if not contests:
            logging.debug("No enabled contests for %s", self.name)
            return
        assert isinstance(contests, list)

        contest_ids = [contest["id"] for contest in contests]
        if not contest_ids:
            return

        tasks = [
            self.request_from_judge_api(f"/contests/{contest_id}/clarifications")
            for contest_id in contest_ids
        ]
        results = await asyncio.gather(*tasks)

        clarifications = []
        for res in results:
            if res is None:
                return
            clarifications.extend(res)

        answered = {c["reply_to_id"] for c in clarifications if c.get("reply_to_id")}
        new_team_clarifications = [
            c
            for c in clarifications
            if parser.parse(c["time"]).timestamp() > self.last_clarification_update
            and c.get("from_team_id")
        ]

        if not new_team_clarifications:
            return

        clarification_texts = []
        for clarification in new_team_clarifications:
            if clarification["id"] in answered:
                continue

            text = f"Clarification request regarding {clarification.get('problem_id', 'general')}:\n"
            text += f"{truncate_text(clarification['text'])}\n"
            text += f"Link: {self.judge_url}/jury/clarifications/{clarification['id']}"
            clarification_texts.append(text)

        if clarification_texts:
            message = (
                f"New unanswered clarification requests for {self.name}:\n"
                + "\n\n".join(clarification_texts)
            )
            await self.send_event(EventType.Clarification, message)

        max_processed_time = self.last_clarification_update
        for c in new_team_clarifications:
            try:
                c_time = parser.parse(c["time"]).timestamp()
                if c_time > max_processed_time:
                    max_processed_time = c_time
            except Exception:
                pass

        if max_processed_time > self.last_clarification_update:
            self.last_clarification_update = max_processed_time
            self.state_manager.save_last_clarification_update(
                self.name, max_processed_time
            )

    async def run(self):
        logging.info("Watching judge %s", self.name)
        while True:
            await asyncio.gather(
                self.check_judge_api_status(),
                self.query_clarifications(),
                self.query_judge_host_status(),
            )
            await asyncio.sleep(60)


async def main(config_path: pathlib.Path):
    try:
        with config_path.open("r") as f:
            config = yaml.safe_load(f)
    except (IOError, yaml.YAMLError) as e:
        logging.critical("Failed to load config file %s: %s", config_path, e)
        return

    state_path = config_path.parent / ".watcher_state.json"
    state_manager = StateManager(state_path)

    ap = apprise.Apprise()
    notification_channels = config.get("notifications", {})
    for name, url in notification_channels.items():
        if not ap.add(url, tag=name):
            logging.warning("Could not add channel: %s", name)

    if not ap.servers:
        logging.warning("No valid notification channels configured.")

    watchers = []
    sessions = []
    try:
        for judge_config in config.get("judges", []):
            name = judge_config["name"]
            url = judge_config["url"]
            user = judge_config["user"]
            password = judge_config.get("password")
            if not password:
                password_env_var = judge_config.get("password_env")
                if password_env_var:
                    password = os.environ.get(password_env_var)

            if not password:
                logging.error("No password provided for judge '%s'. Skipping.", name)
                continue

            session = aiohttp.ClientSession(auth=aiohttp.BasicAuth(user, password))
            sessions.append(session)

            channels_config = judge_config.get("channels", {})
            event_config = {et: [] for et in EventType}

            for channel_name, subscribed_events in channels_config.items():
                if subscribed_events == "*":
                    for et in EventType:
                        event_config[et].append(channel_name)
                elif isinstance(subscribed_events, list):
                    for ev in subscribed_events:
                        et = EventType.get_by_name(ev)
                        if et is not None:
                            event_config[et].append(channel_name)
                        else:
                            logging.warning(
                                "Unknown event type '%s' for channel '%s' in judge '%s'",
                                ev,
                                channel_name,
                                name,
                            )
                else:
                    logging.warning(
                        "Invalid event configuration for channel '%s' in judge '%s",
                        channel_name,
                        name,
                    )

            print(event_config)
            watcher = Watcher(
                name=name,
                url=url,
                session=session,
                apprise_obj=ap,
                event_channels=event_config,
                state_manager=state_manager,
            )
            watchers.append(watcher.run())

        if watchers:
            await asyncio.gather(*watchers)
        else:
            logging.info("No judges to watch.")
    finally:
        for session in sessions:
            if not session.closed:
                await session.close()


def start():
    parser = argparse.ArgumentParser(description="DOMjudge Watcher")
    parser.add_argument(
        "-c",
        "--config",
        type=pathlib.Path,
        default=pathlib.Path(__file__).parent / "config.yaml",
        help="Path to the configuration file (default: config.yaml in script directory)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    logging.getLogger("hpack").setLevel(logging.WARNING)

    asyncio.run(main(args.config))


if __name__ == "__main__":
    start()
