#!/bin/bash
#
# OTP Kiosk - VM Test Setup
# A lighter version for testing in Ubuntu VM before deploying to Pi 5
#
# This version:
# - Creates a separate kiosk user
# - Sets up the launcher
# - Does NOT disable escape methods (for testing)
# - Easy to reverse
# - Handles files with or without .py extension
#
# Usage: sudo ./setup_kiosk_vm_test.sh
#

set -e

KIOSK_USER="otpuser"
KIOSK_HOME="/home/$KIOSK_USER"
APP_DIR="$KIOSK_HOME/otp_app"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo_status() { echo -e "${GREEN}[+]${NC} $1"; }
echo_warn() { echo -e "${YELLOW}[!]${NC} $1"; }
echo_error() { echo -e "${RED}[ERROR]${NC} $1"; }

if [ "$EUID" -ne 0 ]; then
    echo_error "Run with sudo"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=============================================="
echo "     OTP KIOSK - VM TEST SETUP"
echo "=============================================="
echo ""

# --- Install Dependencies ---
echo_status "Installing packages..."
apt-get update
apt-get install -y python3 python3-tk python3-pip openbox xorg lightdm unclutter

pip3 install pyngrok --break-system-packages 2>/dev/null || pip3 install pyngrok

# --- Create User ---
echo_status "Creating kiosk user..."
if ! id "$KIOSK_USER" &>/dev/null; then
    useradd -m -s /bin/bash "$KIOSK_USER"
    echo "$KIOSK_USER:test123" | chpasswd
fi

# --- Grant hardware RNG access (Pi 5) ---
if [ -e /dev/hwrng ]; then
    echo_status "Granting hardware RNG access..."
    # Add user to the group that owns /dev/hwrng
    HWRNG_GROUP=$(stat -c '%G' /dev/hwrng)
    usermod -aG "$HWRNG_GROUP" "$KIOSK_USER"
    # Also ensure permissions are correct
    chmod 660 /dev/hwrng
fi

# --- Setup App Directory ---
echo_status "Setting up application..."
mkdir -p "$APP_DIR"

# Function to copy file (handles with or without .py extension)
copy_py_file() {
    local basename="$1"
    local dest="$APP_DIR/${basename}.py"
    
    # Try with .py extension first
    if [ -f "$SCRIPT_DIR/${basename}.py" ]; then
        cp "$SCRIPT_DIR/${basename}.py" "$dest"
        echo_status "Copied ${basename}.py"
    # Try without .py extension
    elif [ -f "$SCRIPT_DIR/${basename}" ]; then
        cp "$SCRIPT_DIR/${basename}" "$dest"
        echo_status "Copied ${basename} -> ${basename}.py"
    # Try parent directory with .py
    elif [ -f "$SCRIPT_DIR/../${basename}.py" ]; then
        cp "$SCRIPT_DIR/../${basename}.py" "$dest"
        echo_status "Copied ${basename}.py from parent"
    # Try parent directory without .py
    elif [ -f "$SCRIPT_DIR/../${basename}" ]; then
        cp "$SCRIPT_DIR/../${basename}" "$dest"
        echo_status "Copied ${basename} -> ${basename}.py from parent"
    else
        echo_warn "${basename} not found"
    fi
}

# Copy all Python files
copy_py_file "otp_client"
copy_py_file "otp_relay_server"
copy_py_file "otp_generator"
copy_py_file "get_username"

# Copy otp_cipher.txt if it exists
if [ -f "$SCRIPT_DIR/otp_cipher.txt" ]; then
    cp "$SCRIPT_DIR/otp_cipher.txt" "$APP_DIR/"
    echo_status "Copied otp_cipher.txt"
elif [ -f "$SCRIPT_DIR/../otp_cipher.txt" ]; then
    cp "$SCRIPT_DIR/../otp_cipher.txt" "$APP_DIR/"
    echo_status "Copied otp_cipher.txt from parent"
fi

# --- Create Test Launcher (with escape ability) ---
cat > "$APP_DIR/kiosk_launcher.py" << 'LAUNCHER_EOF'
#!/usr/bin/env python3
"""
OTP Kiosk Launcher - VM Test Version
Press Escape 3 times quickly to exit (for testing only)
"""

import tkinter as tk
from tkinter import messagebox
import subprocess
import os
import sys
import time

