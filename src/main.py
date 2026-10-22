import os
from picographics import PicoGraphics, DISPLAY_INKY_FRAME_4 as DISPLAY  # 4.0"

FORECAST_FILE = "forecast.json"


def has_forecast() -> bool:
    try:
        os.stat(FORECAST_FILE)
        return True
    except OSError:
        return False


# The frame buffer (~96 KB in one block) and the TLS download don't fit in RAM together, so every boot
# does only one of them: download and save the forecast, restart, then draw it. A restart is the only
# way to get the heap back unfragmented. The buffer is allocated first thing, before the other imports.
drawing = has_forecast()
graphics = PicoGraphics(DISPLAY) if drawing else None

import logging
import time

import machine

# local imports
import board
import logconfig
import clearoutside

from config import UPDATE_INTERVAL, RETRY_INTERVAL      # type: ignore
from secrets import LAT, LON, WIFI_SSID, WIFI_PASSWORD  # type: ignore

LAST_UPDATE_FILE = "last_update.txt"  # time.time() of the last successful draw


def minutes_until_next_update() -> int:
    """Whole minutes left of the update interval since the last draw, 0 if an update is due or the time is unknown."""
    try:
        with open(LAST_UPDATE_FILE) as f:
            age = time.time() - int(f.read())
    except (OSError, ValueError):
        return 0
    if age < 0 or time.localtime()[0] < board.MIN_VALID_YEAR:
        return 0
    return min(UPDATE_INTERVAL, (UPDATE_INTERVAL * 60 - age + 59) // 60)


def save_update_time() -> None:
    if time.localtime()[0] < board.MIN_VALID_YEAR:
        return  # the clock was never set, so the timestamp would be meaningless
    with open(LAST_UPDATE_FILE, "w") as f:
        f.write(str(time.time()))


board.load_clock()
logconfig.setup()
log = logging.getLogger("main")

# A reset shortly after a draw (not in the middle of a download/draw cycle) keeps the current picture and sleeps out the rest of the interval.
if not drawing:
    remaining = minutes_until_next_update()
    if remaining > 0:
        log.info("Updated within the last %d minutes, sleeping for %d minutes", UPDATE_INTERVAL, remaining)
        board.sleep(remaining)
        machine.soft_reset()

log.info("Clear Outside Inky Frame: %s", "drawing" if drawing else "downloading")

# A short delay to give USB chance to initialise
time.sleep(0.5)

board.clear_button_leds()
board.led_warn.off()

failed = False
try:
    board.pulse_warn_led(2)
    if graphics is not None:
        clearoutside.show(graphics, FORECAST_FILE)
    else:
        board.connect(WIFI_SSID, WIFI_PASSWORD)
        clearoutside.update(LAT, LON, FORECAST_FILE)
except Exception as e:
    failed = True
    log.exception("Update failed: %s", e)
finally:
    board.stop_pulse_warn_led(on=failed)  # stays on after a failed update, off otherwise

if not failed and not drawing:
    machine.soft_reset()  # downloaded: restart with a clean heap to draw

if not failed:
    try:
        save_update_time()
    except OSError as e:
        log.warning("Could not save the update time: %s", e)

# On battery board.sleep() powers the board off and the RTC wakes it, re-running this file.
# On USB power board.sleep() just blocks, so restart for the next update.
if failed:
    log.info("Retrying in %d minutes", RETRY_INTERVAL)
board.sleep(RETRY_INTERVAL if failed else UPDATE_INTERVAL)
machine.soft_reset()
