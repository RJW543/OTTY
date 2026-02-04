#!/usr/bin/env python3
"""
OTP Voice Client - AES Encrypted Voice Calls
Supports one-on-one and group voice calls via the OTP Relay Server.

Features:
- AES-256-GCM encryption for voice data
- Push-to-talk and continuous modes
- Group call rooms with multiple participants
- Visual audio level indicator
- Mute/unmute controls

Requirements:
    pip install pyaudio cryptography

Usage:
    python3 otp_voice_client.py
"""

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import socket
import threading
import struct
import time
import os
import hashlib
import base64
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# Audio handling
try:
    import pyaudio
    AUDIO_AVAILABLE = True
except ImportError:
    AUDIO_AVAILABLE = False
    print("Warning: PyAudio not installed. Install with: pip install pyaudio")

# Encryption
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    print("Warning: cryptography not installed. Install with: pip install cryptography")


# --- CONFIGURATION ---
CREDENTIALS_FILE = "credentials.txt"

# Audio settings
CHUNK_SIZE = 1024          # Samples per frame
FORMAT = pyaudio.paInt16 if AUDIO_AVAILABLE else None
CHANNELS = 1               # Mono audio
RATE = 16000               # 16kHz sample rate (good for voice)
AUDIO_PACKET_INTERVAL = 0.05  # 50ms packets

# Protocol identifiers
PROTO_VOICE = "VOICE"
PROTO_ROOM = "ROOM"
PROTO_SIGNAL = "SIGNAL"

# Room commands
CMD_CREATE = "CREATE"
CMD_JOIN = "JOIN"
CMD_LEAVE = "LEAVE"
CMD_LIST = "LIST"
CMD_INVITE = "INVITE"
CMD_KICK = "KICK"


# --- ENCRYPTION ---

class AESCipher:
    """
    AES-256-GCM encryption for voice data.
    Provides authenticated encryption with associated data.
    """
    
    def __init__(self, password: str, salt: bytes = None):
        """
        Initialize cipher with a password-derived key.
        
        Args:
            password: Shared secret for the call/room
            salt: Optional salt (generated if not provided)
        """
        self.salt = salt or os.urandom(16)
        
        # Derive a 256-bit key using PBKDF2
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=self.salt,
            iterations=100000,  # Balance security and speed
        )
        self.key = kdf.derive(password.encode('utf-8'))
        self.aesgcm = AESGCM(self.key)
    
    def encrypt(self, plaintext: bytes, associated_data: bytes = None) -> bytes:
        """
        Encrypt data with AES-256-GCM.
        
        Returns: nonce (12 bytes) + ciphertext + tag
        """
        nonce = os.urandom(12)
        ciphertext = self.aesgcm.encrypt(nonce, plaintext, associated_data)
        return nonce + ciphertext
    
    def decrypt(self, encrypted: bytes, associated_data: bytes = None) -> bytes:
        """
        Decrypt AES-256-GCM encrypted data.
        
        Args:
            encrypted: nonce (12 bytes) + ciphertext + tag
        
        Returns: Decrypted plaintext
        """
        nonce = encrypted[:12]
        ciphertext = encrypted[12:]
        return self.aesgcm.decrypt(nonce, ciphertext, associated_data)
    
    def get_salt_b64(self) -> str:
        """Get salt as base64 string for sharing."""
        return base64.b64encode(self.salt).decode('utf-8')
    
    @classmethod
    def from_salt_b64(cls, password: str, salt_b64: str) -> 'AESCipher':
        """Create cipher from password and base64 salt."""
        salt = base64.b64decode(salt_b64)
        return cls(password, salt)


# --- AUDIO HANDLER ---

