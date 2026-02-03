#!/bin/bash
#
# OTP Secure Communications - Complete Setup Script
# Installs all dependencies and prepares the system for use
#
# Supports: Raspberry Pi OS, Ubuntu, Debian
#
# Usage:
#   chmod +x setup_otp_system.sh
#   sudo ./setup_otp_system.sh
#
# Options:
#   --kiosk     Also configure kiosk mode (auto-login, fullscreen)
#   --no-reboot Don't reboot after kiosk setup
#   --help      Show this help message
#

set -e

# --- Configuration ---
INSTALL_DIR="/opt/otp-secure"
KIOSK_USER="otpuser"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# --- Helper Functions ---
echo_header() {
    echo ""
    echo -e "${BLUE}${BOLD}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}${BOLD}  $1${NC}"
    echo -e "${BLUE}${BOLD}═══════════════════════════════════════════════════════════${NC}"
}

echo_step() {
    echo -e "${CYAN}[STEP]${NC} $1"
}

echo_status() {
    echo -e "${GREEN}  ✓${NC} $1"
}

echo_warn() {
    echo -e "${YELLOW}  ⚠${NC} $1"
}

echo_error() {
    echo -e "${RED}  ✗${NC} $1"
}

echo_info() {
    echo -e "${BLUE}  ℹ${NC} $1"
}

check_root() {
    if [ "$EUID" -ne 0 ]; then
        echo_error "This script must be run as root (use sudo)"
        exit 1
    fi
}

detect_os() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS_NAME=$NAME
        OS_VERSION=$VERSION_ID
        OS_ID=$ID
    else
        OS_NAME="Unknown"
        OS_ID="unknown"
    fi
    
    # Check if Raspberry Pi
    if [ -f /proc/device-tree/model ]; then
        DEVICE_MODEL=$(cat /proc/device-tree/model | tr -d '\0')
        if [[ "$DEVICE_MODEL" == *"Raspberry Pi"* ]]; then
            IS_RASPBERRY_PI=true
            PI_MODEL="$DEVICE_MODEL"
        fi
    fi
}

show_help() {
    echo "OTP Secure Communications - Setup Script"
    echo ""
    echo "Usage: sudo ./setup_otp_system.sh [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --kiosk       Configure kiosk mode (auto-login, fullscreen launcher)"
    echo "  --no-reboot   Don't automatically reboot after kiosk setup"
    echo "  --install-dir Specify installation directory (default: /opt/otp-secure)"
    echo "  --help        Show this help message"
    echo ""
    echo "Examples:"
    echo "  sudo ./setup_otp_system.sh              # Basic install"
    echo "  sudo ./setup_otp_system.sh --kiosk      # Install + kiosk mode"
    echo ""
}

# --- Parse Arguments ---
SETUP_KIOSK=false
DO_REBOOT=true

while [[ $# -gt 0 ]]; do
    case $1 in
        --kiosk)
            SETUP_KIOSK=true
            shift
            ;;
        --no-reboot)
            DO_REBOOT=false
            shift
            ;;
        --install-dir)
            INSTALL_DIR="$2"
            shift 2
            ;;
        --help|-h)
            show_help
            exit 0
            ;;
        *)
            echo_error "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# --- Main Installation ---

check_root
detect_os

echo_header "OTP Secure Communications Setup"
echo ""
echo -e "  ${BOLD}System:${NC}      $OS_NAME $OS_VERSION"
if [ "$IS_RASPBERRY_PI" = true ]; then
    echo -e "  ${BOLD}Device:${NC}      $PI_MODEL"
fi
echo -e "  ${BOLD}Install to:${NC}  $INSTALL_DIR"
echo -e "  ${BOLD}Kiosk mode:${NC}  $([ "$SETUP_KIOSK" = true ] && echo "Yes" || echo "No")"
echo ""

read -p "Continue with installation? (y/n): " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Installation cancelled."
    exit 0
fi

# --- Step 1: Update System ---
echo_header "Step 1: Updating System Packages"

echo_step "Updating package lists..."
apt-get update -qq

echo_step "Upgrading installed packages..."
apt-get upgrade -y -qq
echo_status "System updated"

