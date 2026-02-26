from __future__ import annotations

import logging

from .common import EventSourceCreate

logger = logging.getLogger(__name__)


async def fetch_firms(*args, **kwargs) -> list[EventSourceCreate]:
    logger.info('FIRMS disabled or missing key')
    return []
