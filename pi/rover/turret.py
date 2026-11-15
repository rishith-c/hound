"""
turret.py — the Ceres pan/tilt turret from the Pi, via the PCA9685 on I2C address 0x40.

Only TILT is driven (channel 0). The pan servo is continuous-rotation, cannot hold an
angle, and stays unplugged; the rover rotates on its wheels to pan.

    from turret import Turret
    t = Turret()
    t.tilt(90)      # level
    t.tilt(75)      # look down a little (floor of the Ceres mechanism is ~62-70°)
    t.relax()       # drop the PWM so the servo stops holding (no current, no heat)
"""
import board
import busio
from adafruit_pca9685 import PCA9685
from adafruit_motor import servo


class Turret:
    TILT_CH = 0
    TILT_MIN_DEG = 65          # Ceres mechanical floor; raise if the bracket touches
    TILT_MAX_DEG = 150
    PARK_DEG = 90

    def __init__(self, address=0x40):
        i2c = busio.I2C(board.SCL, board.SDA)
        self.pca = PCA9685(i2c, address=address)
        self.pca.frequency = 50
        self._tilt = servo.Servo(self.pca.channels[self.TILT_CH], min_pulse=500, max_pulse=2500)
        self.angle = None

    def tilt(self, deg):
        deg = max(self.TILT_MIN_DEG, min(self.TILT_MAX_DEG, float(deg)))
        self._tilt.angle = deg
        self.angle = deg
        return deg

    def park(self):
        return self.tilt(self.PARK_DEG)

    def relax(self):
        """Stop driving the servo (0 % duty). It will sag under the camera's weight."""
        self.pca.channels[self.TILT_CH].duty_cycle = 0

    def close(self):
        self.relax()
        self.pca.deinit()
