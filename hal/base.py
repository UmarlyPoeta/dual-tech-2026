"""Hardware Abstraction Layer (HAL) base interfaces."""

from __future__ import annotations

import abc
from typing import Any, Generic, Optional, TypeVar

T = TypeVar("T")


class Sensor(abc.ABC, Generic[T]):
    """Base interface for all sensors (GPS, Camera, etc.)."""

    @abc.abstractmethod
    def open(self) -> None:
        """Initialize the sensor."""
        pass

    @abc.abstractmethod
    def close(self) -> None:
        """Release sensor resources."""
        pass

    @abc.abstractmethod
    def get_data(self) -> Optional[T]:
        """Return the latest sensor data or None if unavailable."""
        pass


class Actuator(abc.ABC, Generic[T]):
    """Base interface for all actuators (Motors, Servos, etc.)."""

    @abc.abstractmethod
    def open(self) -> None:
        """Initialize the actuator."""
        pass

    @abc.abstractmethod
    def close(self) -> None:
        """Release actuator resources."""
        pass

    @abc.abstractmethod
    def set_state(self, state: T) -> None:
        """Apply a new state or command to the actuator."""
        pass