class AudioHandler:
    """Handles audio capture and playback."""
    
    def __init__(self):
        self.pyaudio = None
        self.input_stream = None
        self.output_stream = None
        self.is_recording = False
        self.is_playing = False
        self.audio_level = 0
        
        # Playback buffer for mixing multiple streams
        self.playback_buffers = defaultdict(list)
        self.playback_lock = threading.Lock()
        
        if AUDIO_AVAILABLE:
            self.pyaudio = pyaudio.PyAudio()
    
    def start_input(self, callback):
        """Start audio capture."""
        if not self.pyaudio:
            return False
        
        try:
            self.input_stream = self.pyaudio.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=RATE,
                input=True,
                frames_per_buffer=CHUNK_SIZE,
                stream_callback=callback
            )
            self.is_recording = True
            return True
        except Exception as e:
            print(f"Failed to start audio input: {e}")
            return False
    
    def start_output(self):
        """Start audio playback."""
        if not self.pyaudio:
            return False
        
        try:
            self.output_stream = self.pyaudio.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=RATE,
                output=True,
                frames_per_buffer=CHUNK_SIZE
            )
            self.is_playing = True
            return True
        except Exception as e:
            print(f"Failed to start audio output: {e}")
            return False
    
    def play_audio(self, audio_data: bytes, source_id: str = "default"):
        """Queue audio data for playback."""
        if self.output_stream and self.is_playing:
            try:
                self.output_stream.write(audio_data)
            except Exception as e:
                print(f"Playback error: {e}")
    
    def stop(self):
        """Stop all audio streams."""
        self.is_recording = False
        self.is_playing = False
        
        if self.input_stream:
            try:
                self.input_stream.stop_stream()
                self.input_stream.close()
            except:
                pass
            self.input_stream = None
        
        if self.output_stream:
            try:
                self.output_stream.stop_stream()
                self.output_stream.close()
            except:
                pass
            self.output_stream = None
    
    def cleanup(self):
        """Clean up PyAudio resources."""
        self.stop()
        if self.pyaudio:
            self.pyaudio.terminate()
            self.pyaudio = None
    
    def calculate_level(self, audio_data: bytes) -> float:
        """Calculate audio level (0-100) from raw audio data."""
        if len(audio_data) < 2:
            return 0
        
        # Convert bytes to samples
        samples = struct.unpack(f'{len(audio_data)//2}h', audio_data)
        
        # Calculate RMS
        if samples:
            rms = (sum(s * s for s in samples) / len(samples)) ** 0.5
            # Normalize to 0-100 (32768 is max for 16-bit audio)
            level = min(100, (rms / 32768) * 200)
            return level
        return 0


# --- VOICE ROOM ---

class VoiceRoom:
    """Represents a voice call room (1-on-1 or group)."""
    
    def __init__(self, room_id: str, password: str, is_creator: bool = False):
        self.room_id = room_id
        self.password = password
        self.is_creator = is_creator
        self.participants = set()
        self.cipher = None
        self.salt = None
        
        if CRYPTO_AVAILABLE:
            self.cipher = AESCipher(password)
            self.salt = self.cipher.get_salt_b64()
    
    def set_salt(self, salt_b64: str):
        """Set salt received from room creator."""
        if CRYPTO_AVAILABLE:
            self.cipher = AESCipher.from_salt_b64(self.password, salt_b64)
            self.salt = salt_b64
    
    def encrypt_audio(self, audio_data: bytes) -> bytes:
        """Encrypt audio data for transmission."""
        if self.cipher:
            return self.cipher.encrypt(audio_data)
        return audio_data
    
    def decrypt_audio(self, encrypted_data: bytes) -> bytes:
        """Decrypt received audio data."""
        if self.cipher:
            try:
                return self.cipher.decrypt(encrypted_data)
            except Exception as e:
                print(f"Decryption error: {e}")
                return b''
        return encrypted_data
    
    def add_participant(self, user_id: str):
        """Add a participant to the room."""
        self.participants.add(user_id)
    
    def remove_participant(self, user_id: str):
        """Remove a participant from the room."""
        self.participants.discard(user_id)


# --- USERNAME LOADING ---

def load_username_from_credentials(file_name=CREDENTIALS_FILE):
    """Load the most recent username from credentials.txt."""
    file_path = Path(file_name)
    if not file_path.exists():
        return None
    
    username = None
    with file_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("Username:"):
                username = line.replace("Username:", "").strip()
    
    return username


# --- VOICE CLIENT GUI ---

