from dataclasses import dataclass, field
from typing import List, Optional, Union


@dataclass
class DataItem:
    name: str
    value: Union[str, int]
    unit_of_measurement: Optional[str] = None


@dataclass
class DeviceData:
    name: str
    unique_name: str
    present: bool = False
    items: List[DataItem] = field(default_factory=list)
