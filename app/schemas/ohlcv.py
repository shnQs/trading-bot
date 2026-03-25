from pydantic import BaseModel


class OHLCVOut(BaseModel):
    symbol: str
    interval: str
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int
    is_closed: bool

    model_config = {"from_attributes": True}
