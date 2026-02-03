#!/usr/bin/env python3
"""
OTP Bluetooth Share - Secure Key Exchange
Allows two users to share one-time pad pages over Bluetooth when physically near each other.

This is the secure "key exchange" phase required for OTP communication.
Both users end up with identical OTP pages that can then be used for encrypted messaging.

Features:
- Bluetooth device discovery
- Secure page transfer with verification
- Progress tracking
- Contact association
- SHA-256 verification of transferred pages

Requirements:
    sudo apt-get install bluetooth bluez libbluetooth-dev
    pip install pybluez

Usage:
    python3 otp_bluetooth_share.py

Security Note:
    This transfer should only be done when you have physically verified
    the identity of the person you're sharing keys with.
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import hashlib
import json
import os
import sys
import time
import uuid
from pathlib import Path
from datetime import datetime

# Try to import Bluetooth library
try:
    import bluetooth
    BLUETOOTH_AVAILABLE = True
except ImportError:
    BLUETOOTH_AVAILABLE = False

# --- CONFIGURATION ---
APP_DIR = Path(__file__).parent.resolve()
OTP_FILE = APP_DIR / "otp_cipher.txt"
USED_PAGES_FILE = APP_DIR / "used_pages.txt"
CONTACTS_FILE = APP_DIR / "contacts.json"
DEVICE_CONFIG_FILE = APP_DIR / "device_config.json"
SHARED_PAGES_FILE = APP_DIR / "shared_pages.json"  # Track which pages shared with whom

# Bluetooth settings
SERVICE_NAME = "OTP-KeyExchange"
SERVICE_UUID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
PAGE_ID_LENGTH = 8
CHUNK_SIZE = 4096  # Bytes per Bluetooth transfer chunk


# --- OTP PAGE MANAGEMENT ---

def load_otp_pages():
    """Load all OTP pages from file."""
    pages = []
    if not OTP_FILE.exists():
        return pages
    
    with open(OTP_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.rstrip('\n')
            if len(line) >= PAGE_ID_LENGTH + 1:
                pages.append(line)
    return pages


def load_used_pages():
    """Load set of used page identifiers."""
    if not USED_PAGES_FILE.exists():
        return set()
    
    with open(USED_PAGES_FILE, 'r', encoding='utf-8') as f:
        return {line.strip() for line in f if line.strip()}


def load_shared_pages():
    """Load record of which pages have been shared with whom."""
    if not SHARED_PAGES_FILE.exists():
        return {}
    
    try:
        with open(SHARED_PAGES_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def save_shared_pages(shared_data):
    """Save shared pages record."""
    with open(SHARED_PAGES_FILE, 'w') as f:
        json.dump(shared_data, f, indent=2)


def get_available_pages(exclude_used=True, exclude_shared=False):
    """
    Get list of available OTP pages.
    
    Args:
        exclude_used: Exclude pages that have been used for messaging
        exclude_shared: Exclude pages that have been shared with anyone
    
    Returns:
        List of (page_id, full_page_content) tuples
    """
    all_pages = load_otp_pages()
    used = load_used_pages() if exclude_used else set()
    shared = load_shared_pages() if exclude_shared else {}
    
    available = []
    shared_ids = set()
    
    if exclude_shared:
        for contact_shares in shared.values():
            shared_ids.update(contact_shares.get('page_ids', []))
    
    for page in all_pages:
        page_id = page[:PAGE_ID_LENGTH]
        if page_id not in used and page_id not in shared_ids:
            available.append((page_id, page))
    
    return available


def add_pages_to_file(pages):
    """Append new pages to the OTP file."""
    with open(OTP_FILE, 'a', encoding='utf-8') as f:
        for page in pages:
            f.write(page + '\n')


def record_shared_pages(contact_id, page_ids, direction='sent'):
    """Record that pages were shared with a contact."""
    shared = load_shared_pages()
    
    if contact_id not in shared:
        shared[contact_id] = {
            'page_ids': [],
            'shared_at': [],
            'direction': direction
        }
    
    timestamp = datetime.now().isoformat()
    shared[contact_id]['page_ids'].extend(page_ids)
    shared[contact_id]['shared_at'].append({
        'timestamp': timestamp,
        'count': len(page_ids),
        'direction': direction
    })
    
    save_shared_pages(shared)


def load_device_id():
    """Load this device's ID from config."""
    if DEVICE_CONFIG_FILE.exists():
        try:
            with open(DEVICE_CONFIG_FILE, 'r') as f:
                data = json.load(f)
                return data.get('device_id')
        except:
            pass
    return None