class VoiceClientGUI:
    """Main GUI for the OTP Voice Client."""
    
    def __init__(self, master):
        self.master = master
        self.master.title("OTP Voice - Encrypted Calls")
        self.master.geometry("500x600")
        self.master.minsize(450, 550)
        
        # Network state
        self.client_socket = None
        self.user_id = None
        self.connected = False
        
        # Voice state
        self.current_room = None
        self.audio_handler = AudioHandler() if AUDIO_AVAILABLE else None
        self.is_transmitting = False
        self.push_to_talk = True
        self.is_muted = False
        
        # Threads
        self.receive_thread = None
        self.audio_thread = None
        
        self.setup_ui()
        self.check_prerequisites()
    
    def setup_ui(self):
        """Build the user interface."""
        style = ttk.Style()
        style.theme_use('clam')
        
        main_frame = ttk.Frame(self.master, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # --- Connection Section ---
        conn_frame = ttk.LabelFrame(main_frame, text="Connection", padding="10")
        conn_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Server row
        server_row = ttk.Frame(conn_frame)
        server_row.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(server_row, text="Server:").pack(side=tk.LEFT)
        self.host_entry = ttk.Entry(server_row, width=22)
        self.host_entry.insert(0, "0.tcp.ngrok.io")
        self.host_entry.pack(side=tk.LEFT, padx=(5, 10))
        
        ttk.Label(server_row, text="Port:").pack(side=tk.LEFT)
        self.port_entry = ttk.Entry(server_row, width=7)
        self.port_entry.insert(0, "12345")
        self.port_entry.pack(side=tk.LEFT, padx=(5, 0))
        
        # Username row
        user_row = ttk.Frame(conn_frame)
        user_row.pack(fill=tk.X, pady=(5, 0))
        
        ttk.Label(user_row, text="Username:").pack(side=tk.LEFT)
        self.username_entry = ttk.Entry(user_row, width=15)
        self.username_entry.pack(side=tk.LEFT, padx=(5, 10))
        
        # Load saved username
        saved_username = load_username_from_credentials()
        if saved_username:
            self.username_entry.insert(0, saved_username)
        
        self.connect_button = ttk.Button(user_row, text="Connect", command=self.connect_to_server)
        self.connect_button.pack(side=tk.LEFT, padx=(5, 0))
        
        self.disconnect_button = ttk.Button(user_row, text="Disconnect", command=self.disconnect, state=tk.DISABLED)
        self.disconnect_button.pack(side=tk.LEFT, padx=(5, 0))
        
        # Status
        self.status_label = ttk.Label(conn_frame, text="* Disconnected", foreground="red")
        self.status_label.pack(anchor=tk.W, pady=(5, 0))
        
        # --- Room Section ---
        room_frame = ttk.LabelFrame(main_frame, text="Voice Room", padding="10")
        room_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Room controls row 1
        room_row1 = ttk.Frame(room_frame)
        room_row1.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(room_row1, text="Room ID:").pack(side=tk.LEFT)
        self.room_entry = ttk.Entry(room_row1, width=15)
        self.room_entry.pack(side=tk.LEFT, padx=(5, 10))
        
        ttk.Label(room_row1, text="Password:").pack(side=tk.LEFT)
        self.room_pass_entry = ttk.Entry(room_row1, width=15, show="-")
        self.room_pass_entry.pack(side=tk.LEFT, padx=(5, 0))
        
        # Room controls row 2
        room_row2 = ttk.Frame(room_frame)
        room_row2.pack(fill=tk.X, pady=(5, 0))
        
        self.create_room_btn = ttk.Button(room_row2, text="Create Room", command=self.create_room, state=tk.DISABLED)
        self.create_room_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        self.join_room_btn = ttk.Button(room_row2, text="Join Room", command=self.join_room, state=tk.DISABLED)
        self.join_room_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        self.leave_room_btn = ttk.Button(room_row2, text="Leave Room", command=self.leave_room, state=tk.DISABLED)
        self.leave_room_btn.pack(side=tk.LEFT)
        
        # Room status
        self.room_status = ttk.Label(room_frame, text="Not in a room", foreground="gray")
        self.room_status.pack(anchor=tk.W, pady=(5, 0))
        
        # --- Participants Section ---
        participants_frame = ttk.LabelFrame(main_frame, text="Participants", padding="10")
        participants_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        self.participants_list = tk.Listbox(participants_frame, height=6, font=("Consolas", 10))
        self.participants_list.pack(fill=tk.BOTH, expand=True)
        
        # Invite row
        invite_row = ttk.Frame(participants_frame)
        invite_row.pack(fill=tk.X, pady=(5, 0))
        
        ttk.Label(invite_row, text="Invite:").pack(side=tk.LEFT)
        self.invite_entry = ttk.Entry(invite_row, width=15)
        self.invite_entry.pack(side=tk.LEFT, padx=(5, 5))
        
        # Check for pre-filled recipient from Contacts app
        recipient_from_env = os.environ.get('OTP_RECIPIENT')
        recipient_name = os.environ.get('OTP_RECIPIENT_NAME')
        if recipient_from_env:
            self.invite_entry.insert(0, recipient_from_env)
            # Also suggest a room name based on the call
            if not self.room_entry.get():
                self.room_entry.insert(0, f"call_{recipient_from_env[:6]}")
        
        self.invite_btn = ttk.Button(invite_row, text="Send Invite", command=self.invite_user, state=tk.DISABLED)
        self.invite_btn.pack(side=tk.LEFT)
        
        # Show contact name if launching from contacts
        if recipient_from_env and recipient_name and recipient_name != recipient_from_env:
            self.calling_label = ttk.Label(
                participants_frame,
                text=f"[T] Calling: {recipient_name}",
                foreground='#8957e5',
                font=("Helvetica", 10, "bold")
            )
            self.calling_label.pack(pady=(5, 0))
        
        # --- Audio Controls Section ---
        audio_frame = ttk.LabelFrame(main_frame, text="Audio Controls", padding="10")
        audio_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Audio level meter
        level_row = ttk.Frame(audio_frame)
        level_row.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(level_row, text="Audio Level:").pack(side=tk.LEFT)
        self.level_canvas = tk.Canvas(level_row, width=200, height=20, bg='#2d2d2d', highlightthickness=0)
        self.level_canvas.pack(side=tk.LEFT, padx=(10, 0))
        self.level_bar = self.level_canvas.create_rectangle(0, 0, 0, 20, fill='#00ff00')
        
        # Control buttons
        controls_row = ttk.Frame(audio_frame)
        controls_row.pack(fill=tk.X)
        
        # Push-to-talk button (larger)
        self.ptt_button = tk.Button(
            controls_row,
            text="[V] PUSH TO TALK",
            font=("Helvetica", 12, "bold"),
            bg='#333333',
            fg='white',
            activebackground='#00aa00',
            activeforeground='white',
            width=18,
            height=2,
            state=tk.DISABLED
        )
        self.ptt_button.pack(side=tk.LEFT, padx=(0, 10))
        self.ptt_button.bind('<ButtonPress-1>', self.start_transmit)
        self.ptt_button.bind('<ButtonRelease-1>', self.stop_transmit)
        
        # Mute toggle
        self.mute_var = tk.BooleanVar(value=False)
        self.mute_check = ttk.Checkbutton(
            controls_row,
            text="Mute Mic",
            variable=self.mute_var,
            command=self.toggle_mute
        )
        self.mute_check.pack(side=tk.LEFT, padx=(0, 10))
        
        # PTT mode toggle
        self.ptt_var = tk.BooleanVar(value=True)
        self.ptt_check = ttk.Checkbutton(
            controls_row,
            text="Push-to-Talk",
            variable=self.ptt_var,
            command=self.toggle_ptt_mode
        )
        self.ptt_check.pack(side=tk.LEFT)
        
        # --- Log Section ---
        log_frame = ttk.LabelFrame(main_frame, text="Activity Log", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        self.log_text = tk.Text(log_frame, height=6, state=tk.DISABLED, font=("Consolas", 9))
        log_scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Bind keyboard shortcut for PTT
        self.master.bind('<space>', self.handle_space_press)
        self.master.bind('<KeyRelease-space>', self.handle_space_release)
    
    def check_prerequisites(self):
        """Check if required modules are available."""
        missing = []
        if not AUDIO_AVAILABLE:
            missing.append("pyaudio")
        if not CRYPTO_AVAILABLE:
            missing.append("cryptography")
        
        if missing:
            self.log_message(f"!  Missing: {', '.join(missing)}")
            self.log_message("Install with: pip install " + " ".join(missing))
    
    def log_message(self, message):
        """Add a message to the log."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        def update():
            self.log_text.config(state=tk.NORMAL)
            self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)
        
        self.master.after(0, update)
    
    def update_audio_level(self, level):
        """Update the audio level meter."""
        def update():
            width = int(level * 2)  # Scale to canvas width
            color = '#00ff00' if level < 70 else '#ffff00' if level < 90 else '#ff0000'
            self.level_canvas.coords(self.level_bar, 0, 0, width, 20)
            self.level_canvas.itemconfig(self.level_bar, fill=color)
        
        self.master.after(0, update)
    
    # --- Connection Methods ---
    
    def connect_to_server(self):
        """Connect to the relay server."""
        host = self.host_entry.get().strip()
        port_str = self.port_entry.get().strip()
        username = self.username_entry.get().strip()
        
        if not host or not port_str or not username:
            messagebox.showwarning("Warning", "Please fill in all connection fields.")
            return
        
        try:
            port = int(port_str)
        except ValueError:
            messagebox.showerror("Error", "Invalid port number.")
            return
        
        self.log_message(f"Connecting to {host}:{port}...")
        
        try:
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client_socket.settimeout(10)
            self.client_socket.connect((host, port))
            
            # Send username
            self.client_socket.sendall(username.encode("utf-8"))
            
            # Wait for response
            response = self.client_socket.recv(1024).decode("utf-8")
            
            if response.startswith("ERROR"):
                error_msg = response.split("|", 1)[1] if "|" in response else response
                raise Exception(error_msg)
            
            self.client_socket.settimeout(None)
            self.user_id = username
            self.connected = True
            
            # Update UI
            self.status_label.config(text=f"* Connected as '{username}'", foreground="green")
            self.connect_button.config(state=tk.DISABLED)
            self.disconnect_button.config(state=tk.NORMAL)
            self.create_room_btn.config(state=tk.NORMAL)
            self.join_room_btn.config(state=tk.NORMAL)
            self.host_entry.config(state=tk.DISABLED)
            self.port_entry.config(state=tk.DISABLED)
            self.username_entry.config(state=tk.DISABLED)
            
            self.log_message(f"Connected as '{username}'")
            
            # Start receive thread
            self.receive_thread = threading.Thread(target=self.receive_messages, daemon=True)
            self.receive_thread.start()
            
            # Start audio output
            if self.audio_handler:
                self.audio_handler.start_output()
            
        except Exception as e:
            self.log_message(f"Connection failed: {e}")
            messagebox.showerror("Connection Error", str(e))
            if self.client_socket:
                self.client_socket.close()
                self.client_socket = None
    
    def disconnect(self):
        """Disconnect from the server."""
        if self.current_room:
            self.leave_room()
        
        self.connected = False
        
        if self.client_socket:
            try:
                self.client_socket.close()
            except:
                pass
            self.client_socket = None
        
        if self.audio_handler:
            self.audio_handler.stop()
        
        # Update UI
        self.status_label.config(text="* Disconnected", foreground="red")
        self.connect_button.config(state=tk.NORMAL)
        self.disconnect_button.config(state=tk.DISABLED)
        self.create_room_btn.config(state=tk.DISABLED)
        self.join_room_btn.config(state=tk.DISABLED)
        self.leave_room_btn.config(state=tk.DISABLED)
        self.ptt_button.config(state=tk.DISABLED)
        self.invite_btn.config(state=tk.DISABLED)
        self.host_entry.config(state=tk.NORMAL)
        self.port_entry.config(state=tk.NORMAL)
        self.username_entry.config(state=tk.NORMAL)
        
        self.log_message("Disconnected")
    
    # --- Room Methods ---
    
    def create_room(self):
        """Create a new voice room."""
        room_id = self.room_entry.get().strip()
        password = self.room_pass_entry.get().strip()
        
        if not room_id:
            room_id = f"room_{self.user_id}_{int(time.time())}"
            self.room_entry.delete(0, tk.END)
            self.room_entry.insert(0, room_id)
        
        if not password:
            messagebox.showwarning("Warning", "Please enter a room password for encryption.")
            return
        
        # Create room locally
        self.current_room = VoiceRoom(room_id, password, is_creator=True)
        self.current_room.add_participant(self.user_id)
        
        # Send room create command
        # Format: ROOM|CREATE|room_id|salt
        msg = f"{PROTO_ROOM}|{CMD_CREATE}|{room_id}|{self.current_room.salt}"
        self.send_to_server(msg)
        
        self.update_room_ui()
        self.log_message(f"Created room: {room_id}")
    
    def join_room(self):
        """Join an existing voice room."""
        room_id = self.room_entry.get().strip()
        password = self.room_pass_entry.get().strip()
        
        if not room_id or not password:
            messagebox.showwarning("Warning", "Please enter room ID and password.")
            return
        
        # Create room locally (salt will be received from server)
        self.current_room = VoiceRoom(room_id, password, is_creator=False)
        self.current_room.add_participant(self.user_id)
        
        # Send join command
        msg = f"{PROTO_ROOM}|{CMD_JOIN}|{room_id}"
        self.send_to_server(msg)
        
        self.log_message(f"Joining room: {room_id}...")
    
    def leave_room(self):
        """Leave the current voice room."""
        if not self.current_room:
            return
        
        # Stop audio transmission
        self.stop_transmit(None)
        
        # Send leave command
        msg = f"{PROTO_ROOM}|{CMD_LEAVE}|{self.current_room.room_id}"
        self.send_to_server(msg)
        
        room_id = self.current_room.room_id
        self.current_room = None
        
        self.update_room_ui()
        self.log_message(f"Left room: {room_id}")
    
    def invite_user(self):
        """Invite a user to the current room."""
        if not self.current_room:
            return
        
        target_user = self.invite_entry.get().strip()
        if not target_user:
            return
        
        # Send invite with room info and salt
        msg = f"{PROTO_ROOM}|{CMD_INVITE}|{target_user}|{self.current_room.room_id}|{self.current_room.salt}"
        self.send_to_server(msg)
        
        self.invite_entry.delete(0, tk.END)
        self.log_message(f"Invited {target_user} to room")
    
    def update_room_ui(self):
        """Update UI based on room state."""
        if self.current_room:
            self.room_status.config(
                text=f"In room: {self.current_room.room_id} ({len(self.current_room.participants)} participants)",
                foreground="green"
            )
            self.create_room_btn.config(state=tk.DISABLED)
            self.join_room_btn.config(state=tk.DISABLED)
            self.leave_room_btn.config(state=tk.NORMAL)
            self.ptt_button.config(state=tk.NORMAL)
            self.invite_btn.config(state=tk.NORMAL)
            self.room_entry.config(state=tk.DISABLED)
            self.room_pass_entry.config(state=tk.DISABLED)
            
            # Update participants list
            self.participants_list.delete(0, tk.END)
            for participant in sorted(self.current_room.participants):
                prefix = "[*] " if participant == self.user_id else "[@] "
                self.participants_list.insert(tk.END, f"{prefix}{participant}")
        else:
            self.room_status.config(text="Not in a room", foreground="gray")
            self.create_room_btn.config(state=tk.NORMAL if self.connected else tk.DISABLED)
            self.join_room_btn.config(state=tk.NORMAL if self.connected else tk.DISABLED)
            self.leave_room_btn.config(state=tk.DISABLED)
            self.ptt_button.config(state=tk.DISABLED)
            self.invite_btn.config(state=tk.DISABLED)
            self.room_entry.config(state=tk.NORMAL)
            self.room_pass_entry.config(state=tk.NORMAL)
            self.participants_list.delete(0, tk.END)
    
    # --- Audio Methods ---
    
    def start_transmit(self, event):
        """Start transmitting audio."""
        if not self.current_room or not self.audio_handler or self.is_muted:
            return
        
        if self.is_transmitting:
            return
        
        self.is_transmitting = True
        self.ptt_button.config(bg='#00aa00', text="[V] TRANSMITTING...")
        
        # Start audio capture in a thread
        self.audio_thread = threading.Thread(target=self.audio_capture_loop, daemon=True)
        self.audio_thread.start()
    
    def stop_transmit(self, event):
        """Stop transmitting audio."""
        if not self.is_transmitting:
            return
        
        self.is_transmitting = False
        self.ptt_button.config(bg='#333333', text="[V] PUSH TO TALK")
        self.update_audio_level(0)
    
    def audio_capture_loop(self):
        """Capture and send audio data."""
        if not self.audio_handler or not self.audio_handler.pyaudio:
            return
        
        try:
            stream = self.audio_handler.pyaudio.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=RATE,
                input=True,
                frames_per_buffer=CHUNK_SIZE
            )
            
            while self.is_transmitting and self.current_room:
                try:
                    audio_data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
                    
                    # Update level meter
                    level = self.audio_handler.calculate_level(audio_data)
                    self.update_audio_level(level)
                    
                    # Encrypt and send
                    encrypted = self.current_room.encrypt_audio(audio_data)
                    encoded = base64.b64encode(encrypted).decode('utf-8')
                    
                    # Format: VOICE|room_id|sender|encoded_audio
                    msg = f"{PROTO_VOICE}|{self.current_room.room_id}|{self.user_id}|{encoded}"
                    self.send_to_server(msg)
                    
                except Exception as e:
                    if self.is_transmitting:
                        self.log_message(f"Audio error: {e}")
                    break
            
            stream.stop_stream()
            stream.close()
            
        except Exception as e:
            self.log_message(f"Failed to capture audio: {e}")
    
    def toggle_mute(self):
        """Toggle microphone mute."""
        self.is_muted = self.mute_var.get()
        if self.is_muted:
            self.stop_transmit(None)
            self.log_message("Microphone muted")
        else:
            self.log_message("Microphone unmuted")
    
    def toggle_ptt_mode(self):
        """Toggle between push-to-talk and continuous modes."""
        self.push_to_talk = self.ptt_var.get()
        if self.push_to_talk:
            self.ptt_button.config(text="[V] PUSH TO TALK")
            self.log_message("Push-to-talk mode enabled")
        else:
            self.ptt_button.config(text="[V] TOGGLE MIC")
            self.log_message("Continuous mode enabled - click to toggle")
    
    def handle_space_press(self, event):
        """Handle spacebar press for PTT."""
        if self.push_to_talk and self.current_room:
            self.start_transmit(event)
    
    def handle_space_release(self, event):
        """Handle spacebar release for PTT."""
        if self.push_to_talk:
            self.stop_transmit(event)
    
    # --- Network Methods ---
    
    def send_to_server(self, message):
        """Send a message to the relay server."""
        if not self.client_socket or not self.connected:
            return
        
        try:
            # For voice protocol, send to special handler
            # Format: _VOICE_TARGET_|room_id|content
            self.client_socket.sendall(message.encode("utf-8"))
        except Exception as e:
            self.log_message(f"Send error: {e}")
    
    def receive_messages(self):
        """Background thread to receive messages."""
        while self.connected and self.client_socket:
            try:
                data = self.client_socket.recv(65536)  # Larger buffer for audio
                if not data:
                    break
                
                message = data.decode("utf-8")
                self.process_received_message(message)
                
            except ConnectionResetError:
                break
            except Exception as e:
                if self.connected:
                    self.master.after(0, lambda: self.log_message(f"Receive error: {e}"))
                break
        
        if self.connected:
            self.master.after(0, self.handle_disconnect)
    
    def process_received_message(self, raw_message):
        """Process a received message."""
        try:
            parts = raw_message.split("|", 3)
            
            if len(parts) < 2:
                return
            
            msg_type = parts[0]
            
            if msg_type == PROTO_VOICE:
                # Voice data: VOICE|room_id|sender|encoded_audio
                if len(parts) >= 4:
                    room_id, sender, encoded = parts[1], parts[2], parts[3]
                    self.handle_voice_data(room_id, sender, encoded)
            
            elif msg_type == PROTO_ROOM:
                # Room management: ROOM|cmd|...
                self.handle_room_message(parts[1:])
            
            elif msg_type == PROTO_SIGNAL:
                # Signaling: SIGNAL|type|...
                self.handle_signal_message(parts[1:])
            
            elif msg_type == "SYSTEM":
                # System message
                self.master.after(0, lambda: self.log_message(f"System: {parts[1]}"))
            
        except Exception as e:
            self.log_message(f"Message parse error: {e}")
    
    def handle_voice_data(self, room_id, sender, encoded):
        """Handle received voice data."""
        if not self.current_room or self.current_room.room_id != room_id:
            return
        
        if sender == self.user_id:
            return  # Don't play back our own audio
        
        try:
            encrypted = base64.b64decode(encoded)
            audio_data = self.current_room.decrypt_audio(encrypted)
            
            if audio_data and self.audio_handler:
                self.audio_handler.play_audio(audio_data, sender)
        except Exception as e:
            pass  # Silently ignore decryption errors
    
    def handle_room_message(self, parts):
        """Handle room management messages."""
        if not parts:
            return
        
        cmd = parts[0]
        
        if cmd == "JOINED":
            # User joined: JOINED|user_id
            if len(parts) >= 2 and self.current_room:
                user = parts[1]
                self.current_room.add_participant(user)
                self.master.after(0, self.update_room_ui)
                self.master.after(0, lambda: self.log_message(f"{user} joined the room"))
        
        elif cmd == "LEFT":
            # User left: LEFT|user_id
            if len(parts) >= 2 and self.current_room:
                user = parts[1]
                self.current_room.remove_participant(user)
                self.master.after(0, self.update_room_ui)
                self.master.after(0, lambda: self.log_message(f"{user} left the room"))
        
        elif cmd == "SALT":
            # Salt received: SALT|salt_b64
            if len(parts) >= 2 and self.current_room:
                self.current_room.set_salt(parts[1])
                self.master.after(0, self.update_room_ui)
                self.master.after(0, lambda: self.log_message("Joined room successfully"))
        
        elif cmd == "MEMBERS":
            # Member list: MEMBERS|user1,user2,user3
            if len(parts) >= 2 and self.current_room:
                members = parts[1].split(",") if parts[1] else []
                for member in members:
                    if member:
                        self.current_room.add_participant(member)
                self.master.after(0, self.update_room_ui)
        
        elif cmd == "INVITE":
            # Incoming invite: INVITE|from_user|room_id|salt
            if len(parts) >= 4:
                from_user, room_id, salt = parts[1], parts[2], parts[3]
                self.master.after(0, lambda: self.handle_invite(from_user, room_id, salt))
        
        elif cmd == "ERROR":
            # Error message
            if len(parts) >= 2:
                self.master.after(0, lambda: self.log_message(f"Room error: {parts[1]}"))
                if self.current_room and not self.current_room.is_creator:
                    self.current_room = None
                    self.master.after(0, self.update_room_ui)
    
    def handle_signal_message(self, parts):
        """Handle signaling messages."""
        pass  # Placeholder for future WebRTC-style signaling
    
    def handle_invite(self, from_user, room_id, salt):
        """Handle an incoming room invite."""
        result = messagebox.askyesno(
            "Voice Call Invite",
            f"{from_user} is inviting you to voice room '{room_id}'.\n\nDo you want to join?"
        )
        
        if result:
            # Prompt for password
            password = simpledialog.askstring(
                "Room Password",
                f"Enter the password for room '{room_id}':",
                show='-'
            )
            
            if password:
                self.current_room = VoiceRoom(room_id, password, is_creator=False)
                self.current_room.set_salt(salt)
                self.current_room.add_participant(self.user_id)
                
                # Send join command
                msg = f"{PROTO_ROOM}|{CMD_JOIN}|{room_id}"
                self.send_to_server(msg)
                
                self.update_room_ui()
                self.log_message(f"Joined room: {room_id}")
    
    def handle_disconnect(self):
        """Handle unexpected disconnection."""
        self.connected = False
        self.client_socket = None
        self.current_room = None
        
        if self.audio_handler:
            self.audio_handler.stop()
        
        self.status_label.config(text="* Disconnected", foreground="red")
        self.connect_button.config(state=tk.NORMAL)
        self.disconnect_button.config(state=tk.DISABLED)
        self.host_entry.config(state=tk.NORMAL)
        self.port_entry.config(state=tk.NORMAL)
        self.username_entry.config(state=tk.NORMAL)
        
        self.update_room_ui()
        self.log_message("Lost connection to server")
        messagebox.showwarning("Disconnected", "Lost connection to the server.")
    
    def cleanup(self):
        """Clean up resources on exit."""
        self.connected = False
        
        if self.audio_handler:
            self.audio_handler.cleanup()
        
        if self.client_socket:
            try:
                self.client_socket.close()
            except:
                pass


def show_disclaimer():
    """Show legal disclaimer on startup."""
    disclaimer = (
        "OTP VOICE - ENCRYPTED VOICE CALLS\n\n"
        "This software is intended for educational and lawful use only.\n\n"
        "Voice data is encrypted using AES-256-GCM.\n"
        "Security depends on keeping the room password secret.\n\n"
        "Requirements:\n"
        "- pyaudio - for audio capture/playback\n"
        "- cryptography - for AES encryption"
    )
    messagebox.showinfo("OTP Voice Client", disclaimer)


def main():
    if not AUDIO_AVAILABLE or not CRYPTO_AVAILABLE:
        missing = []
        if not AUDIO_AVAILABLE:
            missing.append("pyaudio")
        if not CRYPTO_AVAILABLE:
            missing.append("cryptography")
        
        messagebox.showwarning(
            "Missing Dependencies",
            f"The following packages are required:\n\n"
            f"{', '.join(missing)}\n\n"
            f"Install with:\npip install {' '.join(missing)}"
        )
    
    root = tk.Tk()
    show_disclaimer()
    app = VoiceClientGUI(root)
    
    def on_close():
        app.cleanup()
        root.destroy()
    
    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
