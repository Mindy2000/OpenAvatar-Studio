from __future__ import annotations

from dataclasses import dataclass

from openavatar.config import Settings
from openavatar.db import Database
from openavatar.events import EventStore
from openavatar.runtime import Metrics, RunRegistry
from openavatar.services.chat_runtime import ChatService


@dataclass(frozen=True)
class ApplicationContext:
    settings: Settings
    db: Database
    metrics: Metrics
    runs: RunRegistry
    events: EventStore
    chat: ChatService

