"""İşlemler sırasında yaşanan gecikme/hata durumlarını Telegram'a canlı bildirmek için yardımcı."""
from __future__ import annotations

import logging
from typing import Callable

log = logging.getLogger(__name__)

ProgressFn = Callable[[str], None]


def noop(_msg: str) -> None:
    pass