# --- Step 2: Install System Dependencies ---
echo_header "Step 2: Installing System Dependencies"

# Core packages
PACKAGES=(
    "python3"
    "python3-tk"
    "python3-pip"
    "python3-venv"
    "python3-dev"
)

# Audio packages (for voice calls)
AUDIO_PACKAGES=(
    "portaudio19-dev"
    "libasound2-dev"
    "libpulse-dev"
    "pulseaudio"
    "alsa-utils"
)

# GUI packages (for kiosk mode)
GUI_PACKAGES=(
    "xorg"
    "openbox"
    "lightdm"
    "unclutter"
)

echo_step "Installing Python and core packages..."
apt-get install -y -qq "${PACKAGES[@]}"
echo_status "Python packages installed"

echo_step "Installing audio packages (for voice calls)..."
apt-get install -y -qq "${AUDIO_PACKAGES[@]}"
echo_status "Audio packages installed"

if [ "$SETUP_KIOSK" = true ]; then
    echo_step "Installing GUI packages (for kiosk mode)..."
    apt-get install -y -qq "${GUI_PACKAGES[@]}"
    echo_status "GUI packages installed"
fi

# --- Step 3: Install Python Dependencies ---
echo_header "Step 3: Installing Python Dependencies"

# Determine pip install flags
PIP_FLAGS="--break-system-packages"

# Check if --break-system-packages is supported (Python 3.11+)
if ! pip3 install --help 2>&1 | grep -q "break-system-packages"; then
    PIP_FLAGS=""
fi

echo_step "Installing pyngrok (NAT traversal for relay server)..."
pip3 install pyngrok $PIP_FLAGS -q
echo_status "pyngrok installed"

echo_step "Installing cryptography (AES encryption for voice)..."
pip3 install cryptography $PIP_FLAGS -q
echo_status "cryptography installed"

echo_step "Installing PyAudio (audio capture/playback)..."
pip3 install pyaudio $PIP_FLAGS -q
echo_status "PyAudio installed"

echo_step "Installing pyttsx3 (text-to-speech, optional)..."
pip3 install pyttsx3 $PIP_FLAGS -q 2>/dev/null || echo_warn "pyttsx3 not available (optional)"

# --- Step 4: Create Installation Directory ---
echo_header "Step 4: Setting Up Application Directory"

echo_step "Creating installation directory..."
mkdir -p "$INSTALL_DIR"

# Copy application files if they exist in the script directory
APP_FILES=(
    "otp_contacts.py"
    "otp_client.py"
    "otp_voice_client.py"
    "otp_relay_server_voice.py"
    "otp_relay_server.py"
    "otp_generator.py"
    "kiosk_launcher_standalone.py"
    "get_username.py"
)

FOUND_FILES=0
for file in "${APP_FILES[@]}"; do
    if [ -f "$SCRIPT_DIR/$file" ]; then
        cp "$SCRIPT_DIR/$file" "$INSTALL_DIR/"
        echo_status "Copied $file"
        ((FOUND_FILES++))
    fi
done

if [ $FOUND_FILES -eq 0 ]; then
    echo_warn "No application files found in $SCRIPT_DIR"
    echo_info "Please copy the .py files to $INSTALL_DIR manually"
fi

# Copy OTP cipher file if exists
if [ -f "$SCRIPT_DIR/otp_cipher.txt" ]; then
    cp "$SCRIPT_DIR/otp_cipher.txt" "$INSTALL_DIR/"
    echo_status "Copied otp_cipher.txt"
fi

# Set permissions
chmod -R 755 "$INSTALL_DIR"
echo_status "Directory created: $INSTALL_DIR"

# --- Step 5: Configure Hardware RNG (Raspberry Pi) ---
if [ "$IS_RASPBERRY_PI" = true ]; then
    echo_header "Step 5: Configuring Hardware RNG (Raspberry Pi)"
    
    echo_step "Setting up hardware RNG access..."
    
    # Check if hwrng exists
    if [ -e /dev/hwrng ]; then
        # Get the group that owns hwrng
        HWRNG_GROUP=$(stat -c '%G' /dev/hwrng)
        
        # Create udev rule for persistent permissions
        cat > /etc/udev/rules.d/99-hwrng.rules << 'UDEV_EOF'
