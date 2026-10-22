from pimoroni_i2c import PimoroniI2C
from pcf85063a import PCF85063A
import math
from machine import Pin, PWM, RTC, Timer
import time
import inky_frame
import json
import logging
import network
import os

log = logging.getLogger("board")

MIN_VALID_YEAR = 2024  # the RTC reads back as 2000 until it has been set once
NTP_HOSTS = ("pool.ntp.org", "time.google.com", "time.cloudflare.com")
NTP_TIMEOUT = 5  # seconds per attempt; ntptime's default of 1 is often too short on Wi-Fi

# Pin setup for VSYS_HOLD needed to sleep and wake.
HOLD_VSYS_EN_PIN = 2
hold_vsys_en_pin = Pin(HOLD_VSYS_EN_PIN, Pin.OUT)

# intialise the pcf85063a real time clock chip
I2C_SDA_PIN = 4
I2C_SCL_PIN = 5
i2c = PimoroniI2C(I2C_SDA_PIN, I2C_SCL_PIN, 100000)
rtc = PCF85063A(i2c)

led_warn = Pin(6, Pin.OUT)
led_warn_timer = Timer(-1)
led_warn_pwm = None


# duty cycle following a sinusoid seeded by the current time, gamma corrected (gamma 2.8)
def sine_duty(speed_hz):
    brightness = (math.sin(time.ticks_ms() * math.pi * 2 / (1000 / speed_hz)) * 40) + 60
    return int(pow(brightness / 100.0, 2.8) * 65535.0 + 0.5)


def led_warn_callback(t):
    led_warn_pwm.duty_u16(sine_duty(led_warn_pulse_speed_hz))


led_warn_pulse_speed_hz = 1


# pulse the warn led until stop_pulse_warn_led() is called
def pulse_warn_led(speed_hz=1):
    global led_warn_pwm, led_warn_pulse_speed_hz
    led_warn_pulse_speed_hz = speed_hz
    led_warn_timer.deinit()
    if led_warn_pwm is None:
        led_warn_pwm = PWM(led_warn)
        led_warn_pwm.freq(1000)
    led_warn_timer.init(period=50, mode=Timer.PERIODIC, callback=led_warn_callback)


# stop pulsing and leave the warn led on or off
def stop_pulse_warn_led(on=False):
    global led_warn_pwm
    led_warn_timer.deinit()
    if led_warn_pwm is not None:
        led_warn_pwm.deinit()
        led_warn_pwm = None
    led_warn.init(Pin.OUT)
    led_warn.value(on)


# set up for the network LED
network_led_pwm = PWM(Pin(7))
network_led_pwm.freq(1000)
network_led_pwm.duty_u16(0)


# set the brightness of the network led
def network_led(brightness):
    brightness = max(0, min(100, brightness))  # clamp to range
    # gamma correct the brightness (gamma 2.8)
    value = int(pow(brightness / 100.0, 2.8) * 65535.0 + 0.5)
    network_led_pwm.duty_u16(value)


network_led_timer = Timer(-1)
network_led_pulse_speed_hz = 1


def network_led_callback(t):
    # updates the network led brightness based on a sinusoid seeded by the current time
    network_led_pwm.duty_u16(sine_duty(network_led_pulse_speed_hz))


# set the network led into pulsing mode
def pulse_network_led(speed_hz=1):
    global network_led_timer, network_led_pulse_speed_hz
    network_led_pulse_speed_hz = speed_hz
    network_led_timer.deinit()
    network_led_timer.init(period=50, mode=Timer.PERIODIC, callback=network_led_callback)


# turn off the network led and disable any pulsing animation that's running
def stop_network_led():
    global network_led_timer
    network_led_timer.deinit()
    network_led_pwm.duty_u16(0)


def sleep(t):
    # Time to have a little nap until the next update
    rtc.clear_timer_flag()
    rtc.set_timer(t, ttp=rtc.TIMER_TICK_1_OVER_60HZ)
    rtc.enable_timer_interrupt(True)

    # Set the HOLD VSYS pin to an input
    # this allows the device to go into sleep mode when on battery power.
    hold_vsys_en_pin.init(Pin.IN)

    # Regular time.sleep for those powering from USB
    time.sleep(60 * t)


# Turns off the button LEDs
def clear_button_leds():
    inky_frame.button_a.led_off()
    inky_frame.button_b.led_off()
    inky_frame.button_c.led_off()
    inky_frame.button_d.led_off()
    inky_frame.button_e.led_off()


def network_connect(SSID, PSK):
    # Enable the Wireless
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    # Number of attempts to make before timeout
    max_wait = 10

    # Sets the Wireless LED pulsing and attempts to connect to your local network.
    pulse_network_led()
    wlan.config(pm=0xa11140)  # Turn WiFi power saving off for some slow APs
    wlan.connect(SSID, PSK)

    while max_wait > 0:
        if wlan.status() < 0 or wlan.status() >= 3:
            break
        max_wait -= 1
        print('waiting for network connection...')
        time.sleep(1)

    stop_network_led()
    network_led_pwm.duty_u16(30000)

    # Handle connection error. Switches the Warn LED on.
    if wlan.status() != 3:
        stop_network_led()
        led_warn.on()


def connect(ssid, psk):
    """Join Wi-Fi unless already connected, then sync the clock. Returns whether connected."""
    if not network.WLAN(network.STA_IF).isconnected():
        network_connect(ssid, psk)
    connected = network.WLAN(network.STA_IF).isconnected()
    if connected:
        sync_clock()
    return connected


def load_clock():
    # The board's RTC keeps time while powered off, but MicroPython's own clock restarts on every boot.
    year, month, day, hour, minute, second, weekday = rtc.datetime()
    if year >= MIN_VALID_YEAR:
        RTC().datetime((year, month, day, weekday, hour, minute, second, 0))


def sync_clock():
    # NTP time is UTC; it is stored in both clocks so it survives a power-off.
    import ntptime
    ntptime.timeout = NTP_TIMEOUT
    for host in NTP_HOSTS:
        ntptime.host = host
        try:
            ntptime.settime()
            break
        except Exception as e:
            log.warning("NTP sync via %s failed: %s", host, e)
    else:
        return
    year, month, day, hour, minute, second, weekday, _ = time.localtime()
    rtc.datetime((year, month, day, hour, minute, second, weekday))
    log.info("Clock set to %04d-%02d-%02d %02d:%02d:%02d UTC via %s", year, month, day, hour, minute, second, host)


state = {"run": None}
app = None


def file_exists(filename):
    try:
        return (os.stat(filename)[0] & 0x4000) == 0
    except OSError:
        return False


def clear_state():
    if file_exists("state.json"):
        os.remove("state.json")


def save_state(data):
    with open("/state.json", "w") as f:
        f.write(json.dumps(data))
        f.flush()


def load_state():
    global state
    data = json.loads(open("/state.json", "r").read())
    if type(data) is dict:
        state = data


def update_state(running):
    global state
    state['run'] = running
    save_state(state)


def launch_app(app_name):
    global app
    app = __import__(app_name)
    print(app)
    update_state(app_name)