def load_contacts():
    """Load contacts list."""
    if CONTACTS_FILE.exists():
        try:
            with open(CONTACTS_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {}


# --- CHECKSUM UTILITIES ---

def calculate_pages_hash(pages):
    """Calculate SHA-256 hash of pages for verification."""
    hasher = hashlib.sha256()
    for page in sorted(pages):  # Sort for consistent ordering
        hasher.update(page.encode('utf-8'))
    return hasher.hexdigest()


def calculate_page_hash(page):
    """Calculate hash of a single page."""
    return hashlib.sha256(page.encode('utf-8')).hexdigest()[:16]


# --- BLUETOOTH SERVER (RECEIVER) ---

class BluetoothServer(threading.Thread):
    """Bluetooth server that receives OTP pages from another device."""
    
    def __init__(self, callback, status_callback):
        super().__init__(daemon=True)
        self.callback = callback  # Called when pages received
        self.status_callback = status_callback  # Called for status updates
        self.running = False
        self.server_socket = None
    
    def run(self):
        self.running = True
        
        try:
            # Create Bluetooth socket
            self.server_socket = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
            self.server_socket.bind(("", bluetooth.PORT_ANY))
            self.server_socket.listen(1)
            
            port = self.server_socket.getsockname()[1]
            
            # Advertise service
            bluetooth.advertise_service(
                self.server_socket,
                SERVICE_NAME,
                service_id=SERVICE_UUID,
                service_classes=[SERVICE_UUID, bluetooth.SERIAL_PORT_CLASS],
                profiles=[bluetooth.SERIAL_PORT_PROFILE]
            )
            
            self.status_callback(f"Waiting for connection on RFCOMM channel {port}...")
            self.status_callback("Make sure Bluetooth is discoverable!")
            
            # Accept connection
            self.server_socket.settimeout(300)  # 5 minute timeout
            client_socket, client_info = self.server_socket.accept()
            
            self.status_callback(f"Connected to {client_info[0]}")
            
            # Receive data
            self.receive_pages(client_socket)
            
            client_socket.close()
            
        except bluetooth.BluetoothError as e:
            self.status_callback(f"Bluetooth error: {e}")
        except TimeoutError:
            self.status_callback("Connection timed out (5 minutes)")
        except Exception as e:
            self.status_callback(f"Error: {e}")
        finally:
            self.stop()
    
    def receive_pages(self, sock):
        """Receive OTP pages from the connected device."""
        try:
            # Receive header (JSON with metadata)
            header_data = b""
            while True:
                chunk = sock.recv(1024)
                header_data += chunk
                if b"\n---END_HEADER---\n" in header_data:
                    break
            
            header_json, _ = header_data.split(b"\n---END_HEADER---\n", 1)
            header = json.loads(header_json.decode('utf-8'))
            
            sender_id = header.get('sender_id', 'unknown')
            num_pages = header.get('num_pages', 0)
            expected_hash = header.get('hash')
            
            self.status_callback(f"Receiving {num_pages} pages from {sender_id}...")
            
            # Send acknowledgment
            sock.send(b"ACK_HEADER\n")
            
            # Receive pages
            pages_data = b""
            while True:
                chunk = sock.recv(CHUNK_SIZE)
                if not chunk:
                    break
                pages_data += chunk
                if b"\n---END_PAGES---\n" in pages_data:
                    break
                
                # Progress update
                progress = len(pages_data) / (num_pages * 3500) * 100
                self.status_callback(f"Receiving... {min(progress, 100):.1f}%")
            
            pages_json, _ = pages_data.split(b"\n---END_PAGES---\n", 1)
            pages = json.loads(pages_json.decode('utf-8'))
            
            # Verify hash
            received_hash = calculate_pages_hash(pages)
            if received_hash != expected_hash:
                sock.send(b"ERROR: Hash mismatch!\n")
                self.status_callback("ERROR: Hash verification failed!")
                return
            
            # Send confirmation
            sock.send(f"OK: Received {len(pages)} pages\n".encode('utf-8'))
            
            # Save pages and record sharing
            self.status_callback(f"Verified {len(pages)} pages. Saving...")
            
            page_ids = [p[:PAGE_ID_LENGTH] for p in pages]
            add_pages_to_file(pages)
            record_shared_pages(sender_id, page_ids, direction='received')
            
            self.status_callback(f"SUCCESS: Received {len(pages)} OTP pages from {sender_id}")
            self.callback(pages, sender_id)
            
        except Exception as e:
            self.status_callback(f"Receive error: {e}")
            raise
    
    def stop(self):
        self.running = False
        if self.server_socket:
            try:
                bluetooth.stop_advertising(self.server_socket)
                self.server_socket.close()
            except:
                pass
            self.server_socket = None


# --- BLUETOOTH CLIENT (SENDER) ---

class BluetoothClient(threading.Thread):
    """Bluetooth client that sends OTP pages to another device."""
    
    def __init__(self, target_address, pages, contact_id, callback, status_callback):
        super().__init__(daemon=True)
        self.target_address = target_address
        self.pages = pages
        self.contact_id = contact_id
        self.callback = callback
        self.status_callback = status_callback
        self.running = False
    
    def run(self):
        self.running = True
        sock = None
        
        try:
            self.status_callback(f"Connecting to {self.target_address}...")
            
            # Find the service
            services = bluetooth.find_service(
                uuid=SERVICE_UUID,
                address=self.target_address
            )
            
            if not services:
                # Try direct connection on common RFCOMM channels
                self.status_callback("Service not found, trying direct connection...")
                port = 1  # Default RFCOMM channel
            else:
                port = services[0]["port"]
            
            # Connect
            sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
            sock.connect((self.target_address, port))
            
            self.status_callback("Connected! Sending pages...")
            
            # Send pages
            self.send_pages(sock)
            
        except bluetooth.BluetoothError as e:
            self.status_callback(f"Bluetooth error: {e}")
        except Exception as e:
            self.status_callback(f"Error: {e}")
        finally:
            if sock:
                sock.close()
            self.running = False
    
    def send_pages(self, sock):
        """Send OTP pages to the connected device."""
        try:
            device_id = load_device_id() or "unknown"
            pages_hash = calculate_pages_hash(self.pages)
            
            # Send header
            header = {
                'sender_id': device_id,
                'num_pages': len(self.pages),
                'hash': pages_hash,
                'timestamp': datetime.now().isoformat()
            }
            
            header_data = json.dumps(header).encode('utf-8') + b"\n---END_HEADER---\n"
            sock.send(header_data)
            
            # Wait for acknowledgment
            ack = sock.recv(1024)
            if b"ACK_HEADER" not in ack:
                self.status_callback("Error: Header not acknowledged")
                return
            
            self.status_callback(f"Sending {len(self.pages)} pages...")
            
            # Send pages
            pages_data = json.dumps(self.pages).encode('utf-8') + b"\n---END_PAGES---\n"
            
            # Send in chunks with progress
            total_size = len(pages_data)
            sent = 0
            
            while sent < total_size:
                chunk = pages_data[sent:sent + CHUNK_SIZE]
                sock.send(chunk)
                sent += len(chunk)
                progress = sent / total_size * 100
                self.status_callback(f"Sending... {progress:.1f}%")
            
            # Wait for confirmation
            response = sock.recv(1024).decode('utf-8')
            
            if response.startswith("OK:"):
                self.status_callback(f"SUCCESS: {response}")
                
                # Record shared pages
                page_ids = [p[:PAGE_ID_LENGTH] for p in self.pages]
                record_shared_pages(self.contact_id, page_ids, direction='sent')
                
                self.callback(True, len(self.pages))
            else:
                self.status_callback(f"Transfer failed: {response}")
                self.callback(False, 0)
                
        except Exception as e:
            self.status_callback(f"Send error: {e}")
            raise


# --- MAIN GUI ---

class OTPBluetoothShareApp:
    """Main application for Bluetooth OTP sharing."""
    
    def __init__(self, master):
        self.master = master
        self.master.title("OTP Bluetooth Share")
        self.master.geometry("700x650")
        self.master.minsize(650, 600)
        self.master.configure(bg='#0d1117')
        
        # State
        self.server = None
        self.client = None
        self.discovered_devices = []
        self.selected_device = None
        self.device_id = load_device_id()
        self.contacts = load_contacts()
        
        # Check Bluetooth availability
        if not BLUETOOTH_AVAILABLE:
            self.show_bluetooth_error()
            return
        
        self.setup_ui()
        self.update_otp_status()
    
    def show_bluetooth_error(self):
        """Show error when Bluetooth is not available."""
        frame = tk.Frame(self.master, bg='#0d1117')
        frame.place(relx=0.5, rely=0.5, anchor='center')
        
        tk.Label(
            frame,
            text="⚠️",
            font=("Helvetica", 48),
            fg='#f85149',
            bg='#0d1117'
        ).pack(pady=(0, 20))
        
        tk.Label(
            frame,
            text="Bluetooth Not Available",
            font=("Helvetica", 24, "bold"),
            fg='#c9d1d9',
            bg='#0d1117'
        ).pack(pady=(0, 20))
        
        instructions = (
            "Please install the required Bluetooth packages:\n\n"
            "1. System packages:\n"
            "   sudo apt-get install bluetooth bluez libbluetooth-dev\n\n"
            "2. Python package:\n"
            "   pip install pybluez\n\n"
            "3. Restart this application"
        )
        
        tk.Label(
            frame,
            text=instructions,
            font=("Consolas", 11),
            fg='#8b949e',
            bg='#0d1117',
            justify=tk.LEFT
        ).pack(pady=20)
    
    def setup_ui(self):
        """Build the user interface."""
        # Main container with padding
        main = tk.Frame(self.master, bg='#0d1117')
        main.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # --- Header ---
        header_frame = tk.Frame(main, bg='#0d1117')
        header_frame.pack(fill=tk.X, pady=(0, 20))
        
        tk.Label(
            header_frame,
            text="📡",
            font=("Helvetica", 32),
            fg='#58a6ff',
            bg='#0d1117'
        ).pack(side=tk.LEFT, padx=(0, 15))
        
        title_frame = tk.Frame(header_frame, bg='#0d1117')
        title_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        tk.Label(
            title_frame,
            text="OTP Bluetooth Share",
            font=("Helvetica", 22, "bold"),
            fg='#c9d1d9',
            bg='#0d1117',
            anchor='w'
        ).pack(fill=tk.X)
        
        tk.Label(
            title_frame,
            text="Secure key exchange for OTP communication",
            font=("Helvetica", 11),
            fg='#8b949e',
            bg='#0d1117',
            anchor='w'
        ).pack(fill=tk.X)
        
        # Device ID display
        if self.device_id:
            id_label = tk.Label(
                header_frame,
                text=f"My ID: {self.device_id}",
                font=("Consolas", 10),
                fg='#58a6ff',
                bg='#161b22',
                padx=10,
                pady=5
            )
            id_label.pack(side=tk.RIGHT)
        
        # --- OTP Status Bar ---
        self.otp_status_frame = tk.Frame(main, bg='#161b22')
        self.otp_status_frame.pack(fill=tk.X, pady=(0, 15))
        
        self.otp_status_label = tk.Label(
            self.otp_status_frame,
            text="Checking OTP pages...",
            font=("Consolas", 10),
            fg='#8b949e',
            bg='#161b22',
            padx=15,
            pady=8
        )
        self.otp_status_label.pack(fill=tk.X)
        
        # --- Notebook for Send/Receive tabs ---
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TNotebook', background='#0d1117', borderwidth=0)
        style.configure('TNotebook.Tab', background='#21262d', foreground='#c9d1d9',
                       padding=[20, 10], font=('Helvetica', 11))
        style.map('TNotebook.Tab', background=[('selected', '#30363d')],
                 foreground=[('selected', '#58a6ff')])
        
        self.notebook = ttk.Notebook(main)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        
        # --- SEND Tab ---
        send_frame = tk.Frame(self.notebook, bg='#0d1117')
        self.notebook.add(send_frame, text="📤 Send Pages")
        self.setup_send_tab(send_frame)
        
        # --- RECEIVE Tab ---
        receive_frame = tk.Frame(self.notebook, bg='#0d1117')
        self.notebook.add(receive_frame, text="📥 Receive Pages")
        self.setup_receive_tab(receive_frame)
        
        # --- Log Area ---
        log_frame = tk.Frame(main, bg='#161b22')
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(15, 0))
        
        tk.Label(
            log_frame,
            text="Activity Log",
            font=("Helvetica", 10, "bold"),
            fg='#8b949e',
            bg='#161b22',
            anchor='w',
            padx=10,
            pady=5
        ).pack(fill=tk.X)
        
        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            height=8,
            font=("Consolas", 9),
            bg='#0d1117',
            fg='#c9d1d9',
            insertbackground='#c9d1d9',
            relief='flat',
            padx=10,
            pady=10
        )
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.log_text.config(state=tk.DISABLED)
    
    def setup_send_tab(self, parent):
        """Setup the Send Pages tab."""
        container = tk.Frame(parent, bg='#0d1117', padx=15, pady=15)
        container.pack(fill=tk.BOTH, expand=True)
        
        # --- Step 1: Discover Devices ---
        step1 = tk.LabelFrame(
            container,
            text="Step 1: Find Nearby Device",
            font=("Helvetica", 11, "bold"),
            fg='#c9d1d9',
            bg='#0d1117',
            padx=15,
            pady=10
        )
        step1.pack(fill=tk.X, pady=(0, 15))
        
        btn_frame = tk.Frame(step1, bg='#0d1117')
        btn_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.scan_button = tk.Button(
            btn_frame,
            text="🔍 Scan for Devices",
            command=self.scan_devices,
            font=("Helvetica", 11),
            bg='#238636',
            fg='white',
            activebackground='#2ea043',
            activeforeground='white',
            relief='flat',
            padx=20,
            pady=8,
            cursor='hand2'
        )
        self.scan_button.pack(side=tk.LEFT)
        
        self.scan_status = tk.Label(
            btn_frame,
            text="",
            font=("Helvetica", 10),
            fg='#8b949e',
            bg='#0d1117'
        )
        self.scan_status.pack(side=tk.LEFT, padx=(15, 0))
        
        # Device list
        self.device_listbox = tk.Listbox(
            step1,
            height=4,
            font=("Consolas", 10),
            bg='#161b22',
            fg='#c9d1d9',
            selectbackground='#30363d',
            selectforeground='#58a6ff',
            relief='flat',
            highlightthickness=1,
            highlightcolor='#30363d',
            highlightbackground='#21262d'
        )
        self.device_listbox.pack(fill=tk.X)
        self.device_listbox.bind('<<ListboxSelect>>', self.on_device_select)
        
        # --- Step 2: Select Pages ---
        step2 = tk.LabelFrame(
            container,
            text="Step 2: Select Pages to Share",
            font=("Helvetica", 11, "bold"),
            fg='#c9d1d9',
            bg='#0d1117',
            padx=15,
            pady=10
        )
        step2.pack(fill=tk.X, pady=(0, 15))
        
        pages_row = tk.Frame(step2, bg='#0d1117')
        pages_row.pack(fill=tk.X)
        
        tk.Label(
            pages_row,
            text="Number of pages:",
            font=("Helvetica", 11),
            fg='#c9d1d9',
            bg='#0d1117'
        ).pack(side=tk.LEFT)
        
        self.pages_var = tk.StringVar(value="100")
        self.pages_entry = tk.Entry(
            pages_row,
            textvariable=self.pages_var,
            width=10,
            font=("Consolas", 11),
            bg='#161b22',
            fg='#c9d1d9',
            insertbackground='#c9d1d9',
            relief='flat'
        )
        self.pages_entry.pack(side=tk.LEFT, padx=(10, 20))
        
        self.available_label = tk.Label(
            pages_row,
            text="",
            font=("Helvetica", 10),
            fg='#8b949e',
            bg='#0d1117'
        )
        self.available_label.pack(side=tk.LEFT)
        
        # Contact association (optional)
        contact_row = tk.Frame(step2, bg='#0d1117')
        contact_row.pack(fill=tk.X, pady=(10, 0))
        
        tk.Label(
            contact_row,
            text="Associate with contact:",
            font=("Helvetica", 11),
            fg='#c9d1d9',
            bg='#0d1117'
        ).pack(side=tk.LEFT)
        
        self.contact_var = tk.StringVar()
        contact_names = ["(None)"] + [
            f"{c['nickname']} ({cid})" 
            for cid, c in self.contacts.items()
        ]
        
        self.contact_combo = ttk.Combobox(
            contact_row,
            textvariable=self.contact_var,
            values=contact_names,
            state='readonly',
            width=25
        )
        self.contact_combo.current(0)
        self.contact_combo.pack(side=tk.LEFT, padx=(10, 0))
        
        # --- Step 3: Send ---
        step3 = tk.Frame(container, bg='#0d1117')
        step3.pack(fill=tk.X)
        
        self.send_button = tk.Button(
            step3,
            text="📤 Send OTP Pages",
            command=self.send_pages,
            font=("Helvetica", 12, "bold"),
            bg='#238636',
            fg='white',
            activebackground='#2ea043',
            activeforeground='white',
            relief='flat',
            padx=30,
            pady=12,
            cursor='hand2',
            state=tk.DISABLED
        )
        self.send_button.pack(pady=10)
    
    def setup_receive_tab(self, parent):
        """Setup the Receive Pages tab."""
        container = tk.Frame(parent, bg='#0d1117', padx=15, pady=15)
        container.pack(fill=tk.BOTH, expand=True)
        
        # Instructions
        instructions = tk.Label(
            container,
            text=(
                "To receive OTP pages from another device:\n\n"
                "1. Make sure your Bluetooth is discoverable\n"
                "2. Click 'Start Receiving' below\n"
                "3. Have the sender select this device and send pages\n"
                "4. Pages will be automatically verified and saved"
            ),
            font=("Helvetica", 11),
            fg='#8b949e',
            bg='#0d1117',
            justify=tk.LEFT
        )
        instructions.pack(fill=tk.X, pady=(0, 20))
        
        # Receive button
        self.receive_button = tk.Button(
            container,
            text="📥 Start Receiving",
            command=self.start_receiving,
            font=("Helvetica", 14, "bold"),
            bg='#238636',
            fg='white',
            activebackground='#2ea043',
            activeforeground='white',
            relief='flat',
            padx=40,
            pady=15,
            cursor='hand2'
        )
        self.receive_button.pack(pady=20)
        
        # Stop button (hidden initially)
        self.stop_receive_button = tk.Button(
            container,
            text="⏹ Stop Receiving",
            command=self.stop_receiving,
            font=("Helvetica", 12),
            bg='#f85149',
            fg='white',
            activebackground='#da3633',
            activeforeground='white',
            relief='flat',
            padx=20,
            pady=10,
            cursor='hand2'
        )
        
        # Status
        self.receive_status = tk.Label(
            container,
            text="",
            font=("Helvetica", 11),
            fg='#8b949e',
            bg='#0d1117'
        )
        self.receive_status.pack(pady=10)
        
        # Bluetooth info
        info_frame = tk.Frame(container, bg='#161b22', padx=15, pady=15)
        info_frame.pack(fill=tk.X, pady=(20, 0))
        
        tk.Label(
            info_frame,
            text="ℹ️ To make Bluetooth discoverable:",
            font=("Helvetica", 10, "bold"),
            fg='#58a6ff',
            bg='#161b22'
        ).pack(anchor='w')
        
        tk.Label(
            info_frame,
            text="Run: sudo hciconfig hci0 piscan",
            font=("Consolas", 10),
            fg='#c9d1d9',
            bg='#161b22'
        ).pack(anchor='w', pady=(5, 0))
    
    def update_otp_status(self):
        """Update the OTP page count display."""
        available = get_available_pages(exclude_used=True, exclude_shared=False)
        
        if not available:
            self.otp_status_label.config(
                text="⚠️ No OTP pages available - Generate some first!",
                fg='#f85149'
            )
            self.send_button.config(state=tk.DISABLED)
        else:
            self.otp_status_label.config(
                text=f"✓ {len(available):,} OTP pages available for sharing",
                fg='#3fb950'
            )
            self.available_label.config(text=f"({len(available):,} available)")
    
    def log(self, message):
        """Add a message to the log."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        def update():
            self.log_text.config(state=tk.NORMAL)
            self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)
        
        self.master.after(0, update)
    
    def scan_devices(self):
        """Scan for nearby Bluetooth devices."""
        self.scan_button.config(state=tk.DISABLED)
        self.scan_status.config(text="Scanning...")
        self.device_listbox.delete(0, tk.END)
        self.discovered_devices = []
        self.log("Starting Bluetooth scan...")
        
        def do_scan():
            try:
                # Discover devices
                devices = bluetooth.discover_devices(
                    duration=8,
                    lookup_names=True,
                    lookup_class=True,
                    flush_cache=True
                )
                
                self.master.after(0, lambda: self.on_scan_complete(devices))
                
            except Exception as e:
                self.master.after(0, lambda: self.on_scan_error(str(e)))
        
        threading.Thread(target=do_scan, daemon=True).start()
    
    def on_scan_complete(self, devices):
        """Handle scan completion."""
        self.discovered_devices = devices
        self.scan_button.config(state=tk.NORMAL)
        
        if not devices:
            self.scan_status.config(text="No devices found")
            self.log("No Bluetooth devices found")
            return
        
        self.scan_status.config(text=f"Found {len(devices)} device(s)")
        self.log(f"Found {len(devices)} Bluetooth device(s)")
        
        for addr, name, device_class in devices:
            display_name = name if name else addr
            self.device_listbox.insert(tk.END, f"{display_name} [{addr}]")
    
    def on_scan_error(self, error):
        """Handle scan error."""
        self.scan_button.config(state=tk.NORMAL)
        self.scan_status.config(text="Scan failed")
        self.log(f"Scan error: {error}")
        messagebox.showerror("Scan Error", f"Failed to scan: {error}")
    
    def on_device_select(self, event):
        """Handle device selection from list."""
        selection = self.device_listbox.curselection()
        if selection:
            idx = selection[0]
            if idx < len(self.discovered_devices):
                self.selected_device = self.discovered_devices[idx]
                self.send_button.config(state=tk.NORMAL)
                self.log(f"Selected device: {self.selected_device[1] or self.selected_device[0]}")
    
    def send_pages(self):
        """Send OTP pages to selected device."""
        if not self.selected_device:
            messagebox.showwarning("Warning", "Please select a device first")
            return
        
        try:
            num_pages = int(self.pages_var.get())
            if num_pages <= 0:
                raise ValueError()
        except ValueError:
            messagebox.showwarning("Warning", "Please enter a valid number of pages")
            return
        
        # Get available pages
        available = get_available_pages(exclude_used=True, exclude_shared=False)
        
        if num_pages > len(available):
            messagebox.showwarning(
                "Warning",
                f"Only {len(available)} pages available. Adjust the number."
            )
            return
        
        # Get pages to send
        pages_to_send = [page for _, page in available[:num_pages]]
        
        # Get contact ID for recording
        contact_selection = self.contact_var.get()
        contact_id = "unknown"
        if contact_selection and contact_selection != "(None)":
            # Extract ID from "nickname (id)" format
            if "(" in contact_selection:
                contact_id = contact_selection.split("(")[-1].rstrip(")")
        
        target_addr = self.selected_device[0]
        target_name = self.selected_device[1] or target_addr
        
        self.log(f"Sending {num_pages} pages to {target_name}...")
        self.send_button.config(state=tk.DISABLED)
        
        # Start client thread
        self.client = BluetoothClient(
            target_addr,
            pages_to_send,
            contact_id,
            self.on_send_complete,
            self.log
        )
        self.client.start()
    
    def on_send_complete(self, success, count):
        """Handle send completion."""
        def update():
            self.send_button.config(state=tk.NORMAL)
            self.update_otp_status()
            
            if success:
                messagebox.showinfo(
                    "Success",
                    f"Successfully sent {count} OTP pages!\n\n"
                    "Both devices now share these pages for secure communication."
                )
        
        self.master.after(0, update)
    
    def start_receiving(self):
        """Start the Bluetooth server to receive pages."""
        self.receive_button.pack_forget()
        self.stop_receive_button.pack(pady=20)
        self.receive_status.config(text="Initializing Bluetooth server...")
        self.log("Starting Bluetooth receive server...")
        
        self.server = BluetoothServer(
            self.on_pages_received,
            self.on_receive_status
        )
        self.server.start()
    
    def stop_receiving(self):
        """Stop the Bluetooth server."""
        if self.server:
            self.server.stop()
            self.server = None
        
        self.stop_receive_button.pack_forget()
        self.receive_button.pack(pady=20)
        self.receive_status.config(text="Stopped")
        self.log("Stopped Bluetooth receive server")
    
    def on_receive_status(self, status):
        """Update receive status."""
        self.log(status)
        self.master.after(0, lambda: self.receive_status.config(text=status))
    
    def on_pages_received(self, pages, sender_id):
        """Handle received pages."""
        def update():
            self.update_otp_status()
            self.stop_receiving()
            
            messagebox.showinfo(
                "Success",
                f"Successfully received {len(pages)} OTP pages from {sender_id}!\n\n"
                "These pages have been added to your OTP file."
            )
        
        self.master.after(0, update)


# --- MAIN ---

def main():
    # Check if running on supported system
    if sys.platform == 'win32':
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "Unsupported Platform",
            "Bluetooth sharing is designed for Linux (Raspberry Pi / Ubuntu).\n\n"
            "Windows support requires different Bluetooth libraries."
        )
        return
    
    root = tk.Tk()
    
    # Set dark theme
    root.option_add('*TCombobox*Listbox.background', '#161b22')
    root.option_add('*TCombobox*Listbox.foreground', '#c9d1d9')
    
    app = OTPBluetoothShareApp(root)
    
    def on_close():
        if hasattr(app, 'server') and app.server:
            app.server.stop()
        if hasattr(app, 'client') and app.client:
            app.client.running = False
        root.destroy()
    
    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