# Allow access to hardware RNG for OTP generation
KERNEL=="hwrng", MODE="0660", GROUP="gpio"
UDEV_EOF
        
        echo_status "Hardware RNG configured"
        echo_info "Users in the 'gpio' group can access /dev/hwrng"
    else
        echo_warn "Hardware RNG not found at /dev/hwrng"
        echo_info "OTP Generator will use /dev/urandom as fallback"
    fi
fi

# --- Step 6: Create Desktop Shortcut ---
echo_header "Step 6: Creating Desktop Shortcuts"

# Create .desktop file
mkdir -p /usr/share/applications

cat > /usr/share/applications/otp-secure.desktop << DESKTOP_EOF
[Desktop Entry]
Name=OTP Secure Communications
Comment=Encrypted messaging and voice calls
Exec=python3 $INSTALL_DIR/otp_contacts.py
Icon=security-high
Terminal=false
Type=Application
Categories=Network;Security;
DESKTOP_EOF

echo_status "Desktop shortcut created"

# Create command-line launcher
cat > /usr/local/bin/otp-secure << 'BIN_EOF'
#!/bin/bash
cd /opt/otp-secure
python3 otp_contacts.py "$@"
BIN_EOF
chmod +x /usr/local/bin/otp-secure

cat > /usr/local/bin/otp-kiosk << 'BIN_EOF'
#!/bin/bash
cd /opt/otp-secure
python3 kiosk_launcher_standalone.py "$@"
BIN_EOF
chmod +x /usr/local/bin/otp-kiosk

echo_status "Command-line launchers created: 'otp-secure', 'otp-kiosk'"

# --- Step 7: Kiosk Mode Setup (Optional) ---
if [ "$SETUP_KIOSK" = true ]; then
    echo_header "Step 7: Configuring Kiosk Mode"
    
    echo_step "Creating kiosk user..."
    if ! id "$KIOSK_USER" &>/dev/null; then
        useradd -m -s /bin/bash "$KIOSK_USER"
        echo "$KIOSK_USER:otp_secure_2024" | chpasswd
        echo_status "Created user: $KIOSK_USER (password: otp_secure_2024)"
    else
        echo_info "User $KIOSK_USER already exists"
    fi
    
    # Add to gpio group for hardware RNG access
    if [ "$IS_RASPBERRY_PI" = true ]; then
        usermod -aG gpio "$KIOSK_USER" 2>/dev/null || true
    fi
    
    # Create app directory for kiosk user
    KIOSK_APP_DIR="/home/$KIOSK_USER/otp_app"
    mkdir -p "$KIOSK_APP_DIR"
    
    # Copy files
    for file in "${APP_FILES[@]}"; do
        if [ -f "$INSTALL_DIR/$file" ]; then
            cp "$INSTALL_DIR/$file" "$KIOSK_APP_DIR/"
        fi
    done
    
    if [ -f "$INSTALL_DIR/otp_cipher.txt" ]; then
        cp "$INSTALL_DIR/otp_cipher.txt" "$KIOSK_APP_DIR/"
    fi
    
    chown -R "$KIOSK_USER:$KIOSK_USER" "$KIOSK_APP_DIR"
    chmod 700 "$KIOSK_APP_DIR"
    echo_status "Kiosk app directory created"
    
    echo_step "Configuring Openbox..."
    mkdir -p "/home/$KIOSK_USER/.config/openbox"
    
    cat > "/home/$KIOSK_USER/.config/openbox/autostart" << AUTOSTART_EOF
# Disable screen blanking
xset s off
xset -dpms
xset s noblank

# Hide mouse cursor when idle
unclutter -idle 3 &

# Start the kiosk launcher
cd $KIOSK_APP_DIR
python3 $KIOSK_APP_DIR/kiosk_launcher_standalone.py &
AUTOSTART_EOF
    
    chown -R "$KIOSK_USER:$KIOSK_USER" "/home/$KIOSK_USER/.config"
    echo_status "Openbox configured"
    
    echo_step "Configuring auto-login..."
    mkdir -p /etc/lightdm/lightdm.conf.d
    
    cat > /etc/lightdm/lightdm.conf.d/50-kiosk.conf << LIGHTDM_EOF
