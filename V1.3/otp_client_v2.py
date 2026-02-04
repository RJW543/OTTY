#!/usr/bin/env python3
"""
OTP Messaging Client v2 - Per-Contact Cipher Pads
Encrypts messages using contact-specific one-time pad pages.

Each contact has their own unique cipher pad:
    otp_data/contacts/<contact_id>/cipher.txt

Security:
    - A page used with Alice is NEVER available for Bob
    - Complete cryptographic separation between contacts
    - Perfect forward secrecy per contact relationship
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import socket
import threading
import os
import json
from pathlib import Path
from datetime import datetime

# Import helper
try:
    from otp_helper import OTPHelper
except ImportError:
    OTPHelper = None

# Optional TTS
try:
    import pyttsx3
    TTS_AVAILABLE = True
except ImportError:
    TTS_AVAILABLE = False


# --- CONFIGURATION ---
APP_DIR = Path(__file__).parent.resolve()
CREDENTIALS_FILE = APP_DIR / "credentials.txt"
CONTACTS_FILE = APP_DIR / "contacts.json"
PAGE_ID_LENGTH = 8


# --- ENCRYPTION ---

def xor_encrypt(plaintext: str, otp_content: str) -> str:
    """Encrypt plaintext using XOR with OTP content."""
    encrypted = []
    for i, char in enumerate(plaintext):
        if i >= len(otp_content):
            break
        encrypted.append(ord(char) ^ ord(otp_content[i]))
    return bytes(encrypted).hex()


def xor_decrypt(hex_encrypted: str, otp_content: str) -> str:
    """Decrypt hex-encoded message using XOR with OTP content."""
    try:
        encrypted = bytes.fromhex(hex_encrypted)
    except ValueError:
        return "[Decryption Error: Invalid data]"
    
    decrypted = []
    for i, byte in enumerate(encrypted):
        if i >= len(otp_content):
            break
        decrypted.append(chr(byte ^ ord(otp_content[i])))
    
    return ''.join(decrypted)


# --- HELPERS ---

def load_username():
    """Load username from credentials file."""
    if CREDENTIALS_FILE.exists():
        with open(CREDENTIALS_FILE, 'r') as f:
            for line in f:
                if line.startswith("Username:"):
                    return line.replace("Username:", "").strip()
    return None


def load_contacts():
    """Load contacts dictionary."""
    if CONTACTS_FILE.exists():
        try:
            with open(CONTACTS_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {}


def get_contact_name(contact_id: str, contacts: dict) -> str:
    """Get display name for a contact."""
    if contact_id in contacts:
        return contacts[contact_id].get('nickname', contact_id)
    return contact_id


# --- CLIENT GUI ---

class OTPClientGUI:
    """Main GUI for OTP messaging with per-contact pads."""
    
    def __init__(self, master):
        self.master = master
        self.master.title("OTP Secure Messenger v2")
        self.master.geometry("700x650")
        self.master.minsize(650, 550)
        
        # State
        self.client_socket = None
        self.user_id = None
        self.connected = False
        self.current_recipient = None
        
        # OTP Helper
        if OTPHelper:
            self.otp = OTPHelper()
        else:
            self.otp = None
            messagebox.showerror("Error", "otp_helper.py not found!")
        
        # Contacts
        self.contacts = load_contacts()
        
        # TTS
        self.tts = None
        if TTS_AVAILABLE:
            try:
                self.tts = pyttsx3.init()
            except:
                pass
        
        self.setup_ui()
        self.update_otp_status()
    
    def setup_ui(self):
        """Build the UI."""
        style = ttk.Style()
        style.theme_use('clam')
        
        main = ttk.Frame(self.master, padding="10")
        main.pack(fill=tk.BOTH, expand=True)
        
        # --- Connection ---
        conn_frame = ttk.LabelFrame(main, text="Connection", padding="10")
        conn_frame.pack(fill=tk.X, pady=(0, 10))
        
        server_row = ttk.Frame(conn_frame)
        server_row.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(server_row, text="Server:").pack(side=tk.LEFT)
        self.host_entry = ttk.Entry(server_row, width=25)
        self.host_entry.insert(0, "0.tcp.ngrok.io")
        self.host_entry.pack(side=tk.LEFT, padx=(5, 10))
        
        ttk.Label(server_row, text="Port:").pack(side=tk.LEFT)
        self.port_entry = ttk.Entry(server_row, width=8)
        self.port_entry.insert(0, "12345")
        self.port_entry.pack(side=tk.LEFT, padx=(5, 0))
        
        user_row = ttk.Frame(conn_frame)
        user_row.pack(fill=tk.X, pady=(5, 0))
        
        ttk.Label(user_row, text="Username:").pack(side=tk.LEFT)
        self.username_entry = ttk.Entry(user_row, width=20)
        self.username_entry.pack(side=tk.LEFT, padx=(5, 10))
        
        saved_user = load_username()
        if saved_user:
            self.username_entry.insert(0, saved_user)
        
        self.connect_btn = ttk.Button(user_row, text="Connect", command=self.connect)
        self.connect_btn.pack(side=tk.LEFT)
        
        self.disconnect_btn = ttk.Button(user_row, text="Disconnect", 
                                          command=self.disconnect, state=tk.DISABLED)
        self.disconnect_btn.pack(side=tk.LEFT, padx=(5, 0))
        
        self.status_label = ttk.Label(conn_frame, text="● Disconnected", foreground="red")
        self.status_label.pack(anchor=tk.W, pady=(5, 0))
        
        # --- OTP Status ---
        otp_frame = ttk.LabelFrame(main, text="OTP Status (Per-Contact Pads)", padding="5")
        otp_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.otp_status = ttk.Label(otp_frame, text="Loading...")
        self.otp_status.pack(anchor=tk.W)
        
        self.recipient_status = ttk.Label(otp_frame, text="", foreground='#666666')
        self.recipient_status.pack(anchor=tk.W)
        
        # Open Manager button
        ttk.Button(otp_frame, text="📋 Open OTP Manager", 
                  command=self.open_manager).pack(anchor=tk.W, pady=(5, 0))
        
        # --- Chat ---
        chat_frame = ttk.LabelFrame(main, text="Messages", padding="5")
        chat_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        self.chat_area = scrolledtext.ScrolledText(
            chat_frame, height=12, state=tk.DISABLED, font=("Consolas", 10)
        )
        self.chat_area.pack(fill=tk.BOTH, expand=True)
        
        self.chat_area.tag_configure("sent", foreground="#0066cc")
        self.chat_area.tag_configure("received", foreground="#006600")
        self.chat_area.tag_configure("system", foreground="#666666", font=("Consolas", 9, "italic"))
        self.chat_area.tag_configure("error", foreground="#cc0000")
        self.chat_area.tag_configure("warning", foreground="#cc6600")
        
        # --- Message Input ---
        input_frame = ttk.LabelFrame(main, text="Send Message", padding="10")
        input_frame.pack(fill=tk.X)
        
        # Recipient row
        recipient_row = ttk.Frame(input_frame)
        recipient_row.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(recipient_row, text="To:").pack(side=tk.LEFT)
        self.recipient_entry = ttk.Entry(recipient_row, width=20)
        self.recipient_entry.pack(side=tk.LEFT, padx=(5, 0))
        self.recipient_entry.bind('<FocusOut>', self.on_recipient_change)
        self.recipient_entry.bind('<Return>', self.on_recipient_change)
        
        # Pre-fill from environment
        env_recipient = os.environ.get('OTP_RECIPIENT')
        if env_recipient:
            self.recipient_entry.insert(0, env_recipient)
            self.current_recipient = env_recipient
        
        self.recipient_pages_label = ttk.Label(recipient_row, text="", foreground='#666666')
        self.recipient_pages_label.pack(side=tk.RIGHT)
        
        # Message row
        msg_row = ttk.Frame(input_frame)
        msg_row.pack(fill=tk.X)
        
        ttk.Label(msg_row, text="Message:").pack(side=tk.LEFT)
        self.message_entry = ttk.Entry(msg_row, width=40)
        self.message_entry.pack(side=tk.LEFT, padx=(5, 10), fill=tk.X, expand=True)
        self.message_entry.bind("<Return>", lambda e: self.send_message())
        
        self.send_btn = ttk.Button(msg_row, text="Send", command=self.send_message, state=tk.DISABLED)
        self.send_btn.pack(side=tk.LEFT)
        
        # Initial recipient update
        if env_recipient:
            self.update_recipient_status()
    
    def open_manager(self):
        """Open OTP Manager."""
        import subprocess
        import sys
        
        for name in ["otp_manager_v2.py", "otp_manager.py"]:
            path = APP_DIR / name
            if path.exists():
                subprocess.Popen([sys.executable, str(path)], cwd=str(APP_DIR))
                return
        
        messagebox.showerror("Error", "OTP Manager not found!")
    
    def on_recipient_change(self, event=None):
        """Handle recipient change."""
        recipient = self.recipient_entry.get().strip()
        if recipient != self.current_recipient:
            self.current_recipient = recipient
            self.update_recipient_status()
    
    def update_recipient_status(self):
        """Update status for current recipient."""
        if not self.otp or not self.current_recipient:
            self.recipient_pages_label.config(text="")
            return
        
        if not self.otp.contact_has_pad(self.current_recipient):
            self.recipient_pages_label.config(
                text=f"⚠️ No pad for {self.current_recipient[:8]}...",
                foreground='#cc0000'
            )
        else:
            available = self.otp.get_available_count(self.current_recipient)
            if available == 0:
                self.recipient_pages_label.config(
                    text="⚠️ No pages left!",
                    foreground='#cc0000'
                )
            elif available < 10:
                self.recipient_pages_label.config(
                    text=f"⚠️ Low: {available} pages",
                    foreground='#cc6600'
                )
            else:
                self.recipient_pages_label.config(
                    text=f"✓ {available} pages",
                    foreground='#006600'
                )
    
    def update_otp_status(self):
        """Update overall OTP status."""
        if not self.otp:
            self.otp_status.config(text="⚠️ OTP Helper not available", foreground='red')
            return
        
        stats = self.otp.get_statistics()
        
        if stats['num_contacts'] == 0:
            self.otp_status.config(
                text="No pads yet. Generate pads in OTP Manager.",
                foreground='orange'
            )
        else:
            self.otp_status.config(
                text=f"Contacts with pads: {stats['num_contacts']} | "
                     f"Total available: {stats['total_available']:,}",
                foreground='green'
            )
        
        # Show per-contact summary
        if stats['contacts']:
            summary = []
            for contact_id, data in list(stats['contacts'].items())[:3]:
                name = get_contact_name(contact_id, self.contacts)
                summary.append(f"{name[:10]}: {data['available']}")
            self.recipient_status.config(text=" | ".join(summary))
    
    def add_message(self, msg, tag="system"):
        """Add message to chat."""
        ts = datetime.now().strftime("%H:%M")
        self.chat_area.config(state=tk.NORMAL)
        self.chat_area.insert(tk.END, f"[{ts}] {msg}\n", tag)
        self.chat_area.see(tk.END)
        self.chat_area.config(state=tk.DISABLED)
    
    def connect(self):
        """Connect to server."""
        host = self.host_entry.get().strip()
        port_str = self.port_entry.get().strip()
        username = self.username_entry.get().strip()
        
        if not host or not port_str or not username:
            messagebox.showwarning("Warning", "Fill in all fields")
            return
        
        try:
            port = int(port_str)
        except ValueError:
            messagebox.showwarning("Warning", "Invalid port")
            return
        
        self.add_message(f"Connecting to {host}:{port}...", "system")
        
        try:
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client_socket.settimeout(10)
            self.client_socket.connect((host, port))
            self.client_socket.settimeout(None)
            
            self.client_socket.sendall(username.encode('utf-8'))
            response = self.client_socket.recv(1024).decode('utf-8')
            
            if response.startswith("ERROR"):
                self.add_message(f"Failed: {response}", "error")
                self.client_socket.close()
                self.client_socket = None
                return
            
            self.user_id = username
            self.connected = True
            
            self.status_label.config(text=f"● Connected as '{username}'", foreground='green')
            self.connect_btn.config(state=tk.DISABLED)
            self.disconnect_btn.config(state=tk.NORMAL)
            self.send_btn.config(state=tk.NORMAL)
            self.host_entry.config(state=tk.DISABLED)
            self.port_entry.config(state=tk.DISABLED)
            self.username_entry.config(state=tk.DISABLED)
            
            self.add_message("Connected!", "system")
            
            threading.Thread(target=self.receive_loop, daemon=True).start()
            
        except socket.timeout:
            self.add_message("Connection timed out", "error")
        except ConnectionRefusedError:
            self.add_message("Connection refused", "error")
        except Exception as e:
            self.add_message(f"Error: {e}", "error")
    
    def disconnect(self):
        """Disconnect from server."""
        self.connected = False
        
        if self.client_socket:
            try:
                self.client_socket.close()
            except:
                pass
            self.client_socket = None
        
        self.status_label.config(text="● Disconnected", foreground='red')
        self.connect_btn.config(state=tk.NORMAL)
        self.disconnect_btn.config(state=tk.DISABLED)
        self.send_btn.config(state=tk.DISABLED)
        self.host_entry.config(state=tk.NORMAL)
        self.port_entry.config(state=tk.NORMAL)
        self.username_entry.config(state=tk.NORMAL)
        
        self.add_message("Disconnected", "system")
    
    def send_message(self):
        """Encrypt and send a message."""
        if not self.connected or not self.otp:
            return
        
        recipient = self.recipient_entry.get().strip()
        message = self.message_entry.get().strip()
        
        if not recipient or not message:
            return
        
        if recipient == self.user_id:
            messagebox.showwarning("Warning", "Cannot message yourself")
            return
        
        # Check if we have a pad for this recipient
        if not self.otp.contact_has_pad(recipient):
            messagebox.showerror(
                "No Cipher Pad",
                f"No cipher pad exists for {recipient}!\n\n"
                "Use OTP Manager to:\n"
                "1. Generate a pad for this contact, OR\n"
                "2. Receive their pad via Bluetooth"
            )
            return
        
        # Get next available page
        result = self.otp.get_page_for_contact(recipient)
        
        if not result:
            messagebox.showerror(
                "No Pages Left",
                f"All pages for {recipient} have been used!\n\n"
                "Generate a new pad or receive more pages via Bluetooth."
            )
            self.update_recipient_status()
            return
        
        page_id, page_content = result
        
        # Check message length
        if len(message) > len(page_content):
            messagebox.showwarning("Warning", f"Message too long (max {len(page_content)} chars)")
            return
        
        # Encrypt
        encrypted = xor_encrypt(message, page_content)
        
        # Send: recipient|page_id:encrypted_hex
        full_msg = f"{recipient}|{page_id}:{encrypted}"
        
        try:
            self.client_socket.sendall(full_msg.encode('utf-8'))
            self.message_entry.delete(0, tk.END)
            
            name = get_contact_name(recipient, self.contacts)
            self.add_message(f"To {name}: {message}", "sent")
            
            self.update_otp_status()
            self.update_recipient_status()
            
        except Exception as e:
            self.add_message(f"Send failed: {e}", "error")
    
    def receive_loop(self):
        """Background thread to receive messages."""
        while self.connected and self.client_socket:
            try:
                data = self.client_socket.recv(8192)
                if not data:
                    break
                
                self.process_message(data.decode('utf-8'))
                
            except ConnectionResetError:
                break
            except Exception as e:
                if self.connected:
                    self.master.after(0, lambda: self.add_message(f"Receive error: {e}", "error"))
                break
        
        if self.connected:
            self.master.after(0, self.handle_disconnect)
    
    def process_message(self, raw):
        """Parse and decrypt received message."""
        try:
            sender_id, payload = raw.split("|", 1)
            
            # System messages
            if sender_id == "SYSTEM":
                if payload.startswith("offline:"):
                    msg = payload.replace("offline:", "")
                    self.master.after(0, lambda: self.add_message(msg, "system"))
                return
            
            page_id, encrypted = payload.split(":", 1)
            
            # Find the page in sender's pad
            if self.otp:
                page_content = self.otp.find_page_for_decryption(page_id, sender_id)
            else:
                page_content = None
            
            if page_content:
                decrypted = xor_decrypt(encrypted, page_content)
                self.master.after(0, lambda s=sender_id, m=decrypted: self.display_received(s, m))
            else:
                self.master.after(0, lambda: self.add_message(
                    f"From {sender_id}: [Cannot decrypt - no matching page {page_id}]",
                    "warning"
                ))
                
        except ValueError:
            self.master.after(0, lambda: self.add_message("Malformed message", "error"))
    
    def display_received(self, sender, message):
        """Display received message."""
        name = get_contact_name(sender, self.contacts)
        self.add_message(f"From {name}: {message}", "received")
        self.update_otp_status()
        
        # TTS
        if self.tts:
            threading.Thread(target=self.speak, args=(message,), daemon=True).start()
    
    def speak(self, text):
        """Speak message via TTS."""
        if self.tts:
            try:
                self.tts.say(text)
                self.tts.runAndWait()
            except:
                pass
    
    def handle_disconnect(self):
        """Handle unexpected disconnect."""
        self.disconnect()
        messagebox.showwarning("Disconnected", "Lost connection to server")


def main():
    root = tk.Tk()
    
    # Show disclaimer
    messagebox.showinfo(
        "OTP Secure Messenger v2",
        "Per-Contact Cipher Pads\n\n"
        "Each contact has their own unique cipher pad.\n"
        "A pad shared with Alice is NEVER used with Bob.\n\n"
        "Before messaging someone:\n"
        "1. Generate a pad for them (OTP Manager)\n"
        "2. Share the pad via Bluetooth when you meet\n\n"
        "Perfect secrecy requires:\n"
        "• Truly random pads\n"
        "• Each page used only once\n"
        "• Pads kept secret"
    )
    
    app = OTPClientGUI(root)
    
    def on_close():
        if app.connected:
            app.disconnect()
        root.destroy()
    
    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
