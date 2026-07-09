"""进程内领域事件总线（docs/05 §1）。

service 层在事务内 publish；订阅者同事务处理（积分/通知/流程）。
M1 只挂通知器骨架，积分引擎与流程引擎在 M2/M6 注册。
"""
import logging
from collections import defaultdict
from typing import Callable

from sqlalchemy.orm import Session

logger = logging.getLogger("aom.events")

_subscribers: dict[str, list[Callable]] = defaultdict(list)


def subscribe(event_type: str):
    """装饰器：注册订阅者。event_type 支持前缀通配，如 'ticket.*'。"""

    def wrap(fn: Callable):
        _subscribers[event_type].append(fn)
        return fn

    return wrap


def publish(db: Session, event_type: str, entity_type: str, entity_id: str, payload: dict | None = None):
    payload = payload or {}
    handlers = list(_subscribers.get(event_type, []))
    prefix = event_type.split(".")[0] + ".*"
    handlers += _subscribers.get(prefix, [])
    for fn in handlers:
        try:
            fn(db, event_type, entity_type, entity_id, payload)
        except Exception:  # 订阅者异常不阻断主流程，但记录
            logger.exception("event subscriber failed: %s -> %s", event_type, fn.__name__)
