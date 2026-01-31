#!/bin/bash
#
# OTP Kiosk Lockdown Setup Script
# Configures a Raspberry Pi 5 or Ubuntu system to run ONLY the OTP messaging apps
#
# WARNING: This will significantly restrict the system. Test in a VM first!
#
# Usage: sudo ./setup_kiosk.sh
#

set -e

# --- Configuration ---
KIOSK_USER="otpuser"
KIOSK_HOME="/home/$KIOSK_USER"
APP_DIR="$KIOSK_HOME/otp_app"
BACKUP_DIR="/root/pre_kiosk_backup"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo_status() { echo -e "${GREEN}[+]${NC} $1"; }
echo_warn() { echo -e "${YELLOW}[!]${NC} $1"; }
echo_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# --- Pre-flight Checks ---
if [ "$EUID" -ne 0 ]; then
    echo_error "This script must be run as root (use sudo)"
    exit 1
fi

if [ ! -f "otp_client.py" ] || [ ! -f "otp_relay_server.py" ]; then
    echo_error "otp_client.py and otp_relay_server.py must be in the current directory"
    exit 1
fi

echo "=============================================="
echo "       OTP KIOSK LOCKDOWN SETUP"
echo "=============================================="
echo ""
echo_warn "This will create a locked-down kiosk system."
echo_warn "The system will ONLY be able to run OTP apps."
echo ""
read -p "Are you sure you want to continue? (yes/no): " confirm
if [ "$confirm" != "yes" ]; then
    echo "Aborted."
    exit 0
fi

# --- Create Backup ---
echo_status "Creating backup of current configuration..."
mkdir -p "$BACKUP_DIR"
cp /etc/passwd "$BACKUP_DIR/" 2>/dev/null || true
cp /etc/group "$BACKUP_DIR/" 2>/dev/null || true
cp /etc/sudoers "$BACKUP_DIR/" 2>/dev/null || true

# --- Install Dependencies ---
echo_status "Installing required packages..."
apt-get update
apt-get install -y \
    python3 \
    python3-tk \
    python3-pip \
    openbox \
    xorg \
    lightdm \
    unclutter \
    xdotool

# Install Python packages
pip3 install pyngrok --break-system-packages 2>/dev/null || pip3 install pyngrok

# --- Create Kiosk User ---
echo_status "Creating kiosk user '$KIOSK_USER'..."
if id "$KIOSK_USER" &>/dev/null; then
    echo_warn "User $KIOSK_USER already exists, skipping creation"
else
    useradd -m -s /bin/bash "$KIOSK_USER"
    echo "$KIOSK_USER:otp_secure_2024" | chpasswd
fi

# --- Setup Application Directory ---
echo_status "Setting up application directory..."
mkdir -p "$APP_DIR"
cp otp_client.py "$APP_DIR/"
cp otp_relay_server.py "$APP_DIR/"
cp otp_generator.py "$APP_DIR/" 2>/dev/null || echo_warn "otp_generator.py not found, skipping"

# Copy OTP cipher file if it exists
if [ -f "otp_cipher.txt" ]; then
    cp otp_cipher.txt "$APP_DIR/"
    echo_status "Copied otp_cipher.txt"
fi

chown -R "$KIOSK_USER:$KIOSK_USER" "$APP_DIR"
chmod 700 "$APP_DIR"

