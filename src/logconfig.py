import logging
import time

LOG_FILE = "log.log"
LOG_FORMAT = "%(levelname)s\t %(asctime)s --- %(message)s (%(module)s:%(lineno)d)"


class Formatter(logging.Formatter):
    # MicroPython records have no module/lineno, so the logger name and 0 stand in for them.
    # Its logging also can't format time (no time.strftime), so asctime is built by hand.
    def format(self, record: logging.LogRecord) -> str:
        if hasattr(record, "module"):
            return super().format(record)
        if self.usesTime():
            record.asctime = "%04d-%02d-%02d %02d:%02d:%02d" % time.localtime(record.ct)[:6]
        return self.fmt % {
            "name": record.name,
            "message": record.message,
            "msecs": record.msecs,
            "asctime": record.asctime,
            "levelname": record.levelname,
            "module": record.name,
            "lineno": 0,
        }


class FlushingFileHandler(logging.FileHandler):
    # The board can lose power right after an update, so don't leave lines in the write buffer.
    def emit(self, record: logging.LogRecord) -> None:
        super().emit(record)
        self.stream.flush()


def setup(level: int = logging.INFO, filename: str = LOG_FILE) -> None:
    """Log to the console and append to `filename`. Works on MicroPython and CPython."""
    logging.basicConfig(level=level)
    root = logging.getLogger()
    file_handler = FlushingFileHandler(filename)
    file_handler.setLevel(level)
    root.addHandler(file_handler)
    for handler in root.handlers:
        handler.setFormatter(Formatter(LOG_FORMAT))