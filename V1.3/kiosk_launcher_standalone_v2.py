#!/usr/bin/env python3
"""
OTP Kiosk Launcher - Standalone Version with Voice & Bluetooth Support
Run this directly to get a kiosk-style interface without system configuration.

Includes:
- Contacts Hub (central communication manager)
- OTP Text Messenger (OTP encryption)
- OTP Voice Client (AES-256 encrypted calls)
- OTP Bluetooth Share (secure key exchange)
- OTP Generator (Hardware RNG)
- Relay Server

Usage: python3 kiosk_launcher_standalone.py

For testing: Press Escape 3 times quickly to exit fullscreen
For production: Set PRODUCTION_MODE = True below
"""

import tkinter as tk
from tkinter import ttk, messagebox
import subprocess
import os
import sys
import time
import json
from pathlib import Path

# --- CONFIGURATION ---
PRODUCTION_MODE = False  # Set to True to disable escape exit
APP_DIR = Path(__file__).parent.resolve()
CONFIG_FILE = APP_DIR / "device_config.json"


class KioskLauncher:
    def __init__(self, master):
        self.master = master
        self.master.title("OTP Secure Communications")
        
        # Fullscreen
        self.master.attributes('-fullscreen', True)
        self.master.configure(bg='#0d1117')
        
        # Escape handling
        self.escape_count = 0
        self.last_escape_time = 0
        
        if PRODUCTION_MODE:
            # Block all escape methods
            self.master.protocol("WM_DELETE_WINDOW", lambda: None)
            self.master.bind('<Alt-F4>', lambda e: "break")
            self.master.bind('<Control-c>', lambda e: "break")
            self.master.bind('<Control-q>', lambda e: "break")
            self.master.bind('<Escape>', lambda e: "break")
        else:
            # Allow escape for testing
            self.master.bind('<Escape>', self.handle_escape)
        
        self.running_processes = []
        self.device_id = self.load_device_id()
        self.setup_ui()
        self.update_status()
    
    def load_device_id(self):
        """Load device ID from config if available."""
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, 'r') as f:
                    data = json.load(f)
                    return data.get('device_id')
            except:
                pass
        return None
    
    def handle_escape(self, event):
        """Triple-escape to exit (testing mode only)"""
        now = time.time()
        if now - self.last_escape_time < 0.5:
            self.escape_count += 1
        else:
            self.escape_count = 1
        self.last_escape_time = now
        
        if self.escape_count >= 3:
            self.exit_kiosk()
        return "break"
    
    def exit_kiosk(self):
        """Exit kiosk mode"""
        if messagebox.askyesno("Exit", "Exit kiosk mode?"):
            for proc in self.running_processes:
                try:
                    proc.terminate()
                except:
                    pass
            self.master.destroy()
    
    def setup_ui(self):
        # Main container
        main = tk.Frame(self.master, bg='#0d1117')
        main.place(relx=0.5, rely=0.5, anchor='center')
        
        # Header
        header = tk.Label(
            main,
            text="🔐",
            font=("Helvetica", 48),
            fg='#58a6ff',
            bg='#0d1117'
        )
        header.pack(pady=(0, 10))
        
        title = tk.Label(
            main,
            text="OTP Secure Communications",
            font=("Helvetica", 32, "bold"),
            fg='#c9d1d9',
            bg='#0d1117'
        )
        title.pack(pady=(0, 10))
        
        subtitle = tk.Label(
            main,
            text="Encrypted Messaging • Voice Calls • Bluetooth Key Exchange",
            font=("Helvetica", 12),
            fg='#8b949e',
            bg='#0d1117'
        )
        subtitle.pack(pady=(0, 30))
        
        # Device ID display (if configured)
        if self.device_id:
            id_frame = tk.Frame(main, bg='#161b22', padx=15, pady=8)
            id_frame.pack(pady=(0, 30))
            
            tk.Label(
                id_frame,
                text="Device ID: ",
                font=("Helvetica", 10),
                fg='#8b949e',
                bg='#161b22'
            ).pack(side=tk.LEFT)
            
            tk.Label(
                id_frame,
                text=self.device_id,
                font=("Consolas", 11, "bold"),
                fg='#58a6ff',
                bg='#161b22'
            ).pack(side=tk.LEFT)
        
        # MAIN CONTACTS BUTTON (Primary action)
        contacts_btn = tk.Button(
            main,
            text="📱  Open Contacts",
            command=self.launch_contacts,
            font=("Helvetica", 16, "bold"),
            width=24,
            height=2,
            bg='#238636',
            fg='white',
            activebackground='#2ea043',
            activeforeground='white',
            relief='flat',
            cursor='hand2',
            bd=0
        )
        contacts_btn.pack(pady=(0, 30))
        
        # Separator
        tk.Label(
            main,
            text="─────────  or launch directly  ─────────",
            font=("Helvetica", 9),
            fg='#484f58',
            bg='#0d1117'
        ).pack(pady=(0, 20))
        
        # Button container - three columns for direct launch
        btn_container = tk.Frame(main, bg='#0d1117')
        btn_container.pack()
        
        left_col = tk.Frame(btn_container, bg='#0d1117')
        left_col.pack(side=tk.LEFT, padx=15)
        
        center_col = tk.Frame(btn_container, bg='#0d1117')
        center_col.pack(side=tk.LEFT, padx=15)
        
        right_col = tk.Frame(btn_container, bg='#0d1117')
        right_col.pack(side=tk.LEFT, padx=15)
        
        # Style for buttons
        def create_button(parent, text, command, color='#21262d', width=18):
            btn = tk.Button(
                parent,
                text=text,
                command=command,
                font=("Helvetica", 11),
                width=width,
                height=2,
                bg=color,
                fg='white',
                activebackground=self.lighten_color(color),
                activeforeground='white',
                relief='flat',
                cursor='hand2',
                bd=0
            )
            return btn
        
        # Left column - Communication
        comm_label = tk.Label(
            left_col,
            text="📡 Communication",
            font=("Helvetica", 10, "bold"),
            fg='#8b949e',
            bg='#0d1117'
        )
        comm_label.pack(pady=(0, 8))
        
        # Messenger button
        client_btn = create_button(
            left_col,
            "📨  Text Messenger",
            self.launch_client
        )
        client_btn.pack(pady=5)
        
        # Voice button
        voice_btn = create_button(
            left_col,
            "🎤  Voice Calls",
            self.launch_voice
        )
        voice_btn.pack(pady=5)
        
        # Center column - Key Exchange
        key_label = tk.Label(
            center_col,
            text="🔑 Key Exchange",
            font=("Helvetica", 10, "bold"),
            fg='#8b949e',
            bg='#0d1117'
        )
        key_label.pack(pady=(0, 8))
        
        # Bluetooth Share button (highlighted)
        bt_btn = create_button(
            center_col,
            "📡  Bluetooth Share",
            self.launch_bluetooth,
            color='#1f6feb'  # Blue highlight
        )
        bt_btn.pack(pady=5)
        
        # Generator button
        gen_btn = create_button(
            center_col,
            "🎲  OTP Generator",
            self.launch_generator
        )
        gen_btn.pack(pady=5)
        
        # Right column - System
        sys_label = tk.Label(
            right_col,
            text="⚙️ System",
            font=("Helvetica", 10, "bold"),
            fg='#8b949e',
            bg='#0d1117'
        )
        sys_label.pack(pady=(0, 8))
        
        # Server button
        server_btn = create_button(
            right_col,
            "🖥️  Relay Server",
            self.launch_server
        )
        server_btn.pack(pady=5)
        
        # Placeholder for alignment
        placeholder = tk.Frame(right_col, height=45, bg='#0d1117')
        placeholder.pack(pady=5)
        
        # Status panel
        status_frame = tk.Frame(main, bg='#161b22', padx=25, pady=15)
        status_frame.pack(pady=(35, 0))
        
        self.otp_status = tk.Label(
            status_frame,
            text="Checking OTP status...",
            font=("Consolas", 11),
            fg='#8b949e',
            bg='#161b22'
        )
        self.otp_status.pack()
        
        self.process_status = tk.Label(
            status_frame,
            text="",
            font=("Consolas", 10),
            fg='#8b949e',
            bg='#161b22'
        )
        self.process_status.pack(pady=(5, 0))
        
        self.deps_status = tk.Label(
            status_frame,
            text="",
            font=("Consolas", 9),
            fg='#6e7681',
            bg='#161b22'
        )
        self.deps_status.pack(pady=(5, 0))
        
        # Footer
        footer_text = "Kiosk Mode Active"
        if not PRODUCTION_MODE:
            footer_text += " | Press ESC 3x to exit"
        
        footer = tk.Label(
            self.master,
            text=footer_text,
            font=("Helvetica", 9),
            fg='#484f58',
            bg='#0d1117'
        )
        footer.pack(side='bottom', pady=15)
        
        # Check dependencies on startup
        self.check_dependencies()
    
    def lighten_color(self, hex_color):
        """Lighten a hex color for hover effect."""
        hex_color = hex_color.lstrip('#')
        r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        r = min(255, int(r * 1.2))
        g = min(255, int(g * 1.2))
        b = min(255, int(b * 1.2))
        return f'#{r:02x}{g:02x}{b:02x}'
    
    def check_dependencies(self):
        """Check if required Python packages are available."""
        missing = []
        optional_missing = []
        
        try:
            import pyaudio
        except ImportError:
            missing.append("pyaudio")
        
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError:
            missing.append("cryptography")
        
        try:
            from pyngrok import ngrok
        except ImportError:
            optional_missing.append("pyngrok")
        
        try:
            import bluetooth
        except ImportError:
            optional_missing.append("pybluez (for Bluetooth sharing)")
        
        if missing:
            self.deps_status.config(
                text=f"⚠️ Required: pip install {' '.join(missing)}",
                fg='#f85149'
            )
        elif optional_missing:
            self.deps_status.config(
                text=f"ℹ️ Optional: {', '.join(optional_missing)}",
                fg='#d29922'
            )
        else:
            self.deps_status.config(
                text="✓ All dependencies installed",
                fg='#3fb950'
            )
    
    def update_status(self):
        """Update OTP and process status"""
        # Count OTP pages
        otp_file = APP_DIR / "otp_cipher.txt"
        used_file = APP_DIR / "used_pages.txt"
        
        total = 0
        used = 0
        
        if otp_file.exists():
            with open(otp_file) as f:
                total = sum(1 for line in f if len(line.strip()) > 8)
        
        if used_file.exists():
            with open(used_file) as f:
                used = sum(1 for line in f if line.strip())
        
        available = total - used
        
        if total == 0:
            self.otp_status.config(
                text="⚠️  No OTP file found - Generate pages first",
                fg='#f85149'
            )
        elif available == 0:
            self.otp_status.config(
                text="⚠️  All OTP pages used - Generate more",
                fg='#f85149'
            )
        elif available < 100:
            self.otp_status.config(
                text=f"⚠️  Low: {available} pages remaining",
                fg='#d29922'
            )
        else:
            self.otp_status.config(
                text=f"✓  {available:,} OTP pages available",
                fg='#3fb950'
            )
        
        # Clean up finished processes
        self.running_processes = [p for p in self.running_processes if p.poll() is None]
        
        if self.running_processes:
            self.process_status.config(text=f"Running: {len(self.running_processes)} app(s)")
        else:
            self.process_status.config(text="")
        
        # Schedule next update
        self.master.after(2000, self.update_status)
    
    def launch_app(self, filename):
        """Launch an OTP application"""
        path = APP_DIR / filename
        if path.exists():
            proc = subprocess.Popen(
                [sys.executable, str(path)],
                cwd=str(APP_DIR)
            )
            self.running_processes.append(proc)
        else:
            messagebox.showerror("Error", f"{filename} not found in {APP_DIR}")
    
    def launch_contacts(self):
        """Launch the Contacts app (main communication hub)"""
        self.launch_app("otp_contacts.py")
    
    def launch_client(self):
        self.launch_app("otp_client.py")
    
    def launch_voice(self):
        self.launch_app("otp_voice_client.py")
    
    def launch_bluetooth(self):
        """Launch the Bluetooth Share app"""
        self.launch_app("otp_bluetooth_share.py")
    
    def launch_server(self):
        # Try voice-enabled server first, fall back to basic
        if (APP_DIR / "otp_relay_server_voice.py").exists():
            self.launch_app("otp_relay_server_voice.py")
        else:
            self.launch_app("otp_relay_server.py")
    
    def launch_generator(self):
        self.launch_app("otp_generator.py")


def main():
    root = tk.Tk()
    
    # Check if required files exist
    required = ["otp_contacts.py", "otp_client.py"]
    optional = [
        "otp_relay_server.py",
        "otp_relay_server_voice.py",
        "otp_voice_client.py",
        "otp_generator.py",
        "otp_bluetooth_share.py"
    ]
    
    missing_required = [f for f in required if not (APP_DIR / f).exists()]
    missing_optional = [f for f in optional if not (APP_DIR / f).exists()]
    
    if missing_required:
        messagebox.showerror(
            "Missing Required Files",
            f"The following required files were not found in {APP_DIR}:\n\n" +
            "\n".join(f"• {f}" for f in missing_required) +
            "\n\nCannot start kiosk."
        )
        return
    
    if missing_optional:
        # Just show a subtle warning, don't block startup
        print(f"Note: Some optional files not found: {', '.join(missing_optional)}")
    
    app = KioskLauncher(root)
    root.mainloop()


if __name__ == "__main__":
    main()