class KioskLauncher:
    def __init__(self, master):
        self.master = master
        self.master.title("OTP Secure System")
        self.master.attributes('-fullscreen', True)
        self.master.configure(bg='#1a1a2e')
        
        self.app_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Escape sequence tracker (for VM testing)
        self.escape_count = 0
        self.last_escape_time = 0
        self.master.bind('<Escape>', self.handle_escape)
        
        self.setup_ui()
    
    def handle_escape(self, event):
        """Triple-escape to exit (VM testing only)"""
        current_time = time.time()
        if current_time - self.last_escape_time < 0.5:
            self.escape_count += 1
        else:
            self.escape_count = 1
        self.last_escape_time = current_time
        
        if self.escape_count >= 3:
            if messagebox.askyesno("Exit Kiosk", "Exit kiosk mode? (VM testing only)"):
                self.master.destroy()
        return "break"
    
    def setup_ui(self):
        center_frame = tk.Frame(self.master, bg='#1a1a2e')
        center_frame.place(relx=0.5, rely=0.5, anchor='center')
        
        # Title
        title = tk.Label(
            center_frame,
            text="🔐 OTP Secure Messaging",
            font=("Helvetica", 28, "bold"),
            fg='#e94560',
            bg='#1a1a2e'
        )
        title.pack(pady=(0, 40))
        
        button_style = {
            'font': ("Helvetica", 16),
            'width': 22,
            'height': 2,
            'bg': '#16213e',
            'fg': 'white',
            'activebackground': '#0f3460',
            'activeforeground': 'white',
            'relief': 'flat',
            'cursor': 'hand2'
        }
        
        tk.Button(
            center_frame,
            text="📨 Messenger Client",
            command=self.launch_client,
            **button_style
        ).pack(pady=8)
        
        tk.Button(
            center_frame,
            text="🖥️ Relay Server",
            command=self.launch_server,
            **button_style
        ).pack(pady=8)
        
        tk.Button(
            center_frame,
            text="🎲 OTP Generator",
            command=self.launch_generator,
            **button_style
        ).pack(pady=8)
        
        # Status
        self.status = tk.Label(
            center_frame,
            text="",
            font=("Helvetica", 11),
            fg='#888888',
            bg='#1a1a2e'
        )
        self.status.pack(pady=(20, 0))
        
        # OTP count
        self.update_otp_status()
        
        # Footer with escape hint (VM only)
        tk.Label(
            self.master,
            text="VM Test Mode | Press Escape 3x to exit",
            font=("Helvetica", 9),
            fg='#444444',
            bg='#1a1a2e'
        ).pack(side='bottom', pady=10)
    
    def update_otp_status(self):
        otp_file = os.path.join(self.app_dir, "otp_cipher.txt")
        used_file = os.path.join(self.app_dir, "used_pages.txt")
        
        total = 0
        used = 0
        
        if os.path.exists(otp_file):
            with open(otp_file) as f:
                total = sum(1 for line in f if len(line.strip()) > 8)
        
        if os.path.exists(used_file):
            with open(used_file) as f:
                used = sum(1 for line in f if line.strip())
        
        available = total - used
        if total > 0:
            self.status.config(text=f"OTP: {available} pages available ({used}/{total} used)")
        else:
            self.status.config(text="⚠️ No OTP file found - run Generator first", fg='#e94560')
    
    def find_file(self, basename):
        """Find file with or without .py extension"""
        # Try with .py first
        path_py = os.path.join(self.app_dir, f"{basename}.py")
        if os.path.exists(path_py):
            return path_py
        # Try without .py
        path_no_ext = os.path.join(self.app_dir, basename)
        if os.path.exists(path_no_ext):
            return path_no_ext
        return None
    
    def launch_app(self, basename):
        path = self.find_file(basename)
        if path:
            subprocess.Popen([sys.executable, path], cwd=self.app_dir)
            self.master.after(1000, self.update_otp_status)
        else:
            messagebox.showerror("Error", f"{basename} not found!")
    
    def launch_client(self):
        self.launch_app("otp_client")
    
    def launch_server(self):
        self.launch_app("otp_relay_server")
    
    def launch_generator(self):
        self.launch_app("otp_generator")


if __name__ == "__main__":
    root = tk.Tk()
    app = KioskLauncher(root)
    root.mainloop()
LAUNCHER_EOF

chown -R "$KIOSK_USER:$KIOSK_USER" "$APP_DIR"
chmod +x "$APP_DIR/kiosk_launcher.py"

# --- Configure Openbox ---
echo_status "Configuring Openbox..."
mkdir -p "$KIOSK_HOME/.config/openbox"

cat > "$KIOSK_HOME/.config/openbox/autostart" << EOF
xset s off
xset -dpms
unclutter -idle 5 &
cd $APP_DIR && python3 kiosk_launcher.py &
EOF

chown -R "$KIOSK_USER:$KIOSK_USER" "$KIOSK_HOME/.config"

# --- Configure LightDM ---
echo_status "Configuring auto-login..."
mkdir -p /etc/lightdm/lightdm.conf.d

cat > /etc/lightdm/lightdm.conf.d/50-kiosk.conf << EOF
[Seat:*]
autologin-user=$KIOSK_USER
autologin-user-timeout=0
user-session=openbox
EOF

# --- Create session file ---
cat > /usr/share/xsessions/openbox.desktop << EOF
[Desktop Entry]
Name=Openbox
Exec=openbox-session
Type=Application
EOF

# --- Create removal script ---
cat > /root/remove_kiosk_test.sh << 'EOF'
#!/bin/bash
rm -f /etc/lightdm/lightdm.conf.d/50-kiosk.conf
echo "Kiosk auto-login disabled. Reboot to use normal login."
EOF
chmod +x /root/remove_kiosk_test.sh

echo ""
echo "=============================================="
echo_status "VM TEST SETUP COMPLETE!"
echo "=============================================="
echo ""
echo "Kiosk User:  $KIOSK_USER"
echo "Password:    test123"
echo "App Dir:     $APP_DIR"
echo ""
echo "To test:"
echo "  1. Reboot: sudo reboot"
echo "  2. System will auto-login to kiosk mode"
echo "  3. Press Escape 3 times quickly to exit"
echo ""
echo "To remove: sudo /root/remove_kiosk_test.sh && sudo reboot"
echo ""
