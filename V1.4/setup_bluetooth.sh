#!/bin/bash
#
# OTP Bluetooth Share - Setup Script
# Installs Bluetooth dependencies for OTP key exchange
#
# Usage: sudo ./setup_bluetooth.sh
#

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo_status() { echo -e "${GREEN}[+]${NC} $1"; }
echo_warn() { echo -e "${YELLOW}[!]${NC} $1"; }
echo_error() { echo -e "${RED}[ERROR]${NC} $1"; }
echo_info() { echo -e "${BLUE}[i]${NC} $1"; }

# Check root
if [ "$EUID" -ne 0 ]; then
    echo_error "Please run with sudo: sudo ./setup_bluetooth.sh"
    exit 1
fi

echo "=============================================="
echo "     OTP Bluetooth Share - Setup"
echo "=============================================="
echo ""

# Get the actual user (not root)
ACTUAL_USER=${SUDO_USER:-$USER}

# --- Install System Packages ---
echo_status "Installing Bluetooth system packages..."
apt-get update -qq
apt-get install -y \
    bluetooth \
    bluez \
    bluez-tools \
    libbluetooth-dev \
    python3-dev \
    libglib2.0-dev

echo_status "System packages installed"

# --- Install Python Package ---
echo_status "Installing PyBluez Python package..."

# Determine pip flags
PIP_FLAGS=""
if pip3 install --help 2>&1 | grep -q "break-system-packages"; then
    PIP_FLAGS="--break-system-packages"
fi

pip3 install pybluez $PIP_FLAGS || {
    echo_warn "pip install failed, trying with --user for $ACTUAL_USER..."
    sudo -u "$ACTUAL_USER" pip3 install pybluez --user $PIP_FLAGS
}

echo_status "PyBluez installed"

# --- Configure Bluetooth ---
echo_status "Configuring Bluetooth service..."

# Enable and start Bluetooth service
systemctl enable bluetooth
systemctl start bluetooth

# Add user to bluetooth group
usermod -aG bluetooth "$ACTUAL_USER"
echo_status "Added $ACTUAL_USER to bluetooth group"

# --- Create Helper Scripts ---
echo_status "Creating Bluetooth helper scripts..."

# Script to make device discoverable
cat > /usr/local/bin/bt-discoverable << 'EOF'
#!/bin/bash
# Make Bluetooth discoverable for OTP key exchange
echo "Making Bluetooth discoverable for 5 minutes..."
sudo hciconfig hci0 piscan
bluetoothctl discoverable on
bluetoothctl discoverable-timeout 300
echo "Device is now discoverable. Run 'bt-hidden' to disable."
EOF
chmod +x /usr/local/bin/bt-discoverable

# Script to hide device
cat > /usr/local/bin/bt-hidden << 'EOF'
#!/bin/bash
# Make Bluetooth hidden
echo "Hiding Bluetooth device..."
sudo hciconfig hci0 noscan
bluetoothctl discoverable off
echo "Device is now hidden."
EOF
chmod +x /usr/local/bin/bt-hidden

# Script to check Bluetooth status
cat > /usr/local/bin/bt-status << 'EOF'
#!/bin/bash
# Check Bluetooth status
echo "=== Bluetooth Status ==="
echo ""
echo "Service:"
systemctl status bluetooth --no-pager -l | head -5
echo ""
echo "Adapter:"
hciconfig hci0 2>/dev/null || echo "No adapter found"
echo ""
echo "Paired devices:"
bluetoothctl paired-devices 2>/dev/null || echo "None"
EOF
chmod +x /usr/local/bin/bt-status

echo_status "Helper scripts created: bt-discoverable, bt-hidden, bt-status"

# --- Configure for Raspberry Pi ---
if [ -f /proc/device-tree/model ] && grep -q "Raspberry Pi" /proc/device-tree/model; then
    echo_status "Detected Raspberry Pi - configuring for Pi Bluetooth..."
    
    # Ensure Bluetooth is enabled in config
    if [ -f /boot/config.txt ]; then
        if ! grep -q "dtparam=krnbt=on" /boot/config.txt; then
            echo "dtparam=krnbt=on" >> /boot/config.txt
            echo_info "Added kernel Bluetooth parameter to /boot/config.txt"
        fi
    fi
    
    # For Pi 5, might need firmware config
    if [ -f /boot/firmware/config.txt ]; then
        if ! grep -q "dtparam=krnbt=on" /boot/firmware/config.txt; then
            echo "dtparam=krnbt=on" >> /boot/firmware/config.txt
            echo_info "Added kernel Bluetooth parameter to /boot/firmware/config.txt"
        fi
    fi
fi

# --- Create udev rule for non-root Bluetooth access ---
echo_status "Creating udev rules for Bluetooth access..."

cat > /etc/udev/rules.d/99-bluetooth.rules << 'EOF'
# Allow users in bluetooth group to access Bluetooth devices
KERNEL=="rfkill", MODE="0666"
SUBSYSTEM=="bluetooth", MODE="0660", GROUP="bluetooth"
EOF

udevadm control --reload-rules
udevadm trigger

echo_status "Udev rules configured"

# --- Summary ---
echo ""
echo "=============================================="
echo -e "${GREEN}    Bluetooth Setup Complete!${NC}"
echo "=============================================="
echo ""
echo "Helper commands:"
echo "  bt-discoverable  - Make device visible for pairing"
echo "  bt-hidden        - Hide device"
echo "  bt-status        - Check Bluetooth status"
echo ""
echo "To use OTP Bluetooth Share:"
echo "  1. Run: bt-discoverable"
echo "  2. Run: python3 otp_bluetooth_share.py"
echo ""
echo -e "${YELLOW}Note: You may need to log out and back in${NC}"
echo -e "${YELLOW}      for group changes to take effect.${NC}"
echo ""

# Offer to restart Bluetooth
read -p "Restart Bluetooth service now? (y/n): " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    systemctl restart bluetooth
    echo_status "Bluetooth service restarted"
fi

echo ""
echo "Done!"