[Seat:*]
autologin-user=$KIOSK_USER
autologin-user-timeout=0
user-session=openbox
greeter-hide-users=true
LIGHTDM_EOF
    
    # Create openbox session file
    cat > /usr/share/xsessions/openbox.desktop << SESSION_EOF
[Desktop Entry]
Name=Openbox
Comment=Openbox Window Manager
Exec=openbox-session
Type=Application
SESSION_EOF
    
    echo_status "Auto-login configured"
    
    # Create recovery script
    cat > /root/disable_kiosk.sh << 'RECOVERY_EOF'
#!/bin/bash
echo "Disabling kiosk mode..."
rm -f /etc/lightdm/lightdm.conf.d/50-kiosk.conf
echo "Kiosk mode disabled. Reboot to use normal login."
RECOVERY_EOF
    chmod +x /root/disable_kiosk.sh
    echo_status "Recovery script created: /root/disable_kiosk.sh"
fi

# --- Step 8: Verification ---
echo_header "Step 8: Verifying Installation"

echo_step "Checking Python packages..."

MISSING_PACKAGES=()

python3 -c "import tkinter" 2>/dev/null || MISSING_PACKAGES+=("tkinter")
python3 -c "from pyngrok import ngrok" 2>/dev/null || MISSING_PACKAGES+=("pyngrok")
python3 -c "from cryptography.hazmat.primitives.ciphers.aead import AESGCM" 2>/dev/null || MISSING_PACKAGES+=("cryptography")
python3 -c "import pyaudio" 2>/dev/null || MISSING_PACKAGES+=("pyaudio")

if [ ${#MISSING_PACKAGES[@]} -eq 0 ]; then
    echo_status "All Python packages installed correctly"
else
    echo_warn "Some packages may not be installed correctly:"
    for pkg in "${MISSING_PACKAGES[@]}"; do
        echo_error "  - $pkg"
    done
fi

# Check audio
echo_step "Checking audio system..."
if command -v aplay &> /dev/null; then
    AUDIO_DEVICES=$(aplay -l 2>/dev/null | grep -c "card" || echo "0")
    if [ "$AUDIO_DEVICES" -gt 0 ]; then
        echo_status "Audio system: $AUDIO_DEVICES device(s) found"
    else
        echo_warn "No audio devices found"
    fi
else
    echo_warn "ALSA tools not available"
fi

# --- Complete ---
echo_header "Installation Complete!"

echo ""
echo -e "${GREEN}${BOLD}  ✓ OTP Secure Communications is ready to use!${NC}"
echo ""
echo "  Installation directory: $INSTALL_DIR"
echo ""
echo -e "  ${BOLD}Quick Start:${NC}"
echo "    • Run 'otp-secure' to launch the Contacts app"
echo "    • Run 'otp-kiosk' to launch the full kiosk interface"
echo "    • Or: python3 $INSTALL_DIR/otp_contacts.py"
echo ""

if [ "$SETUP_KIOSK" = true ]; then
    echo -e "  ${BOLD}Kiosk Mode:${NC}"
    echo "    • User: $KIOSK_USER"
    echo "    • Password: otp_secure_2024"
    echo "    • App directory: /home/$KIOSK_USER/otp_app/"
    echo "    • To disable: sudo /root/disable_kiosk.sh"
    echo ""
    
    if [ "$DO_REBOOT" = true ]; then
        echo -e "  ${YELLOW}System will reboot in 10 seconds to enter kiosk mode...${NC}"
        echo "  Press Ctrl+C to cancel"
        sleep 10
        reboot
    else
        echo -e "  ${YELLOW}Reboot to enter kiosk mode: sudo reboot${NC}"
    fi
else
    echo -e "  ${BOLD}Next Steps:${NC}"
    echo "    1. Copy your OTP cipher file to $INSTALL_DIR/otp_cipher.txt"
    echo "    2. Run 'otp-secure' to set up your device ID"
    echo "    3. Add contacts and start communicating!"
    echo ""
    echo "  For kiosk mode, run: sudo ./setup_otp_system.sh --kiosk"
fi

echo ""
