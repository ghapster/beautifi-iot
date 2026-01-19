import pigpio
import time

pi = pigpio.pi()

pi.set_PWM_frequency(18, 1000)       # 1 kHz
pi.set_PWM_dutycycle(18, 255)        # Full power (255 = 100%)
print("Fan should spin at 100%")
time.sleep(10)

pi.set_PWM_dutycycle(18, 0)
pi.stop()
print("PWM stopped")

