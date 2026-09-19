"""Collect diagnostic families in a stable order."""

from importlib import import_module

MODULES = (
    "adc",
    "bus",
    "clocks",
    "comparators",
    "cpu",
    "decimal_adjust",
    "eeprom",
    "flash",
    "iic",
    "interrupts",
    "lcd",
    "power",
    "rtc",
    "sensor",
    "sensor_i2c",
    "serial",
    "ssu",
    "timers",
    "watchdog",
)


def cases():
    for name in MODULES:
        yield from import_module(f".{name}", __name__).cases()
