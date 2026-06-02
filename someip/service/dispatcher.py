"""SOME/IP message dispatcher.

The Dispatcher routes incoming SOME/IP messages to the appropriate
Skeleton or Proxy based on service_id and message type.
"""

import logging
from typing import Callable, Dict, Optional

from ..message.message import SomeipMessage
from ..message.message_type import MessageType
from ..message.header import SD_SERVICE_ID, SD_METHOD_ID
from .skeleton import Skeleton
from .proxy import Proxy

logger = logging.getLogger(__name__)


class Dispatcher:
    """Routes incoming SOME/IP messages to the correct handler.

    The dispatcher maintains a registry of Skeletons (server-side) and
    Proxies (client-side). Incoming messages are dispatched based on:
    - SD messages -> SD handler
    - REQUEST/REQUEST_NO_RETURN -> Skeleton matching service_id
    - RESPONSE/ERROR -> Proxy matching (client_id, session_id)
    - NOTIFICATION -> Event handler matching service_id
    """

    def __init__(self):
        # service_id -> Skeleton
        self._skeletons: Dict[int, Skeleton] = {}
        # service_id -> Proxy
        self._proxies: Dict[int, Proxy] = {}
        # SD message handler
        self._sd_handler: Optional[Callable] = None
        # Notification handlers: (service_id, method_id) -> callback
        self._notification_handlers: Dict[tuple, Callable] = {}

    def register_skeleton(self, skeleton: Skeleton) -> None:
        """Register a Skeleton for a service."""
        self._skeletons[skeleton.service_id] = skeleton

    def unregister_skeleton(self, service_id: int) -> None:
        """Unregister a Skeleton."""
        self._skeletons.pop(service_id, None)

    def register_proxy(self, proxy: Proxy) -> None:
        """Register a Proxy for a service."""
        self._proxies[proxy.service_id] = proxy

    def unregister_proxy(self, service_id: int) -> None:
        """Unregister a Proxy."""
        self._proxies.pop(service_id, None)

    def set_sd_handler(self, handler: Callable) -> None:
        """Set the handler for SD messages.

        Handler signature: handler(message: SomeipMessage, source: tuple)
        """
        self._sd_handler = handler

    def register_notification_handler(
        self, service_id: int, method_id: int, handler: Callable
    ) -> None:
        """Register a handler for notification messages."""
        self._notification_handlers[(service_id, method_id)] = handler

    def unregister_notification_handler(
        self, service_id: int, method_id: int
    ) -> None:
        """Unregister a notification handler."""
        self._notification_handlers.pop((service_id, method_id), None)

    async def dispatch(self, message: SomeipMessage, source: tuple = None) -> Optional[SomeipMessage]:
        """Dispatch an incoming message to the appropriate handler.

        Returns a response message if one needs to be sent back.
        """
        header = message.header

        # SD messages
        if header.is_sd:
            if self._sd_handler:
                self._sd_handler(message, source)
            return None

        msg_type = header.message_type
        service_id = header.service_id

        # Request messages -> Skeleton
        if msg_type in (MessageType.REQUEST, MessageType.REQUEST_NO_RETURN):
            skeleton = self._skeletons.get(service_id)
            if skeleton:
                response = await skeleton.handle_message(message)
                return response
            else:
                logger.warning(
                    "No skeleton for service 0x%04X", service_id
                )
                return None

        # Response/Error messages -> Proxy
        elif msg_type in (MessageType.RESPONSE, MessageType.ERROR):
            proxy = self._proxies.get(service_id)
            if proxy:
                matched = proxy.handle_response(message)
                if not matched:
                    logger.debug(
                        "Unmatched response for service 0x%04X", service_id
                    )
            return None

        # Notification messages -> event handler
        elif msg_type == MessageType.NOTIFICATION:
            method_id = header.method_id
            handler = self._notification_handlers.get((service_id, method_id))
            if handler:
                try:
                    handler(message, source)
                except Exception as e:
                    logger.warning("Notification handler error: %s", e)
            else:
                logger.debug(
                    "No handler for notification 0x%04X:0x%04X",
                    service_id, method_id,
                )
            return None

        # TP messages
        elif msg_type.is_tp():
            # TP handling should be done at a lower layer before dispatch
            logger.debug("TP message received, should be handled before dispatch")
            return None

        else:
            logger.warning("Unhandled message type: %s", msg_type)
            return None
