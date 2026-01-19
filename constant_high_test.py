import RPi.GPIO as GPIO
import time

# Setup
PWM_PIN = 18  # GPIO18 (Physical Pin 12)

GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
GPIO.setup(PWM_PIN, GPIO.OUT)

# Set GPIO18 HIGH (simulate 100% duty analog signal)
print("Setting GPIO18 HIGH — simulating constant 5V signal to fan.")
GPIO.output(PWM_PIN, GPIO.HIGH)

# Hold for 60 seconds
time.sleep(60)

# Cleanup
GPIO.output(PWM_PIN, GPIO.LOW)
GPIO.cleanup()
print("Test complete. GPIO18 set LOW and cleaned up.")

