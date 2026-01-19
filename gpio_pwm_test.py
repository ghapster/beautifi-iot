import time
import pigpio

PWM_GPIO = 18  # GPIO18 = Pin 12
FREQ = 25
DUTY = 1.0  # Full power

pi = pigpio.pi()
if not pi.connected:
    exit()

try:
    pi.set_PWM_frequency(PWM_GPIO, FREQ)
    pi.set_PWM_dutycycle(PWM_GPIO, int(255 * DUTY))
    print("Running fan at 100% for 30 seconds")
    time.sleep(30)
finally:
    print("Stopping fan")
    pi.set_PWM_dutycycle(PWM_GPIO, 0)
    pi.set_mode(PWM_GPIO, pigpio.OUTPUT)
    pi.write(PWM_GPIO, 0)  # Force GPIO18 LOW
    pi.stop()


