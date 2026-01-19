import RPi.GPIO as GPIO
import time
import threading

# GPIO pin mapping
FAN_PWM_PINS = {
    "Fan 1": 18,
    "Fan 2": 13,
    "Fan 3": 19
}

FREQ = 100
RAMP_STEPS = [0, 25, 50, 75, 100]
STEP_DELAY = 10         # seconds between each ramp step
FAN_START_DELAYS = {    # staggered start delays
    "Fan 1": 0,
    "Fan 2": 30,
    "Fan 3": 60
}
RUNTIME_AT_FULL = 60    # seconds all fans run at 100%

# Setup GPIO
GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)

# Initialize PWM objects
pwms = {}
for fan_name, pin in FAN_PWM_PINS.items():
    GPIO.setup(pin, GPIO.OUT)
    pwm = GPIO.PWM(pin, FREQ)
    pwm.start(0)
    pwms[fan_name] = pwm
    print(f"{fan_name} initialized on GPIO{pin}")

# Fan control thread
def ramp_fan(fan_name, pwm, delay):
    print(f"{fan_name} will start in {delay}s...")
    time.sleep(delay)

    # Ramp up
    for duty in RAMP_STEPS:
        print(f"{fan_name} → {duty}%")
        pwm.ChangeDutyCycle(duty)
        time.sleep(STEP_DELAY)

# Reverse ramp
def ramp_down(fan_name, pwm, delay):
    print(f"{fan_name} ramp-down will start in {delay}s...")
    time.sleep(delay)
    
    for duty in reversed(RAMP_STEPS):
        print(f"{fan_name} → {duty}%")
        pwm.ChangeDutyCycle(duty)
        time.sleep(STEP_DELAY)
    print(f"{fan_name} turned off.")

try:
    # Start ramp-up threads
    threads = []
    for fan_name in FAN_PWM_PINS:
        t = threading.Thread(target=ramp_fan, args=(fan_name, pwms[fan_name], FAN_START_DELAYS[fan_name]))
        t.start()
        threads.append(t)

    # Wait for all to reach 100%
    for t in threads:
        t.join()

    print(f"\nAll fans at 100% — holding for {RUNTIME_AT_FULL}s")
    time.sleep(RUNTIME_AT_FULL)

    # Start ramp-down in same order, staggered by 30s
    down_threads = []
    for i, fan_name in enumerate(FAN_PWM_PINS):
        t = threading.Thread(target=ramp_down, args=(fan_name, pwms[fan_name], i * 30))
        t.start()
        down_threads.append(t)

    for t in down_threads:
        t.join()

finally:
    # Stop PWM and cleanup
    for pwm in pwms.values():
        pwm.ChangeDutyCycle(0)
        pwm.stop()
    GPIO.cleanup()
    print("\nAll fans off and GPIO cleaned up.")

