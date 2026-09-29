"""
Handlers Module - Magic Chatbot v2
===================================
Capa de presentación del bot de Telegram. Contiene los handlers que
procesan las interacciones del usuario (comandos, mensajes, callbacks)
y las delegan a la capa de servicios de negocio.

Principios aplicados:
- Thin Controllers: Los handlers solo orquestan; no contienen lógica de negocio.
- Dependency Injection: Los handlers reciben servicios vía constructor.
- Separación por tipo de interacción: comandos, mensajes, callbacks, errores.

Handlers incluidos:
- CommandHandlers: /start, /help, /id, /vm, etc.
- MessageHandlers: Procesamiento de texto no-comando (capturas, eco).
- CallbackHandlers: Botones inline (selección de servicio, validación, calendario).
- ConversationHandlers: Flujos conversacionales multi-paso (si aplica).
- ErrorHandler: Manejo global de errores.

Uso:
    from handlers.commands import CommandHandlers
    from handlers.callbacks import CallbackHandlers

    cmd = CommandHandlers(user_service, subscription_service, payment_service)
    app.add_handler(CommandHandler("start", cmd.start))
"""

from .callbacks import CallbackHandlers
from .commands import CommandHandlers
from .errors import ErrorHandler
from .messages import MessageHandlers

__all__ = [
    "CommandHandlers",
    "MessageHandlers",
    "CallbackHandlers",
    "ErrorHandler",
]
