import attr
import hikari
from models.timer import Timer


@attr.define()
class TimerCompleteEvent(hikari.Event):
    """
    Dispatched when a scheduled timer has expired.
    """

    app: hikari.GatewayBotAware = attr.field()
    timer: Timer = attr.field()