# --- Create Kiosk Launcher Script ---
echo_status "Creating kiosk launcher..."
cat > "$APP_DIR/kiosk_launcher.py" << 'LAUNCHER_EOF'
#!/usr/bin/env python3
"""
OTP Kiosk Launcher
Provides a simple menu to launch OTP applications in a locked-down environment.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import subprocess
import os
import sys

class KioskLauncher:
    def __init__(self, master):
        self.master = master
        self.master.title("OTP Secure System")
        
        # Make fullscreen and remove decorations
        self.master.attributes('-fullscreen', True)
        self.master.configure(bg='#1a1a2e')
        
        # Prevent Alt+F4 and other escape methods
        self.master.protocol("WM_DELETE_WINDOW", self.do_nothing)
        self.master.bind('<Alt-F4>', self.do_nothing)
        self.master.bind('<Control-c>', self.do_nothing)
        self.master.bind('<Control-q>', self.do_nothing)
        self.master.bind('<Escape>', self.do_nothing)
        
        self.app_dir = os.path.dirname(os.path.abspath(__file__))
        self.child_process = None
        
        self.setup_ui()
    
    def do_nothing(self, event=None):
        """Block escape attempts"""
        return "break"
    
    def setup_ui(self):
        # Center frame
        center_frame = tk.Frame(self.master, bg='#1a1a2e')
        center_frame.place(relx=0.5, rely=0.5, anchor='center')
        
        # Title
        title = tk.Label(
            center_frame,
            text="🔐 OTP Secure Messaging System",
            font=("Helvetica", 32, "bold"),
            fg='#e94560',
            bg='#1a1a2e'
        )
        title.pack(pady=(0, 50))
        
        # Button style
        button_style = {
            'font': ("Helvetica", 18),
            'width': 25,
            'height': 2,
            'bg': '#16213e',
            'fg': 'white',
            'activebackground': '#0f3460',
            'activeforeground': 'white',
            'relief': 'flat',
            'cursor': 'hand2'
        }
        
        # Client button
        client_btn = tk.Button(
            center_frame,
            text="📨 Start Messenger Client",
            command=self.launch_client,
            **button_style
        )
        client_btn.pack(pady=10)
        
        # Server button
        server_btn = tk.Button(
            center_frame,
            text="🖥️ Start Relay Server",
            command=self.launch_server,
            **button_style
        )
        server_btn.pack(pady=10)
        
        # Status label
        self.status_label = tk.Label(
            center_frame,
            text="Select an application to launch",
            font=("Helvetica", 12),
            fg='#888888',
            bg='#1a1a2e'
        )
        self.status_label.pack(pady=(30, 0))
        
        # Footer
        footer = tk.Label(
            self.master,
            text="OTP Kiosk Mode | Secure Communications Only",
            font=("Helvetica", 10),
            fg='#444444',
            bg='#1a1a2e'
        )
        footer.pack(side='bottom', pady=20)
    
    def launch_client(self):
        """Launch the OTP Client"""
        client_path = os.path.join(self.app_dir, "otp_client.py")
        if os.path.exists(client_path):
            self.status_label.config(text="Launching Messenger Client...")
            subprocess.Popen([sys.executable, client_path], cwd=self.app_dir)
        else:
            messagebox.showerror("Error", "Client application not found!")
    
    def launch_server(self):
        """Launch the OTP Relay Server"""
        server_path = os.path.join(self.app_dir, "otp_relay_server.py")
        if os.path.exists(server_path):
            self.status_label.config(text="Launching Relay Server...")
            subprocess.Popen([sys.executable, server_path], cwd=self.app_dir)
        else:
            messagebox.showerror("Error", "Server application not found!")


def main():
    root = tk.Tk()
    app = KioskLauncher(root)
    root.mainloop()


if __name__ == "__main__":
    main()
LAUNCHER_EOF

chmod +x "$APP_DIR/kiosk_launcher.py"
chown "$KIOSK_USER:$KIOSK_USER" "$APP_DIR/kiosk_launcher.py"

# --- Configure Openbox (Minimal Window Manager) ---
echo_status "Configuring Openbox window manager..."
mkdir -p "$KIOSK_HOME/.config/openbox"

cat > "$KIOSK_HOME/.config/openbox/autostart" << OPENBOX_EOF
# Disable screen blanking
xset s off
xset -dpms
xset s noblank

# Hide mouse cursor when idle
unclutter -idle 3 &

# Start the kiosk launcher
cd $APP_DIR
python3 $APP_DIR/kiosk_launcher.py &
OPENBOX_EOF

cat > "$KIOSK_HOME/.config/openbox/rc.xml" << 'RCXML_EOF'
<?xml version="1.0" encoding="UTF-8"?>
<openbox_config xmlns="http://openbox.org/3.4/rc">
  <resistance>
    <strength>10</strength>
    <screen_edge_strength>20</screen_edge_strength>
  </resistance>
  <focus>
    <followMouse>no</followMouse>
  </focus>
  <placement>
    <policy>Smart</policy>
    <center>yes</center>
  </placement>
  <desktops>
    <number>1</number>
  </desktops>
  <keyboard>
    <!-- Block most keyboard shortcuts -->
  </keyboard>
  <mouse>
    <context name="Client">
      <mousebind button="Left" action="Press">
        <action name="Focus"/>
        <action name="Raise"/>
      </mousebind>
    </context>
  </mouse>
  <applications>
    <!-- Remove window decorations from all apps -->
    <application class="*">
      <decor>no</decor>
      <maximized>true</maximized>
    </application>
  </applications>
</openbox_config>
RCXML_EOF

chown -R "$KIOSK_USER:$KIOSK_USER" "$KIOSK_HOME/.config"

# --- Configure LightDM for Auto-Login ---
echo_status "Configuring automatic login..."
mkdir -p /etc/lightdm/lightdm.conf.d

cat > /etc/lightdm/lightdm.conf.d/50-kiosk.conf << LIGHTDM_EOF
[Seat:*]
autologin-user=$KIOSK_USER
autologin-user-timeout=0
user-session=openbox
greeter-hide-users=true
LIGHTDM_EOF

# --- Create Openbox Session File ---
echo_status "Creating Openbox session..."
cat > /usr/share/xsessions/openbox.desktop << SESSION_EOF
[Desktop Entry]
Name=Openbox
Comment=Openbox Window Manager
Exec=openbox-session
Type=Application
SESSION_EOF

# --- Restrict User Shell (Optional but recommended) ---
echo_status "Restricting user shell access..."
cat > "$KIOSK_HOME/.bashrc" << 'BASHRC_EOF'
# Restricted bashrc - no commands allowed
echo "This is a restricted kiosk system."
echo "Shell access is disabled."
exit
BASHRC_EOF

# --- Block Virtual Terminal Switching ---
echo_status "Blocking terminal switching..."
cat > /etc/X11/xorg.conf.d/10-kiosk.conf << XORG_EOF
Section "ServerFlags"
    Option "DontVTSwitch" "true"
    Option "DontZap" "true"
EndSection
XORG_EOF
mkdir -p /etc/X11/xorg.conf.d

# --- Create Systemd Service for Extra Lockdown ---
echo_status "Creating kiosk service..."
cat > /etc/systemd/system/otp-kiosk.service << SERVICE_EOF
[Unit]
Description=OTP Kiosk Mode
After=graphical.target

[Service]
Type=simple
User=$KIOSK_USER
Environment=DISPLAY=:0
WorkingDirectory=$APP_DIR
ExecStart=/usr/bin/python3 $APP_DIR/kiosk_launcher.py
Restart=always
RestartSec=3

[Install]
WantedBy=graphical.target
SERVICE_EOF

systemctl daemon-reload
systemctl enable otp-kiosk.service

# --- Create Recovery Script ---
echo_status "Creating recovery script..."
cat > /root/disable_kiosk.sh << 'RECOVERY_EOF'
#!/bin/bash
# Run this script to disable kiosk mode and restore normal operation

echo "Disabling kiosk mode..."

# Disable auto-login
rm -f /etc/lightdm/lightdm.conf.d/50-kiosk.conf

# Disable kiosk service
systemctl disable otp-kiosk.service
systemctl stop otp-kiosk.service

# Remove X restrictions
rm -f /etc/X11/xorg.conf.d/10-kiosk.conf

echo "Kiosk mode disabled. Reboot to restore normal operation."
echo "Run: sudo reboot"
RECOVERY_EOF

chmod +x /root/disable_kiosk.sh

# --- Final Summary ---
echo ""
echo "=============================================="
echo_status "KIOSK SETUP COMPLETE!"
echo "=============================================="
echo ""
echo "Kiosk User:     $KIOSK_USER"
echo "Password:       otp_secure_2024"
echo "App Directory:  $APP_DIR"
echo ""
echo_warn "IMPORTANT:"
echo "  1. Copy your otp_cipher.txt to: $APP_DIR/"
echo "  2. To disable kiosk mode, boot to recovery and run:"
echo "     /root/disable_kiosk.sh"
echo ""
echo "Reboot now to enter kiosk mode: sudo reboot"
echo ""
