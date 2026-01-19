import RPi.GPIO as GPIO
import time

PWM_PIN = 18       # GPIO18 (Pin 12)
FREQ = 100         # Lower frequency so capacitor can smooth the signal

GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
GPIO.setup(PWM_PIN, GPIO.OUT)

pwm = GPIO.PWM(PWM_PIN, FREQ)
pwm.start(0)  # Start at 0% duty (fan should be off)

try:
    for duty in [0, 25, 50, 75, 100]:
        print(f"Setting duty cycle to {duty}%")
        pwm.ChangeDutyCycle(duty)
        time.sleep(30)  # Observe fan behavior for 30 sec per setting

finally:
    pwm.ChangeDutyCycle(0)
    pwm.stop()
    GPIO.cleanup()
    print("PWM stopped and GPIO cleaned up.")

