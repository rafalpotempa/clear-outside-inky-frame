# Clear Outside forecast for the Inky Frame: fetch, parse and draw.
# Works on MicroPython (Inky Frame / Pico W) and CPython.
# The page is ~215 KB, so it is parsed line by line and never held in RAM.

import json
import logging
import os
log = logging.getLogger("clearoutside")

# --- Data source ---
HOST = "clearoutside.com"
# Midday view: each day row runs 12:00 -> 11:00 next day, so a whole night is in one row.
VIEW = "midday"

RATING = {"fc_good": 0, "fc_ok": 1, "fc_bad": 2}

# Detail row label prefix -> key. Only rows listed in `keep` are stored.
ROWS = (
    ("Total Clouds", "total_cloud"),
    ("Low Clouds", "low_cloud"),
    ("Medium Clouds", "mid_cloud"),
    ("High Clouds", "high_cloud"),
    ("ISS Passover", "iss"),
    ("Visibility", "visibility"),
    ("Fog", "fog"),
    ("Precipitation Type", "precip_type"),
    ("Precipitation Probability", "precip_prob"),
    ("Precipitation Amount", "precip_mm"),
    ("Wind Speed", "wind"),
    ("Chance of Frost", "frost"),
    ("Temperature", "temp"),
    ("Feels Like", "feels_like"),
    ("Dew Point", "dew_point"),
    ("Relative Humidity", "humidity"),
    ("Pressure", "pressure"),
    ("Ozone", "ozone"),
)

DEFAULT_KEEP = ("total_cloud", "low_cloud", "mid_cloud", "high_cloud",
                "precip_prob", "temp", "wind", "humidity")

# --- Display ---
# Inky Frame palette pen indices, drawn as solid ink.
BLACK, WHITE, GREEN, BLUE, RED, YELLOW, ORANGE = range(7)

# Pens indexed by rating (good, ok, bad) and darkness (day, sunset, dusk, night).
RATING_PENS = (GREEN, YELLOW, RED)
DARKNESS_PENS = (WHITE, ORANGE, BLUE, BLACK)
# The palette has no gray, so this is an RGB pen; it is drawn without dithering.
DAYLIGHT_OUTLINE_RGB = (128, 128, 128)

FONT = "bitmap8"
MARGIN = 5
LABEL_WIDTH = 150  # day label column
HOURS_Y = 42  # hour labels above the grid
TOP = 54  # first day row
ROW_HEIGHT = 48
# Grid columns: a full day from noon to noon, so midnight is always in the center.
HOURS = tuple(range(12, 24)) + tuple(range(12))

# bitmap8 is ASCII-only.
ASCII = {"ą": "a", "ć": "c", "ę": "e", "ł": "l", "ń": "n", "ó": "o", "ś": "s", "ź": "z", "ż": "z",
         "Ą": "A", "Ć": "C", "Ę": "E", "Ł": "L", "Ń": "N", "Ó": "O", "Ś": "S", "Ź": "Z", "Ż": "Z"}


def update(lat, lon, path):
    """Fetch the forecast and save it as JSON at `path`. Drawing happens after a restart, see show()."""
    _log_memory("start")
    data = fetch(lat, lon, keep=(), view=VIEW)
    _log_memory("after fetch")
    # Written to a temporary file first so that a half-written forecast is never picked up.
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.rename(tmp, path)
    log.info("Saved forecast to %s", path)


def show(graphics, path):
    """Draw the forecast saved by update(), then delete it so that the next boot downloads a fresh one."""
    try:
        with open(path) as f:
            data = json.load(f)
        draw(graphics, data)
        _log_memory("after draw")
    finally:
        os.remove(path)


def _log_memory(label):
    # Free heap and the largest single block still allocatable (the frame buffer needs ~96000 contiguous bytes).
    import gc
    gc.collect()
    lo, hi = 0, gc.mem_free()
    while hi - lo > 1024:
        mid = (lo + hi) // 2
        try:
            bytearray(mid)
            lo = mid
        except MemoryError:
            hi = mid
    log.info("Memory %s: %d free, largest block ~%d", label, gc.mem_free(), lo)


