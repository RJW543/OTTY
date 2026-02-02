#!/usr/bin/env python3
"""
OTP Kiosk Launcher - Standalone Version
Run this directly to get a kiosk-style interface without system configuration.

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
from pathlib import Path

# --- CONFIGURATION ---
PRODUCTION_MODE = False  # Set to True to disable escape exit
APP_DIR = Path(__file__).parent.resolve()


class KioskLauncher:
    def __init__(self, master):
        self.master = master
        self.master.title("OTP Secure Messaging System")
        
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
        self.setup_ui()
        self.update_status()
    
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
            text="OTP Secure Messaging",
            font=("Helvetica", 32, "bold"),
            fg='#c9d1d9',
            bg='#0d1117'
        )
        title.pack(pady=(0, 10))
        
        subtitle = tk.Label(
            main,
            text="One-Time Pad Encrypted Communications",
            font=("Helvetica", 12),
            fg='#8b949e',
            bg='#0d1117'
        )
        subtitle.pack(pady=(0, 40))
        
        # Button container
        btn_frame = tk.Frame(main, bg='#0d1117')
        btn_frame.pack()
        
        # Style for buttons
        def create_button(parent, text, command, color='#238636'):
            btn = tk.Button(
                parent,
                text=text,
                command=command,
                font=("Helvetica", 14),
                width=24,
                height=2,
                bg=color,
                fg='white',
                activebackground='#2ea043',
                activeforeground='white',
                relief='flat',
                cursor='hand2',
                bd=0
            )
            return btn
        
        # Messenger button
        client_btn = create_button(
            btn_frame,
            "📨  Start Messenger",
            self.launch_client,
            '#238636'
        )
        client_btn.pack(pady=8)
        
        # Server button
        server_btn = create_button(
            btn_frame,
            "🖥️  Start Relay Server",
            self.launch_server,
            '#1f6feb'
        )
        server_btn.pack(pady=8)
        
        # Generator button (if hwrng available or for testing)
        gen_btn = create_button(
            btn_frame,
            "🎲  Generate OTP Pages",
            self.launch_generator,
            '#6e40c9'
        )
        gen_btn.pack(pady=8)
        
        # Status panel
        status_frame = tk.Frame(main, bg='#161b22', padx=20, pady=15)
        status_frame.pack(pady=(30, 0))
        
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
    
    def launch_client(self):
        self.launch_app("otp_client.py")
    
    def launch_server(self):
        self.launch_app("otp_relay_server.py")
    
    def launch_generator(self):
        self.launch_app("otp_generator.py")


def main():
    root = tk.Tk()
    
    # Check if required files exist
    required = ["otp_client.py", "otp_relay_server.py"]
    missing = [f for f in required if not (APP_DIR / f).exists()]
    
    if missing:
        messagebox.showwarning(
            "Missing Files",
            f"The following files were not found in {APP_DIR}:\n\n" +
            "\n".join(f"• {f}" for f in missing) +
            "\n\nSome features may not work."
        )
    
    app = KioskLauncher(root)
    root.mainloop()


if __name__ == "__main__":
    main()
