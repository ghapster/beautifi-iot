import RPi.GPIO as GPIO
import time

PWM_PIN = 18  # GPIO18 (Pin 12)

GPIO.setmode(GPIO.BCM)
GPIO.setup(PWM_PIN, GPIO.OUT)

pwm = GPIO.PWM(PWM_PIN, 1000)  # 1 kHz
pwm.start(100)  # 100% duty

time.sleep(30)

pwm.stop()
GPIO.cleanup()

