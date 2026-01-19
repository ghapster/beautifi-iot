# main.py
from flask import Flask, jsonify
import board
import busio
import socket
from adafruit_pca9685 import PCA9685

# Flask app
app = Flask(__name__)

# Init I2C and PCA9685 fan controller
i2c = busio.I2C(board.SCL, board.SDA)
pca = PCA9685(i2c)
pca.frequency = 1000  # Match AC Infinity fans

# Fan state tracking
fan_channel = 0
fan_on = False
fan_speed_percent = 0.0

def set_fan_speed(percent):
    global fan_on, fan_speed_percent
    duty = int(0xFFFF * percent)
    pca.channels[fan_channel].duty_cycle = duty
    fan_on = percent > 0
    fan_speed_percent = percent

@app.route('/status')
def status():
    return jsonify({
        "hostname": socket.gethostname(),
        "fan_on": fan_on,
        "fan_speed_percent": fan_speed_percent
    })

if __name__ == '__main__':
    set_fan_speed(0.75)  # Start at 75% for testing
    app.run(host='0.0.0.0', port=80)


