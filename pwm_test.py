import RPi.GPIO as GPIO
import time

PWM_PIN = 18  # GPIO18 (Pin 12)

GPIO.setmode(GPIO.BCM)
GPIO.setup(PWM_PIN, 1000)

pwm = GPIO.PWM(PWM_PIN, GPIO.HIGH)  # 1 kHz frequency
pwm.start(100)  # Start at 100% duty cycle

print("PWM running at 100% duty")
time.sleep(30)

pwm.stop()
GPIO.cleanup()
print("PWM stopped")

