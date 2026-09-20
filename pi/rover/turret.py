"""
turret.py — the tilt servo, driven by the UNO R4 over the same serial link as the wheels.

No PCA9685 any more: the tilt servo's signal sits on the CNC shield's Z+ end-stop pin (R4 D11) and the pan servo's on
the X+ end-stop pin (R4 D9), both hardware PWM; their power comes from the XL4015 5 V rail. The firmware clamps to 65–150° (Ceres mechanical floor ~62°).

    from r4 import R4; from turret import Turret
    t = Turret(R4())
    t.tilt(90)      # level
    t.tilt(75)      # look down a little
    t.relax()       # stop the pulses so the servo stops holding (no current, no heat)
"""


class Turret:
    TILT_MIN_DEG = 78
    TILT_MAX_DEG = 150
    PARK_DEG = 92

    def __init__(self, r4):
        self.r4 = r4
        self.angle = None

    def tilt(self, deg):
        deg = int(max(self.TILT_MIN_DEG, min(self.TILT_MAX_DEG, float(deg))))
        self.r4.tilt(deg)
        self.angle = deg
        return deg

    def nudge_pan(self, direction, ms=300):
        """Ceres pan: continuous-rotation, so only timed nudges (~20° per 300 ms). Keeps a net-nudge count as a rough bearing."""
        self.r4.nudge_pan(direction, ms)
        self.pan_steps = getattr(self, "pan_steps", 0) + (1 if direction > 0 else -1)
        return self.pan_steps

    def pan_stop(self):
        self.r4.pan_stop()

    def park(self):
        self.r4.pan_stop()
        return self.tilt(self.PARK_DEG)

    def relax(self):
        self.r4.tilt(-1); self.r4.pan(-1)

    def close(self):
        self.relax()
