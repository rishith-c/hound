#!/bin/sh
# setup_pi.sh — one-time setup ON THE PI (run over ssh by pi/deploy.sh --setup).
# Installs: Python venv with pyserial + Adafruit PCA9685/servo libs (turret), I2C enabled,
# arduino-cli + the UNO R4 core so the Pi can flash the R4 over its own USB cable.
set -e
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update -qq
sudo apt-get install -y -qq python3-venv python3-pip python3-serial i2c-tools python3-smbus rsync git >/dev/null
sudo raspi-config nonint do_i2c 0 2>/dev/null || true          # enable the hardware I2C bus for the PCA9685
sudo usermod -aG dialout,i2c,gpio "$USER" 2>/dev/null || true   # serial + I2C without sudo (takes effect on next login)

mkdir -p "$HOME/rover"
cd "$HOME/rover"
[ -d venv ] || python3 -m venv --system-site-packages venv
venv/bin/pip install -q --upgrade pip
venv/bin/pip install -q pyserial adafruit-blinka adafruit-circuitpython-pca9685 adafruit-circuitpython-motor \
  numpy scipy adafruit-circuitpython-mlx90640 opencv-python-headless        # sensing: vitals DSP, thermal array, MobileNet-SSD camera
# MobileNet-SSD (Caffe) for the camera person detector, ~23 MB
[ -f "$HOME/rover/MobileNetSSD_deploy.caffemodel" ] || curl -fsSL -o "$HOME/rover/MobileNetSSD_deploy.caffemodel" \
  "https://github.com/chuanqi305/MobileNet-SSD/raw/master/mobilenet_iter_73000.caffemodel" || true
[ -f "$HOME/rover/MobileNetSSD_deploy.prototxt" ] || curl -fsSL -o "$HOME/rover/MobileNetSSD_deploy.prototxt" \
  "https://raw.githubusercontent.com/chuanqi305/MobileNet-SSD/master/deploy.prototxt" || true

# arduino-cli so the Pi can upload a compiled .bin to the R4 on /dev/ttyACM0
mkdir -p "$HOME/.local/bin"
if ! [ -x "$HOME/.local/bin/arduino-cli" ]; then
  curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | BINDIR="$HOME/.local/bin" sh >/dev/null
fi
export PATH="$HOME/.local/bin:$PATH"
arduino-cli config init --overwrite >/dev/null 2>&1 || true
arduino-cli core update-index >/dev/null
arduino-cli core install arduino:renesas_uno >/dev/null

echo "setup complete on $(hostname): $(python3 --version), arduino-cli $(arduino-cli version | awk '{print $3}'), I2C: $(ls /dev/i2c-* 2>/dev/null | tr '\n' ' ')"
