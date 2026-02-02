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

# Copy otp_cipher.txt if it exists
if [ -f "$SCRIPT_DIR/otp_cipher.txt" ]; then
    cp "$SCRIPT_DIR/otp_cipher.txt" "$APP_DIR/"
    echo_status "Copied otp_cipher.txt"
elif [ -f "$SCRIPT_DIR/../otp_cipher.txt" ]; then
    cp "$SCRIPT_DIR/../otp_cipher.txt" "$APP_DIR/"
    echo_status "Copied otp_cipher.txt from parent"
fi

# Copy credentials.txt if it exists
if [ -f "$SCRIPT_DIR/credentials.txt" ]; then
    cp "$SCRIPT_DIR/credentials.txt" "$APP_DIR/"
elif [ -f "$SCRIPT_DIR/../credentials.txt" ]; then
    cp "$SCRIPT_DIR/../credentials.txt" "$APP_DIR/"
fi

# --- Create Unified Kiosk App (all-in-one with seamless screen switching) ---
# --- Create Unified Kiosk App (all-in-one with seamless screen switching) ---
cat > "$APP_DIR/kiosk_launcher.py" << 'LAUNCHER_EOF'
#!/usr/bin/env python3
"""
OTP Kiosk - All-in-One Application
Seamless screen switching between launcher, client, server, and generator.
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import socket
import threading
import os
import sys
import time
import fcntl
from pathlib import Path
from datetime import datetime

try:
    from pyngrok import ngrok
    NGROK_AVAILABLE = True
except ImportError:
    NGROK_AVAILABLE = False

# --- CONFIGURATION ---
APP_DIR = Path(__file__).parent.resolve()
OTP_FILE = APP_DIR / "otp_cipher.txt"
USED_PAGES_FILE = APP_DIR / "used_pages.txt"
USED_PAGES_LOCK = APP_DIR / "used_pages.lock"
CREDENTIALS_FILE = APP_DIR / "credentials.txt"
PI_HWRNG_DEVICE = "/dev/hwrng"
PAGE_LENGTH = 3500
PAGE_ID_LENGTH = 8


# ============================================================================
# OTP UTILITIES
# ============================================================================

def load_otp_pages():
    otp_pages = []
    if not OTP_FILE.exists():
        return otp_pages
    with OTP_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip('\n')
            if len(line) < PAGE_ID_LENGTH + 1:
                continue
            identifier = line[:PAGE_ID_LENGTH]
            content = line[PAGE_ID_LENGTH:]
            otp_pages.append((identifier, content))
    return otp_pages


def load_used_pages():
    if not USED_PAGES_FILE.exists():
        return set()
    with USED_PAGES_FILE.open("r", encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def mark_page_used(identifier):
    with open(USED_PAGES_LOCK, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            with open(USED_PAGES_FILE, "a", encoding="utf-8") as f:
                f.write(f"{identifier}\n")
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def get_next_otp_page(otp_pages, used_identifiers):
    with open(USED_PAGES_LOCK, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            current_used = load_used_pages()
            for identifier, content in otp_pages:
                if identifier not in current_used:
                    with open(USED_PAGES_FILE, "a", encoding="utf-8") as f:
                        f.write(f"{identifier}\n")
                    used_identifiers.add(identifier)
                    return identifier, content
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
    return None, None


def xor_encrypt(plaintext, otp_content):
    encrypted = [ord(c) ^ ord(otp_content[i]) for i, c in enumerate(plaintext) if i < len(otp_content)]
    return bytes(encrypted).hex()


def xor_decrypt(hex_encrypted, otp_content):
    try:
        encrypted_bytes = bytes.fromhex(hex_encrypted)
    except ValueError:
        return "[Decryption Error]"
    decrypted = [chr(b ^ ord(otp_content[i])) for i, b in enumerate(encrypted_bytes) if i < len(otp_content)]
    return ''.join(decrypted)


def get_otp_status():
    otp_pages = load_otp_pages()
    used = load_used_pages()
    total = len(otp_pages)
    available = total - len(used)
    return available, total


def load_username():
    if CREDENTIALS_FILE.exists():
        with CREDENTIALS_FILE.open("r") as f:
            for line in f:
                if line.startswith("Username:"):
                    return line.replace("Username:", "").strip()
    return ""


# ============================================================================
# MAIN KIOSK APPLICATION
# ============================================================================

class OTPKiosk:
    def __init__(self, master):
        self.master = master
        self.master.title("OTP Secure System")
        self.master.attributes('-fullscreen', True)
        self.master.configure(bg='#0d1117')
        
        self.escape_count = 0
        self.last_escape_time = 0
        self.master.bind('<Escape>', self.handle_escape)
        
        self.otp_pages = load_otp_pages()
        self.used_identifiers = load_used_pages()
        
        self.client_socket = None
        self.client_connected = False
        self.client_user_id = None
        
        self.server = None
        self.server_clients = {}
        self.server_clients_lock = threading.Lock()
        self.ngrok_tunnel = None
        
        self.generating = False
        
        self.container = tk.Frame(self.master, bg='#0d1117')
        self.container.pack(fill=tk.BOTH, expand=True)
        
        self.show_main_menu()
    
    def handle_escape(self, event):
        now = time.time()
        if now - self.last_escape_time < 0.5:
            self.escape_count += 1
        else:
            self.escape_count = 1
        self.last_escape_time = now
        
        if self.escape_count >= 3:
            if messagebox.askyesno("Exit", "Exit kiosk mode?"):
                self.cleanup_and_exit()
        return "break"
    
    def cleanup_and_exit(self):
        if self.client_socket:
            try:
                self.client_socket.close()
            except:
                pass
        if self.server:
            try:
                self.server.shutdown()
            except:
                pass
        if self.ngrok_tunnel and NGROK_AVAILABLE:
            try:
                ngrok.disconnect(self.ngrok_tunnel.public_url)
            except:
                pass
        self.master.destroy()
    
    def clear_screen(self):
        for widget in self.container.winfo_children():
            widget.destroy()
    
    def create_header(self, title, show_back=True):
        header = tk.Frame(self.container, bg='#161b22', height=60)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        
        if show_back:
            back_btn = tk.Button(
                header, text="← Back", font=("Helvetica", 12),
                bg='#21262d', fg='white', activebackground='#30363d',
                activeforeground='white', relief='flat', cursor='hand2',
                command=self.show_main_menu
            )
            back_btn.pack(side=tk.LEFT, padx=20, pady=12)
        
        title_label = tk.Label(header, text=title, font=("Helvetica", 18, "bold"),
                               fg='#58a6ff', bg='#161b22')
        title_label.pack(side=tk.LEFT, padx=20, pady=12)
        return header
    
    def show_main_menu(self):
        if self.client_connected:
            self.disconnect_client()
        
        self.clear_screen()
        
        center = tk.Frame(self.container, bg='#0d1117')
        center.place(relx=0.5, rely=0.5, anchor='center')
        
        tk.Label(center, text="🔐", font=("Helvetica", 64), fg='#58a6ff', bg='#0d1117').pack(pady=(0, 10))
        tk.Label(center, text="OTP Secure Messaging", font=("Helvetica", 36, "bold"),
                 fg='#c9d1d9', bg='#0d1117').pack(pady=(0, 10))
        tk.Label(center, text="One-Time Pad Encrypted Communications", font=("Helvetica", 14),
                 fg='#8b949e', bg='#0d1117').pack(pady=(0, 50))
        
        btn_style = {'font': ("Helvetica", 16), 'width': 24, 'height': 2, 'relief': 'flat',
                     'cursor': 'hand2', 'fg': 'white', 'activeforeground': 'white'}
        
        tk.Button(center, text="📨  Messenger Client", bg='#238636', activebackground='#2ea043',
                  command=self.show_client_screen, **btn_style).pack(pady=8)
        tk.Button(center, text="🖥️  Relay Server", bg='#1f6feb', activebackground='#388bfd',
                  command=self.show_server_screen, **btn_style).pack(pady=8)
        tk.Button(center, text="🎲  OTP Generator", bg='#6e40c9', activebackground='#8957e5',
                  command=self.show_generator_screen, **btn_style).pack(pady=8)
        
        available, total = get_otp_status()
        if total == 0:
            status_text, status_color = "⚠️  No OTP file - Generate pages first", '#f85149'
        elif available == 0:
            status_text, status_color = "⚠️  All OTP pages used", '#f85149'
        elif available < 100:
            status_text, status_color = f"⚠️  Low: {available} pages remaining", '#d29922'
        else:
            status_text, status_color = f"✓  {available:,} OTP pages available", '#3fb950'
        
        tk.Label(center, text=status_text, font=("Helvetica", 12), fg=status_color, bg='#0d1117').pack(pady=(30, 0))
        tk.Label(self.container, text="Press ESC 3x to exit | OTP Kiosk Mode", font=("Helvetica", 10),
                 fg='#484f58', bg='#0d1117').pack(side='bottom', pady=15)
    
    def show_client_screen(self):
        self.clear_screen()
        self.create_header("📨 Messenger Client")
        
        content = tk.Frame(self.container, bg='#0d1117', padx=30, pady=20)
        content.pack(fill=tk.BOTH, expand=True)
        
        conn_frame = tk.Frame(content, bg='#161b22', padx=20, pady=15)
        conn_frame.pack(fill=tk.X, pady=(0, 15))
        
        tk.Label(conn_frame, text="Connection", font=("Helvetica", 14, "bold"),
                 fg='#c9d1d9', bg='#161b22').grid(row=0, column=0, columnspan=6, sticky='w', pady=(0, 10))
        
        tk.Label(conn_frame, text="Server:", fg='#8b949e', bg='#161b22').grid(row=1, column=0, padx=(0, 5))
        self.client_host_entry = tk.Entry(conn_frame, width=25, bg='#21262d', fg='white', insertbackground='white')
        self.client_host_entry.insert(0, "0.tcp.ngrok.io")
        self.client_host_entry.grid(row=1, column=1, padx=5)
        
        tk.Label(conn_frame, text="Port:", fg='#8b949e', bg='#161b22').grid(row=1, column=2, padx=(10, 5))
        self.client_port_entry = tk.Entry(conn_frame, width=8, bg='#21262d', fg='white', insertbackground='white')
        self.client_port_entry.insert(0, "12345")
        self.client_port_entry.grid(row=1, column=3, padx=5)
        
        tk.Label(conn_frame, text="Username:", fg='#8b949e', bg='#161b22').grid(row=1, column=4, padx=(10, 5))
        self.client_username_entry = tk.Entry(conn_frame, width=15, bg='#21262d', fg='white', insertbackground='white')
        self.client_username_entry.insert(0, load_username())
        self.client_username_entry.grid(row=1, column=5, padx=5)
        
        self.client_connect_btn = tk.Button(conn_frame, text="Connect", bg='#238636', fg='white',
                                             activebackground='#2ea043', relief='flat', cursor='hand2',
                                             command=self.connect_client)
        self.client_connect_btn.grid(row=1, column=6, padx=(15, 0))
        
        self.client_status_label = tk.Label(conn_frame, text="● Disconnected", fg='#f85149', bg='#161b22')
        self.client_status_label.grid(row=2, column=0, columnspan=7, sticky='w', pady=(10, 0))
        
        chat_frame = tk.Frame(content, bg='#161b22', padx=15, pady=15)
        chat_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        
        tk.Label(chat_frame, text="Messages", font=("Helvetica", 14, "bold"),
                 fg='#c9d1d9', bg='#161b22').pack(anchor='w', pady=(0, 10))
        
        self.client_chat_area = scrolledtext.ScrolledText(chat_frame, height=12, bg='#0d1117', fg='#c9d1d9',
                                                           font=("Consolas", 11), state=tk.DISABLED, wrap=tk.WORD)
        self.client_chat_area.pack(fill=tk.BOTH, expand=True)
        self.client_chat_area.tag_configure("sent", foreground="#58a6ff")
        self.client_chat_area.tag_configure("received", foreground="#3fb950")
        self.client_chat_area.tag_configure("system", foreground="#8b949e")
        self.client_chat_area.tag_configure("error", foreground="#f85149")
        
        input_frame = tk.Frame(content, bg='#161b22', padx=15, pady=15)
        input_frame.pack(fill=tk.X)
        
        tk.Label(input_frame, text="To:", fg='#8b949e', bg='#161b22').pack(side=tk.LEFT)
        self.client_recipient_entry = tk.Entry(input_frame, width=15, bg='#21262d', fg='white', insertbackground='white')
        self.client_recipient_entry.pack(side=tk.LEFT, padx=(5, 15))
        
        tk.Label(input_frame, text="Message:", fg='#8b949e', bg='#161b22').pack(side=tk.LEFT)
        self.client_message_entry = tk.Entry(input_frame, width=40, bg='#21262d', fg='white', insertbackground='white')
        self.client_message_entry.pack(side=tk.LEFT, padx=(5, 15), fill=tk.X, expand=True)
        self.client_message_entry.bind('<Return>', lambda e: self.send_client_message())
        
        self.client_send_btn = tk.Button(input_frame, text="Send", bg='#238636', fg='white',
                                          activebackground='#2ea043', relief='flat', cursor='hand2',
                                          state=tk.DISABLED, command=self.send_client_message)
        self.client_send_btn.pack(side=tk.LEFT)
    
    def add_chat_message(self, message, tag="system"):
        timestamp = datetime.now().strftime("%H:%M")
        self.client_chat_area.config(state=tk.NORMAL)
        self.client_chat_area.insert(tk.END, f"[{timestamp}] {message}\n", tag)
        self.client_chat_area.see(tk.END)
        self.client_chat_area.config(state=tk.DISABLED)
    
    def connect_client(self):
        host = self.client_host_entry.get().strip()
        port = self.client_port_entry.get().strip()
        username = self.client_username_entry.get().strip()
        
        if not host or not port or not username:
            messagebox.showwarning("Warning", "Please fill in all connection fields.")
            return
        
        try:
            port = int(port)
        except ValueError:
            messagebox.showwarning("Warning", "Port must be a number.")
            return
        
        self.add_chat_message(f"Connecting to {host}:{port}...", "system")
        
        try:
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client_socket.settimeout(10)
            self.client_socket.connect((host, port))
            self.client_socket.settimeout(None)
            
            self.client_socket.sendall(username.encode("utf-8"))
            response = self.client_socket.recv(1024).decode("utf-8")
            
            if response.startswith("ERROR"):
                error_msg = response.split("|", 1)[1] if "|" in response else response
                self.add_chat_message(f"Connection failed: {error_msg}", "error")
                self.client_socket.close()
                self.client_socket = None
                return
            
            self.client_user_id = username
            self.client_connected = True
            
            self.client_status_label.config(text=f"● Connected as '{username}'", fg='#3fb950')
            self.client_connect_btn.config(text="Disconnect", command=self.disconnect_client)
            self.client_send_btn.config(state=tk.NORMAL)
            self.client_host_entry.config(state=tk.DISABLED)
            self.client_port_entry.config(state=tk.DISABLED)
            self.client_username_entry.config(state=tk.DISABLED)
            
            self.add_chat_message("Connected!", "system")
            threading.Thread(target=self.client_receive_messages, daemon=True).start()
            
        except socket.timeout:
            self.add_chat_message("Connection timed out.", "error")
        except ConnectionRefusedError:
            self.add_chat_message("Connection refused. Is the server running?", "error")
        except Exception as e:
            self.add_chat_message(f"Connection error: {e}", "error")
    
    def disconnect_client(self):
        self.client_connected = False
        if self.client_socket:
            try:
                self.client_socket.close()
            except:
                pass
            self.client_socket = None
        
        self.client_status_label.config(text="● Disconnected", fg='#f85149')
        self.client_connect_btn.config(text="Connect", command=self.connect_client)
        self.client_send_btn.config(state=tk.DISABLED)
        self.client_host_entry.config(state=tk.NORMAL)
        self.client_port_entry.config(state=tk.NORMAL)
        self.client_username_entry.config(state=tk.NORMAL)
    
    def send_client_message(self):
        if not self.client_connected:
            return
        
        recipient = self.client_recipient_entry.get().strip()
        message = self.client_message_entry.get().strip()
        
        if not recipient or not message:
            return
        
        if recipient == self.client_user_id:
            messagebox.showwarning("Warning", "Cannot message yourself.")
            return
        
        otp_id, otp_content = get_next_otp_page(self.otp_pages, self.used_identifiers)
        if not otp_id:
            messagebox.showerror("Error", "No OTP pages available!")
            return
        
        if len(message) > len(otp_content):
            messagebox.showwarning("Warning", f"Message too long! Max {len(otp_content)} chars.")
            return
        
        encrypted_hex = xor_encrypt(message, otp_content)
        full_message = f"{recipient}|{otp_id}:{encrypted_hex}"
        
        try:
            self.client_socket.sendall(full_message.encode("utf-8"))
            self.client_message_entry.delete(0, tk.END)
            self.add_chat_message(f"To {recipient}: {message}", "sent")
        except Exception as e:
            self.add_chat_message(f"Send failed: {e}", "error")
    
    def client_receive_messages(self):
        while self.client_connected and self.client_socket:
            try:
                data = self.client_socket.recv(8192)
                if not data:
                    break
                message = data.decode("utf-8")
                self.process_client_message(message)
            except:
                break
        
        if self.client_connected:
            self.master.after(0, self.disconnect_client)
    
    def process_client_message(self, raw_message):
        try:
            sender_id, payload = raw_message.split("|", 1)
            
            if sender_id == "SYSTEM":
                self.master.after(0, lambda: self.add_chat_message(payload, "system"))
                return
            
            otp_id, encrypted_hex = payload.split(":", 1)
            
            otp_content = None
            for identifier, content in self.otp_pages:
                if identifier == otp_id:
                    otp_content = content
                    break
            
            if otp_content:
                decrypted = xor_decrypt(encrypted_hex, otp_content)
                mark_page_used(otp_id)
                self.used_identifiers.add(otp_id)
                self.master.after(0, lambda s=sender_id, m=decrypted: self.add_chat_message(f"From {s}: {m}", "received"))
            else:
                self.master.after(0, lambda: self.add_chat_message(f"From {sender_id}: [Unknown OTP]", "error"))
        except:
            self.master.after(0, lambda: self.add_chat_message("Received malformed message", "error"))
    
    def show_server_screen(self):
        self.clear_screen()
        self.create_header("🖥️ Relay Server")
        
        content = tk.Frame(self.container, bg='#0d1117', padx=30, pady=20)
        content.pack(fill=tk.BOTH, expand=True)
        
        status_frame = tk.Frame(content, bg='#161b22', padx=20, pady=15)
        status_frame.pack(fill=tk.X, pady=(0, 15))
        
        self.server_status_label = tk.Label(status_frame, text="● STOPPED", font=("Helvetica", 18, "bold"),
                                             fg='#f85149', bg='#161b22')
        self.server_status_label.pack(side=tk.LEFT)
        
        self.server_clients_label = tk.Label(status_frame, text="Clients: 0", font=("Helvetica", 12),
                                              fg='#8b949e', bg='#161b22')
        self.server_clients_label.pack(side=tk.RIGHT)
        
        info_frame = tk.Frame(content, bg='#161b22', padx=20, pady=15)
        info_frame.pack(fill=tk.X, pady=(0, 15))
        
        tk.Label(info_frame, text="Local Port:", fg='#8b949e', bg='#161b22').pack(side=tk.LEFT)
        self.server_port_entry = tk.Entry(info_frame, width=8, bg='#21262d', fg='white', insertbackground='white')
        self.server_port_entry.insert(0, "65432")
        self.server_port_entry.pack(side=tk.LEFT, padx=(5, 20))
        
        self.server_start_btn = tk.Button(info_frame, text="Start Server", bg='#238636', fg='white',
                                           activebackground='#2ea043', relief='flat', cursor='hand2',
                                           command=self.start_server)
        self.server_start_btn.pack(side=tk.LEFT, padx=5)
        
        self.server_stop_btn = tk.Button(info_frame, text="Stop Server", bg='#da3633', fg='white',
                                          activebackground='#f85149', relief='flat', cursor='hand2',
                                          state=tk.DISABLED, command=self.stop_server)
        self.server_stop_btn.pack(side=tk.LEFT, padx=5)
        
        self.server_ngrok_label = tk.Label(info_frame, text="", font=("Consolas", 11), fg='#58a6ff', bg='#161b22')
        self.server_ngrok_label.pack(side=tk.RIGHT)
        
        log_frame = tk.Frame(content, bg='#161b22', padx=15, pady=15)
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        tk.Label(log_frame, text="Activity Log", font=("Helvetica", 14, "bold"),
                 fg='#c9d1d9', bg='#161b22').pack(anchor='w', pady=(0, 10))
        
        self.server_log_area = scrolledtext.ScrolledText(log_frame, height=15, bg='#0d1117', fg='#c9d1d9',
                                                          font=("Consolas", 10), state=tk.DISABLED)
        self.server_log_area.pack(fill=tk.BOTH, expand=True)
    
    def server_log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        def update():
            self.server_log_area.config(state=tk.NORMAL)
            self.server_log_area.insert(tk.END, f"[{timestamp}] {message}\n")
            self.server_log_area.see(tk.END)
            self.server_log_area.config(state=tk.DISABLED)
        self.master.after(0, update)
    
    def update_server_client_count(self):
        def update():
            with self.server_clients_lock:
                count = len(self.server_clients)
            self.server_clients_label.config(text=f"Clients: {count}")
        self.master.after(0, update)
    
    def start_server(self):
        try:
            port = int(self.server_port_entry.get())
        except ValueError:
            messagebox.showerror("Error", "Invalid port number")
            return
        
        try:
            if NGROK_AVAILABLE:
                self.server_log("Starting ngrok tunnel...")
                self.ngrok_tunnel = ngrok.connect(port, "tcp")
                public_url = self.ngrok_tunnel.public_url
                parsed = public_url.replace("tcp://", "").split(":")
                self.server_ngrok_label.config(text=f"ngrok: {parsed[0]}:{parsed[1]}")
                self.server_log(f"Ngrok active: {public_url}")
            else:
                self.server_ngrok_label.config(text="ngrok unavailable")
            
            import socketserver
            kiosk = self
            
            class Handler(socketserver.BaseRequestHandler):
                def handle(self):
                    client_socket = self.request
                    user_id = None
                    try:
                        user_id = client_socket.recv(1024).decode("utf-8").strip()
                        if not user_id:
                            client_socket.sendall("ERROR|Invalid userID.".encode("utf-8"))
                            return
                        
                        with kiosk.server_clients_lock:
                            if user_id in kiosk.server_clients:
                                client_socket.sendall("ERROR|UserID already taken.".encode("utf-8"))
                                kiosk.server_log(f"Rejected '{user_id}' - ID in use")
                                return
                            kiosk.server_clients[user_id] = client_socket
                        
                        client_socket.sendall("OK|Connected.".encode("utf-8"))
                        kiosk.server_log(f"User '{user_id}' connected")
                        kiosk.update_server_client_count()
                        
                        while True:
                            data = client_socket.recv(8192)
                            if not data:
                                break
                            message = data.decode("utf-8")
                            try:
                                recipient_id, payload = message.split("|", 1)
                                kiosk.server_log(f"'{user_id}' -> '{recipient_id}'")
                                
                                with kiosk.server_clients_lock:
                                    recipient_socket = kiosk.server_clients.get(recipient_id)
                                
                                if recipient_socket:
                                    recipient_socket.sendall(f"{user_id}|{payload}".encode("utf-8"))
                                else:
                                    client_socket.sendall(f"SYSTEM|{recipient_id} is offline.".encode("utf-8"))
                            except ValueError:
                                pass
                    except:
                        pass
                    finally:
                        if user_id:
                            with kiosk.server_clients_lock:
                                if user_id in kiosk.server_clients:
                                    del kiosk.server_clients[user_id]
                            kiosk.server_log(f"User '{user_id}' disconnected")
                            kiosk.update_server_client_count()
            
            class ThreadedServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
                daemon_threads = True
                allow_reuse_address = True
            
            self.server = ThreadedServer(("0.0.0.0", port), Handler)
            threading.Thread(target=lambda: self.server.serve_forever(), daemon=True).start()
            
            self.server_status_label.config(text="● RUNNING", fg='#3fb950')
            self.server_start_btn.config(state=tk.DISABLED)
            self.server_stop_btn.config(state=tk.NORMAL)
            self.server_port_entry.config(state=tk.DISABLED)
            self.server_log(f"Server listening on port {port}")
            
        except Exception as e:
            self.server_log(f"Failed to start: {e}")
            messagebox.showerror("Error", f"Failed to start server: {e}")
    
    def stop_server(self):
        if self.server:
            self.server.shutdown()
            self.server = None
        
        with self.server_clients_lock:
            self.server_clients.clear()
        
        if self.ngrok_tunnel and NGROK_AVAILABLE:
            try:
                ngrok.disconnect(self.ngrok_tunnel.public_url)
            except:
                pass
            self.ngrok_tunnel = None
        
        self.server_status_label.config(text="● STOPPED", fg='#f85149')
        self.server_start_btn.config(state=tk.NORMAL)
        self.server_stop_btn.config(state=tk.DISABLED)
        self.server_port_entry.config(state=tk.NORMAL)
        self.server_ngrok_label.config(text="")
        self.server_log("Server stopped")
        self.update_server_client_count()
    
    def show_generator_screen(self):
        self.clear_screen()
        self.create_header("🎲 OTP Generator")
        
        content = tk.Frame(self.container, bg='#0d1117', padx=30, pady=20)
        content.pack(fill=tk.BOTH, expand=True)
        
        center = tk.Frame(content, bg='#0d1117')
        center.place(relx=0.5, rely=0.4, anchor='center')
        
        tk.Label(center, text="Generate True Random OTP Pages", font=("Helvetica", 20, "bold"),
                 fg='#c9d1d9', bg='#0d1117').pack(pady=(0, 10))
        tk.Label(center, text="Uses Raspberry Pi 5 Hardware RNG (/dev/hwrng)", font=("Helvetica", 12),
                 fg='#8b949e', bg='#0d1117').pack(pady=(0, 30))
        
        input_frame = tk.Frame(center, bg='#0d1117')
        input_frame.pack(pady=20)
        
        tk.Label(input_frame, text="Number of pages:", fg='#c9d1d9', bg='#0d1117',
                 font=("Helvetica", 14)).pack(side=tk.LEFT, padx=(0, 10))
        
        self.gen_pages_entry = tk.Entry(input_frame, width=10, bg='#21262d', fg='white',
                                         insertbackground='white', font=("Helvetica", 14))
        self.gen_pages_entry.insert(0, "10000")
        self.gen_pages_entry.pack(side=tk.LEFT)
        
        self.gen_button = tk.Button(center, text="Generate OTP File", font=("Helvetica", 14),
                                     bg='#6e40c9', fg='white', activebackground='#8957e5',
                                     relief='flat', cursor='hand2', width=20, height=2,
                                     command=self.start_generation)
        self.gen_button.pack(pady=30)
        
        self.gen_status_label = tk.Label(center, text="Ready", font=("Helvetica", 12),
                                          fg='#8b949e', bg='#0d1117')
        self.gen_status_label.pack()
        
        self.gen_progress = ttk.Progressbar(center, length=400, mode='determinate')
        self.gen_progress.pack(pady=20)
        
        if not os.path.exists(PI_HWRNG_DEVICE):
            self.gen_status_label.config(text="⚠️ /dev/hwrng not found - Not on Pi 5?", fg='#f85149')
            self.gen_button.config(state=tk.DISABLED)
    
    def start_generation(self):
        try:
            num_pages = int(self.gen_pages_entry.get())
            if num_pages <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid positive number.")
            return
        
        self.gen_button.config(state=tk.DISABLED)
        self.gen_progress['value'] = 0
        self.gen_progress['maximum'] = num_pages
        self.generating = True
        threading.Thread(target=self.generate_otp, args=(num_pages,), daemon=True).start()
    
    def generate_otp(self, num_pages):
        import string
        chars = string.ascii_uppercase + string.digits + string.punctuation
        charset_len = len(chars)
        limit = 204
        
        def generate_page(rng_file):
            result = []
            needed = PAGE_LENGTH
            while len(result) < PAGE_LENGTH:
                chunk = rng_file.read(needed * 4)
                if not chunk:
                    raise IOError("Failed to read from hardware RNG")
                for byte in chunk:
                    if byte < limit:
                        result.append(chars[byte % charset_len])
                        if len(result) == PAGE_LENGTH:
                            break
                needed = PAGE_LENGTH - len(result)
            return ''.join(result)
        
        try:
            with open(PI_HWRNG_DEVICE, "rb") as rng, open(OTP_FILE, "w", encoding="utf-8") as out:
                for i in range(1, num_pages + 1):
                    if not self.generating:
                        break
                    page = generate_page(rng)
                    out.write(page + "\n")
                    if i % 10 == 0:
                        self.master.after(0, lambda v=i: self.update_gen_progress(v, num_pages))
            
            self.otp_pages = load_otp_pages()
            self.used_identifiers = load_used_pages()
            self.master.after(0, lambda: self.gen_complete(num_pages))
        except PermissionError:
            self.master.after(0, lambda: self.gen_error("Permission denied. Need root access to /dev/hwrng"))
        except Exception as e:
            self.master.after(0, lambda: self.gen_error(str(e)))
    
    def update_gen_progress(self, current, total):
        self.gen_progress['value'] = current
        self.gen_status_label.config(text=f"Generating... {current}/{total} pages", fg='#58a6ff')
    
    def gen_complete(self, num_pages):
        self.gen_button.config(state=tk.NORMAL)
        self.gen_progress['value'] = num_pages
        self.gen_status_label.config(text=f"✓ Generated {num_pages} pages!", fg='#3fb950')
        self.generating = False
        messagebox.showinfo("Success", f"Generated {num_pages} OTP pages.\nSaved to {OTP_FILE}")
    
    def gen_error(self, error):
        self.gen_button.config(state=tk.NORMAL)
        self.gen_status_label.config(text=f"Error: {error}", fg='#f85149')
        self.generating = False
        messagebox.showerror("Error", error)


def main():
    root = tk.Tk()
    app = OTPKiosk(root)
    root.mainloop()


if __name__ == "__main__":
    main()
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
