#!/usr/bin/env python3
"""
OTP Bluetooth Share - Per-Contact Cipher Pad Exchange
Share a contact-specific cipher pad via Bluetooth when meeting in person.

Key Concept:
    - Each contact has their own unique cipher.txt
    - When sharing, you send YOUR copy of the pad for a specific contact
    - When receiving, you specify which contact the pad is for
    - Both users end up with identical pads in their respective contact folders

Workflow:
    1. User A generates a pad for contact "bob" 
    2. User A meets Bob in person
    3. User A sends the pad to Bob via Bluetooth
    4. Bob receives and saves it as his pad for contact "alice"
    5. Now both have identical pads for communicating with each other

Requirements:
    sudo apt-get install bluetooth bluez libbluetooth-dev
    pip install pybluez
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import hashlib
import json
import os
import sys
from pathlib import Path
from datetime import datetime

try:
    import bluetooth
    BLUETOOTH_AVAILABLE = True
except ImportError:
    BLUETOOTH_AVAILABLE = False

# --- CONFIGURATION ---
APP_DIR = Path(__file__).parent.resolve()
OTP_DATA_DIR = APP_DIR / "otp_data"
CONTACTS_DIR = OTP_DATA_DIR / "contacts"
CONTACTS_FILE = APP_DIR / "contacts.json"
DEVICE_CONFIG_FILE = APP_DIR / "device_config.json"
TRANSFER_LOG_FILE = OTP_DATA_DIR / "bluetooth_transfers.json"

SERVICE_NAME = "OTP-KeyExchange"
SERVICE_UUID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
PAGE_ID_LENGTH = 8
CHUNK_SIZE = 4096


# --- HELPER FUNCTIONS ---

def ensure_directories():
    OTP_DATA_DIR.mkdir(exist_ok=True)
    CONTACTS_DIR.mkdir(exist_ok=True)


def load_device_id():
    if DEVICE_CONFIG_FILE.exists():
        try:
            with open(DEVICE_CONFIG_FILE, 'r') as f:
                return json.load(f).get('device_id')
        except:
            pass
    return None


def load_contacts():
    if CONTACTS_FILE.exists():
        try:
            with open(CONTACTS_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {}


def get_contact_name(contact_id, contacts):
    if contact_id in contacts:
        return contacts[contact_id].get('nickname', contact_id)
    return contact_id


def get_contacts_with_pads():
    if not CONTACTS_DIR.exists():
        return []
    
    contacts = []
    for item in CONTACTS_DIR.iterdir():
        if item.is_dir() and (item / "cipher.txt").exists():
            contacts.append(item.name)
    return sorted(contacts)


def get_pad_pages(contact_id):
    cipher_file = CONTACTS_DIR / contact_id / "cipher.txt"
    if not cipher_file.exists():
        return []
    
    with open(cipher_file, 'r', encoding='utf-8') as f:
        return [line.rstrip('\n') for line in f if len(line.strip()) > PAGE_ID_LENGTH]


def get_pad_page_count(contact_id):
    return len(get_pad_pages(contact_id))


def save_pad_for_contact(contact_id, pages, source="bluetooth"):
    ensure_directories()
    contact_dir = CONTACTS_DIR / contact_id
    contact_dir.mkdir(exist_ok=True)
    
    cipher_file = contact_dir / "cipher.txt"
    with open(cipher_file, 'w', encoding='utf-8') as f:
        for page in pages:
            f.write(page + '\n')
    
    used_file = contact_dir / "used.txt"
    with open(used_file, 'w') as f:
        pass
    
    metadata = {
        'created': datetime.now().isoformat(),
        'num_pages': len(pages),
        'source': source
    }
    with open(contact_dir / "metadata.json", 'w') as f:
        json.dump(metadata, f, indent=2)
    
    return len(pages)


def record_transfer(direction, contact_id, device_addr, num_pages):
    ensure_directories()
    log = {'sent': [], 'received': []}
    if TRANSFER_LOG_FILE.exists():
        try:
            with open(TRANSFER_LOG_FILE, 'r') as f:
                log = json.load(f)
        except:
            pass
    
    log[direction].append({
        'timestamp': datetime.now().isoformat(),
        'contact_id': contact_id,
        'device_address': device_addr,
        'num_pages': num_pages
    })
    
    with open(TRANSFER_LOG_FILE, 'w') as f:
        json.dump(log, f, indent=2)


def calculate_pages_hash(pages):
    hasher = hashlib.sha256()
    for page in sorted(pages):
        hasher.update(page.encode('utf-8'))
    return hasher.hexdigest()


# --- BLUETOOTH SERVER ---

class BluetoothServer(threading.Thread):
    def __init__(self, target_contact_id, callback, status_callback):
        super().__init__(daemon=True)
        self.target_contact_id = target_contact_id
        self.callback = callback
        self.status_callback = status_callback
        self.running = False
        self.server_socket = None
    
    def run(self):
        self.running = True
        
        try:
            self.server_socket = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
            self.server_socket.bind(("", bluetooth.PORT_ANY))
            self.server_socket.listen(1)
            
            port = self.server_socket.getsockname()[1]
            
            bluetooth.advertise_service(
                self.server_socket, SERVICE_NAME, service_id=SERVICE_UUID,
                service_classes=[SERVICE_UUID, bluetooth.SERIAL_PORT_CLASS],
                profiles=[bluetooth.SERIAL_PORT_PROFILE]
            )
            
            self.status_callback(f"Waiting on channel {port}...")
            self.status_callback("Run: bt-discoverable")
            
            self.server_socket.settimeout(300)
            client_socket, client_info = self.server_socket.accept()
            
            self.status_callback(f"Connected: {client_info[0]}")
            self.receive_pad(client_socket, client_info)
            client_socket.close()
            
        except bluetooth.BluetoothError as e:
            self.status_callback(f"BT error: {e}")
        except TimeoutError:
            self.status_callback("Timeout (5 min)")
        except Exception as e:
            self.status_callback(f"Error: {e}")
        finally:
            self.stop()
    
    def receive_pad(self, sock, client_info):
        try:
            header_data = b""
            while b"\n---END_HEADER---\n" not in header_data:
                chunk = sock.recv(1024)
                if not chunk:
                    break
                header_data += chunk
            
            header_json, _ = header_data.split(b"\n---END_HEADER---\n", 1)
            header = json.loads(header_json.decode('utf-8'))
            
            sender_id = header.get('sender_id', 'unknown')
            num_pages = header.get('num_pages', 0)
            expected_hash = header.get('hash')
            
            self.status_callback(f"Receiving {num_pages} pages...")
            sock.send(b"ACK_HEADER\n")
            
            pages_data = b""
            while b"\n---END_PAGES---\n" not in pages_data:
                chunk = sock.recv(CHUNK_SIZE)
                if not chunk:
                    break
                pages_data += chunk
                progress = min(len(pages_data) / (num_pages * 3500) * 100, 100)
                self.status_callback(f"Receiving... {progress:.1f}%")
            
            pages_json, _ = pages_data.split(b"\n---END_PAGES---\n", 1)
            pages = json.loads(pages_json.decode('utf-8'))
            
            if calculate_pages_hash(pages) != expected_hash:
                sock.send(b"ERROR: Hash mismatch!\n")
                self.status_callback("ERROR: Verification failed!")
                return
            
            sock.send(f"OK: {len(pages)} pages\n".encode('utf-8'))
            
            self.status_callback(f"Saving for {self.target_contact_id}...")
            saved = save_pad_for_contact(self.target_contact_id, pages)
            record_transfer('received', self.target_contact_id, client_info[0], saved)
            
            self.status_callback(f"SUCCESS: {saved} pages saved")
            self.callback(True, saved, sender_id)
            
        except Exception as e:
            self.status_callback(f"Error: {e}")
            self.callback(False, 0, None)
    
    def stop(self):
        self.running = False
        if self.server_socket:
            try:
                bluetooth.stop_advertising(self.server_socket)
                self.server_socket.close()
            except:
                pass
            self.server_socket = None


# --- BLUETOOTH CLIENT ---

class BluetoothClient(threading.Thread):
    def __init__(self, target_addr, target_name, contact_id, pages, callback, status_callback):
        super().__init__(daemon=True)
        self.target_addr = target_addr
        self.target_name = target_name
        self.contact_id = contact_id
        self.pages = pages
        self.callback = callback
        self.status_callback = status_callback
    
    def run(self):
        sock = None
        try:
            self.status_callback(f"Connecting to {self.target_name}...")
            
            services = bluetooth.find_service(uuid=SERVICE_UUID, address=self.target_addr)
            port = services[0]["port"] if services else 1
            
            sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
            sock.connect((self.target_addr, port))
            
            self.status_callback("Connected!")
            self.send_pad(sock)
            
        except Exception as e:
            self.status_callback(f"Error: {e}")
            self.callback(False, 0)
        finally:
            if sock:
                sock.close()
    
    def send_pad(self, sock):
        try:
            device_id = load_device_id() or "unknown"
            
            header = {
                'sender_id': device_id,
                'for_contact': self.contact_id,
                'num_pages': len(self.pages),
                'hash': calculate_pages_hash(self.pages),
                'timestamp': datetime.now().isoformat()
            }
            
            sock.send(json.dumps(header).encode('utf-8') + b"\n---END_HEADER---\n")
            
            if b"ACK_HEADER" not in sock.recv(1024):
                self.status_callback("Not acknowledged")
                return
            
            self.status_callback(f"Sending {len(self.pages)} pages...")
            
            pages_data = json.dumps(self.pages).encode('utf-8') + b"\n---END_PAGES---\n"
            total = len(pages_data)
            sent = 0
            
            while sent < total:
                chunk = pages_data[sent:sent + CHUNK_SIZE]
                sock.send(chunk)
                sent += len(chunk)
                self.status_callback(f"Sending... {sent/total*100:.1f}%")
            
            response = sock.recv(1024).decode('utf-8')
            
            if response.startswith("OK:"):
                record_transfer('sent', self.contact_id, self.target_addr, len(self.pages))
                self.status_callback(f"SUCCESS!")
                self.callback(True, len(self.pages))
            else:
                self.status_callback(f"Failed: {response}")
                self.callback(False, 0)
                
        except Exception as e:
            self.status_callback(f"Error: {e}")
            self.callback(False, 0)


# --- GUI ---

class OTPBluetoothShareApp:
    def __init__(self, master):
        self.master = master
        self.master.title("OTP Bluetooth Share")
        self.master.geometry("750x700")
        self.master.minsize(700, 650)
        self.master.configure(bg='#0d1117')
        
        self.server = None
        self.discovered_devices = []
        self.selected_device = None
        self.device_id = load_device_id()
        self.contacts = load_contacts()
        
        ensure_directories()
        
        if not BLUETOOTH_AVAILABLE:
            self.show_bt_error()
            return
        
        self.setup_ui()
    
    def show_bt_error(self):
        frame = tk.Frame(self.master, bg='#0d1117')
        frame.place(relx=0.5, rely=0.5, anchor='center')
        tk.Label(frame, text="⚠️ Bluetooth Not Available", font=("Helvetica", 20, "bold"),
                fg='#f85149', bg='#0d1117').pack(pady=20)
        tk.Label(frame, text="sudo apt install bluetooth bluez libbluetooth-dev\npip install pybluez",
                font=("Consolas", 11), fg='#8b949e', bg='#0d1117').pack()
    
    def setup_ui(self):
        main = tk.Frame(self.master, bg='#0d1117')
        main.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # Header
        tk.Label(main, text="📡 Bluetooth Pad Share", font=("Helvetica", 22, "bold"),
                fg='#c9d1d9', bg='#0d1117').pack(anchor='w')
        tk.Label(main, text="Share per-contact cipher pads via Bluetooth",
                font=("Helvetica", 11), fg='#8b949e', bg='#0d1117').pack(anchor='w', pady=(0, 15))
        
        # Tabs
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TNotebook', background='#0d1117')
        style.configure('TNotebook.Tab', background='#21262d', foreground='#c9d1d9', padding=[20, 10])
        style.map('TNotebook.Tab', background=[('selected', '#30363d')])
        
        notebook = ttk.Notebook(main)
        notebook.pack(fill=tk.BOTH, expand=True)
        
        send_frame = tk.Frame(notebook, bg='#0d1117')
        notebook.add(send_frame, text="📤 Send Pad")
        self.setup_send_tab(send_frame)
        
        recv_frame = tk.Frame(notebook, bg='#0d1117')
        notebook.add(recv_frame, text="📥 Receive Pad")
        self.setup_recv_tab(recv_frame)
        
        # Log
        log_frame = tk.Frame(main, bg='#161b22')
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(15, 0))
        tk.Label(log_frame, text="Log", font=("Helvetica", 10, "bold"),
                fg='#8b949e', bg='#161b22', padx=10, pady=5).pack(anchor='w')
        self.log_text = scrolledtext.ScrolledText(log_frame, height=5, font=("Consolas", 9),
            bg='#0d1117', fg='#c9d1d9', relief='flat')
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.log_text.config(state=tk.DISABLED)
    
    def setup_send_tab(self, parent):
        c = tk.Frame(parent, bg='#0d1117', padx=15, pady=15)
        c.pack(fill=tk.BOTH, expand=True)
        
        # Contact selection
        tk.Label(c, text="1. Select contact's pad to send:", font=("Helvetica", 11, "bold"),
                fg='#c9d1d9', bg='#0d1117').pack(anchor='w', pady=(0, 5))
        
        contacts_with_pads = get_contacts_with_pads()
        self.send_contact_var = tk.StringVar()
        
        if contacts_with_pads:
            options = [f"{get_contact_name(cid, self.contacts)} ({cid}) - {get_pad_page_count(cid)} pages"
                      for cid in contacts_with_pads]
            self.send_combo = ttk.Combobox(c, textvariable=self.send_contact_var,
                values=options, state='readonly', width=50)
            self.send_combo.current(0)
            self.send_combo.pack(anchor='w', pady=(0, 15))
        else:
            tk.Label(c, text="No pads yet. Generate in OTP Manager first.",
                    fg='#f85149', bg='#0d1117').pack(anchor='w', pady=(0, 15))
        
        # Device scan
        tk.Label(c, text="2. Find recipient device:", font=("Helvetica", 11, "bold"),
                fg='#c9d1d9', bg='#0d1117').pack(anchor='w', pady=(0, 5))
        
        btn_row = tk.Frame(c, bg='#0d1117')
        btn_row.pack(anchor='w', pady=(0, 5))
        
        self.scan_btn = tk.Button(btn_row, text="🔍 Scan", command=self.scan,
            font=("Helvetica", 10), bg='#238636', fg='white', relief='flat', padx=15, pady=5)
        self.scan_btn.pack(side=tk.LEFT)
        
        self.scan_status = tk.Label(btn_row, text="", fg='#8b949e', bg='#0d1117')
        self.scan_status.pack(side=tk.LEFT, padx=10)
        
        self.device_list = tk.Listbox(c, height=4, font=("Consolas", 10),
            bg='#161b22', fg='#c9d1d9', selectbackground='#1f6feb', relief='flat')
        self.device_list.pack(fill=tk.X, pady=(0, 15))
        self.device_list.bind('<<ListboxSelect>>', self.on_device_sel)
        
        # Send button
        self.send_btn = tk.Button(c, text="📤 Send Cipher Pad", command=self.send_pad,
            font=("Helvetica", 12, "bold"), bg='#238636', fg='white', relief='flat',
            padx=30, pady=10, state=tk.DISABLED)
        self.send_btn.pack(pady=10)
    
    def setup_recv_tab(self, parent):
        c = tk.Frame(parent, bg='#0d1117', padx=15, pady=15)
        c.pack(fill=tk.BOTH, expand=True)
        
        tk.Label(c, text="1. Who is sending you this pad?", font=("Helvetica", 11, "bold"),
                fg='#c9d1d9', bg='#0d1117').pack(anchor='w', pady=(0, 5))
        
        self.recv_contact_var = tk.StringVar()
        options = [f"{get_contact_name(cid, self.contacts)} ({cid})" for cid in self.contacts.keys()]
        
        if options:
            self.recv_combo = ttk.Combobox(c, textvariable=self.recv_contact_var,
                values=options, state='readonly', width=50)
            self.recv_combo.current(0)
            self.recv_combo.pack(anchor='w', pady=(0, 15))
        else:
            tk.Label(c, text="No contacts. Add in Contacts app first.",
                    fg='#f85149', bg='#0d1117').pack(anchor='w', pady=(0, 15))
            self.recv_combo = None
        
        tk.Label(c, text="2. Start receiving:", font=("Helvetica", 11, "bold"),
                fg='#c9d1d9', bg='#0d1117').pack(anchor='w', pady=(0, 5))
        
        self.recv_btn = tk.Button(c, text="📥 Start Receiving", command=self.start_recv,
            font=("Helvetica", 12, "bold"), bg='#238636', fg='white', relief='flat', padx=30, pady=10)
        self.recv_btn.pack(pady=5)
        
        self.stop_btn = tk.Button(c, text="⏹ Stop", command=self.stop_recv,
            font=("Helvetica", 10), bg='#f85149', fg='white', relief='flat', padx=20, pady=5)
        
        self.recv_status = tk.Label(c, text="", fg='#8b949e', bg='#0d1117')
        self.recv_status.pack(pady=10)
        
        tk.Label(c, text="Make discoverable: bt-discoverable", font=("Consolas", 10),
                fg='#58a6ff', bg='#0d1117').pack(pady=10)
    
    def log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        def update():
            self.log_text.config(state=tk.NORMAL)
            self.log_text.insert(tk.END, f"[{ts}] {msg}\n")
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)
        self.master.after(0, update)
    
    def scan(self):
        self.scan_btn.config(state=tk.DISABLED)
        self.scan_status.config(text="Scanning...")
        self.device_list.delete(0, tk.END)
        self.discovered_devices = []
        self.log("Scanning...")
        
        def do_scan():
            try:
                devices = bluetooth.discover_devices(duration=8, lookup_names=True)
                self.master.after(0, lambda: self.on_scan_done(devices))
            except Exception as e:
                self.master.after(0, lambda: self.scan_status.config(text=f"Error: {e}"))
                self.master.after(0, lambda: self.scan_btn.config(state=tk.NORMAL))
        
        threading.Thread(target=do_scan, daemon=True).start()
    
    def on_scan_done(self, devices):
        self.discovered_devices = [(addr, name, None) for addr, name in devices]
        self.scan_btn.config(state=tk.NORMAL)
        self.scan_status.config(text=f"Found {len(devices)}")
        self.log(f"Found {len(devices)} devices")
        
        for addr, name in devices:
            self.device_list.insert(tk.END, f"{name or addr} [{addr}]")
    
    def on_device_sel(self, event):
        sel = self.device_list.curselection()
        if sel and sel[0] < len(self.discovered_devices):
            self.selected_device = self.discovered_devices[sel[0]]
            self.send_btn.config(state=tk.NORMAL)
    
    def send_pad(self):
        if not self.selected_device or not self.send_contact_var.get():
            return
        
        contact_id = self.send_contact_var.get().split('(')[1].split(')')[0]
        pages = get_pad_pages(contact_id)
        
        if not pages:
            messagebox.showerror("Error", "No pages")
            return
        
        self.log(f"Sending {len(pages)} pages...")
        self.send_btn.config(state=tk.DISABLED)
        
        client = BluetoothClient(
            self.selected_device[0],
            self.selected_device[1] or self.selected_device[0],
            contact_id, pages,
            lambda ok, n: self.master.after(0, lambda: self.on_send_done(ok, n)),
            self.log
        )
        client.start()
    
    def on_send_done(self, ok, count):
        self.send_btn.config(state=tk.NORMAL)
        if ok:
            messagebox.showinfo("Success", f"Sent {count} pages!")
    
    def start_recv(self):
        if not self.recv_combo:
            return
        
        contact_id = self.recv_contact_var.get().split('(')[-1].rstrip(')')
        
        self.recv_btn.pack_forget()
        self.stop_btn.pack(pady=5)
        self.recv_status.config(text="Waiting...")
        self.log(f"Waiting for pad for {contact_id}...")
        
        self.server = BluetoothServer(
            contact_id,
            lambda ok, n, s: self.master.after(0, lambda: self.on_recv_done(ok, n)),
            self.log
        )
        self.server.start()
    
    def stop_recv(self):
        if self.server:
            self.server.stop()
            self.server = None
        self.stop_btn.pack_forget()
        self.recv_btn.pack(pady=5)
        self.recv_status.config(text="Stopped")
    
    def on_recv_done(self, ok, count):
        self.stop_recv()
        if ok:
            messagebox.showinfo("Success", f"Received {count} pages!")


def main():
    if sys.platform == 'win32':
        messagebox.showerror("Error", "Linux only")
        return
    
    root = tk.Tk()
    app = OTPBluetoothShareApp(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (app.server.stop() if app.server else None, root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