def draw(graphics, data):
    width, _ = graphics.get_bounds()
    days = data["days"]
    cell = min((width - LABEL_WIDTH - MARGIN) // len(HOURS), (ROW_HEIGHT - 4) // 2)
    sq = cell - 1
    grid_x = LABEL_WIDTH + (width - LABEL_WIDTH - len(HOURS) * cell) // 2
    gray = graphics.create_pen(*DAYLIGHT_OUTLINE_RGB)

    graphics.set_font(FONT)
    graphics.set_pen(WHITE)
    graphics.clear()

    graphics.set_pen(BLACK)
    graphics.text(_ascii(data["location"]), MARGIN, 4, width - 2 * MARGIN, 2)
    graphics.text("Generated %s %s" % (data["generated"], data["timezone"]), MARGIN, 24, width - 2 * MARGIN, 1)

    for c, h in enumerate(HOURS):
        graphics.text("%02d" % h, grid_x + c * cell + (sq - 11) // 2, HOURS_Y, cell, 1)

    for d, day in enumerate(days):
        y = TOP + d * ROW_HEIGHT
        graphics.set_pen(BLACK)
        graphics.text("%s %s" % ((day.get("weekday") or "")[:3], day.get("date")), MARGIN, y + 2, LABEL_WIDTH, 2)
        graphics.text("%s %s%%" % (day.get("moon_phase"), day.get("moon_illum")), MARGIN, y + 20, LABEL_WIDTH, 1)
        astro = day.get("astro_dark")
        graphics.text("Astro %s" % ("%s-%s" % tuple(astro) if astro else "none"), MARGIN, y + 32, LABEL_WIDTH, 1)
        index = {h: i for i, h in enumerate(day["hours"])}
        for c, h in enumerate(HOURS):
            i = index.get(h)
            if i is None:
                continue
            x = grid_x + c * cell
            graphics.set_pen(RATING_PENS[day["rating"][i]])
            graphics.rectangle(x, y + 2, sq, sq)
            dark = darkness(day, h)
            if dark == 0:
                # White on white would be invisible, so daylight gets a gray outline.
                graphics.set_pen(gray)
                graphics.rectangle(x, y + 2 + cell, sq, sq)
                graphics.set_pen(WHITE)
                graphics.rectangle(x + 1, y + 3 + cell, sq - 2, sq - 2)
            else:
                graphics.set_pen(DARKNESS_PENS[dark])
                graphics.rectangle(x, y + 2 + cell, sq, sq)

    graphics.update()


def darkness(day, hour):
    """0 daylight, 1 sunset (sun below horizon), 2 dusk (civil dark), 3 astronomical night."""
    t = hour * 60 + 30
    if _within(t, day.get("astro_dark")):
        return 3
    if _within(t, day.get("civil_dark")):
        return 2
    rise, set_ = day.get("sun_rise"), day.get("sun_set")
    if rise and set_ and not _within(t, (rise, set_)):
        return 1
    return 0


def _within(t, interval):
    # interval is ("HH:MM", "HH:MM") and may wrap past midnight.
    if not interval:
        return False
    a, b = _minutes(interval[0]), _minutes(interval[1])
    return a <= t < b if a <= b else t >= a or t < b


def _minutes(hhmm):
    h, _, m = hhmm.partition(":")
    return int(h) * 60 + int(m)


def _ascii(s):
    return "".join(ASCII.get(c, c if ord(c) < 128 else "?") for c in s or "")


def fetch(lat, lon, keep=DEFAULT_KEEP, view=None):
    return parse(iter_lines_micropython(lat, lon, view), keep)


def iter_lines_micropython(lat, lon, view=None):
    """Stream the forecast page over HTTPS on MicroPython, yielding lines."""
    import socket
    import ssl

    path = f"/forecast/{lat}/{lon}"
    if view:
        path += f"?view={view}"

    sock = socket.socket()
    addr = socket.getaddrinfo(HOST, 443)[0][-1]
    try:
        sock.connect(addr)
        try:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.verify_mode = ssl.CERT_NONE
            sock = ctx.wrap_socket(sock, server_hostname=HOST)
        except AttributeError:
            sock = ssl.wrap_socket(sock, server_hostname=HOST)
        # HTTP/1.0 avoids chunked transfer encoding.
        sock.write(("GET %s HTTP/1.0\r\nHost: %s\r\nUser-Agent: inky-frame\r\n"
                    "Connection: close\r\n\r\n" % (path, HOST)).encode())
        status = sock.readline()
        if b" 200 " not in status:
            raise OSError("HTTP " + status.decode().strip())
        while sock.readline() not in (b"\r\n", b""):
            pass
        while True:
            line = sock.readline()
            if not line:
                break
            yield line
    finally:
        sock.close()


def parse(lines, keep=DEFAULT_KEEP):
    """Parse an iterable of HTML lines (bytes or str) into a dict."""
    labels = {}
    for prefix, key in ROWS:
        if key in keep:
            labels[prefix] = key

    result = {"location": None, "generated": None, "timezone": None, "days": []}
    day = None
    pending = None  # "ratings" or a row key; collects <li> items until </ul>
    count = 0

    for line in lines:
        count += 1
        if count % 500 == 0:
            log.debug("Parsed %d lines, %d days", count, len(result["days"]))
        if isinstance(line, bytes):
            line = line.decode("utf-8", "ignore")

        if pending is not None:
            for cls, title, text in _iter_li(line):
                if pending == "ratings":
                    day["hours"].append(_to_int(text.split()[0]) if text else None)
                    day["rating"].append(RATING.get(cls.split()[0] if cls else "", 1))
                else:
                    day["rows"][pending].append(_parse_li(pending, cls, title, text))
            if "</ul>" in line:
                pending = None
            continue

        if "<h1>Forecast for " in line:
            loc = _between(line, "<h1>Forecast for ", "</h1>") or ""
            result["location"] = loc.rpartition(" (")[0] or loc
        elif "<h2>Generated: " in line:
            result["generated"] = _between(line, "Generated: ", ".")
            result["timezone"] = _between(line, "Timezone: ", "<")
        elif 'class="fc_day" id="day_' in line:
            day = {"rating": [], "hours": [], "rows": {}}
            result["days"].append(day)
            log.debug("Parsing day %d", len(result["days"]))
        elif day is None:
            continue
        elif "<style" in line:
            day = None  # trailing CSS repeats fc_daylight/fc_moonlight selectors
        elif "fc_day_date" in line:
            day["weekday"] = _between(line, "<span>", "</span>")
            day["date"] = _to_int(_between(line, "</span>", "<"))
        elif "fc_moon_phase_image" in line:
            # moon_phase_<n>: signed phase used by the site's sprite (e.g. -40)
            day["moon_phase_n"] = _to_int(_between(line, " moon_phase_", '"'))
        elif "fc_moon_phase\"" in line:
            day["moon_phase"] = _between(line, ">", "<")
        elif "fc_moon_percentage" in line:
            day["moon_illum"] = _to_int(_between(line, ">", "%"))
        elif "fc_moon_riseset" in line:
            t = _strip_tags(line).split()
            day["moon_rise"] = t[0] if len(t) > 0 else None
            day["moon_set"] = t[1] if len(t) > 1 else None
        elif "fc_hour_ratings" in line:
            pending = "ratings"
        elif '<div class="fc_daylight"' in line:
            text = _strip_tags(line.partition('<div class="fc_moonlight"></div>')[2]) + "."
            sun = _between(text, "Sun - ", ".  ") or ""
            day["sun_rise"] = _between(sun, "Rise: ", ",")
            day["sun_set"] = _between(sun, "Set: ", ",")
            day["civil_dark"] = _labelled(text, "Civil Dark")
            day["nautical_dark"] = _labelled(text, "Nautical Dark")
            day["astro_dark"] = _labelled(text, "Astro Dark")
        elif "fc_detail_label" in line:
            label = _between(line, "<span>", "</span>") or ""
            for prefix, key in labels.items():
                if label.startswith(prefix):
                    pending = key
                    day["rows"][key] = []
                    break
    log.info("Parsed %d lines, %d days: done", count, len(result["days"]))
    return result


def _iter_li(line):
    # Yields (class, title, text) for every <li> on a line.
    for part in line.split("<li")[1:]:
        if not part or part[0] not in " >":
            continue  # e.g. <link>
        head, _, rest = part.partition(">")
        cls = _between(head, 'class="', '"') or ""
        title = _between(head, 'title="', '"')
        text = _strip_tags(rest.partition("</li>")[0])
        yield cls, title, text


def _parse_li(key, cls, title, text):
    if key == "wind":
        return (_to_int(text), _to_int(_between(title or "", "(", "&deg;")))
    if key in ("precip_type", "frost"):
        return title or ""
    if key == "iss":
        return text or None
    return _to_int(text)


def _labelled(text, label):
    # "Civil Dark: 18:50 - 06:17." -> ("18:50", "06:17"); "None" -> None
    v = _between(text, label + ": ", ".")
    if v is None:
        return None
    v = v.strip()
    if " - " in v:
        a, _, b = v.partition(" - ")
        return (a.strip(), b.strip())
    return v if ":" in v else None


def _between(s, start, end, pos=0):
    i = s.find(start, pos)
    if i < 0:
        return None
    i += len(start)
    j = s.find(end, i)
    if j < 0:
        return None
    return s[i:j]


def _strip_tags(s):
    out = []
    depth = 0
    for ch in s:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        elif depth == 0:
            out.append(ch)
    return "".join(out).replace("&nbsp;", " ").strip()


def _to_int(s):
    try:
        return int(s)
    except (ValueError, TypeError):
        try:
            return round(float(s))
        except (ValueError, TypeError):
            return None
