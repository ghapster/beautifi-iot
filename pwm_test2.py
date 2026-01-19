import RPi.GPIO as GPIO
import time

PWM_PIN = 18  # GPIO18
FREQ = 1000   # 1 kHz PWM

def invert(duty):
    return 100 - duty

GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
GPIO.setup(PWM_PIN, GPIO.OUT)

pwm = GPIO.PWM(PWM_PIN, FREQ)
pwm.start(invert(0))  # Send 100% duty = GPIO HIGH all the time = fan full speed?

try:
    for duty in [0, 25, 50, 75, 100]:
        print(f"Fan setting: {duty}% (Inverted = {invert(duty)}%)")
        pwm.ChangeDutyCycle(invert(duty))
        time.sleep(30)

    print("Done. Turning off fan.")
    pwm.ChangeDutyCycle(invert(0))  # Fan full speed again

finally:
    pwm.stop()
    GPIO.cleanup()
    print("Cleaned up.")

