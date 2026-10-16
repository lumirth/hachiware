"""Collect diagnostic families in a stable order."""

from importlib import import_module

MODULES = (
    "adc",
    "arithmetic",
    "bits",
    "bus",
    "clock_modes",
    "clocks",
    "comparators",
    "control",
    "cpu",
    "decimal_adjust",
    "divide",
    "eeprom",
    "flash",
    "iic",
    "instruction_timing",
    "interrupts",
    "lcd",
    "lcd_voltage",
    "logic",
    "multiply",
    "poll",
    "ports",
    "power",
    "rewrite",
    "rtc",
    "sensor",
    "sensor_i2c",
    "serial",
    "ssu",
    "standby",
    "timer_modes",
    "timers",
    "watchdog",
)


def cases():
    for name in MODULES:
        yield from import_module(f".{name}", __name__).cases()
