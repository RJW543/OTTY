"""
OTP Relay Server with Voice Room Support
Routes encrypted messages AND voice calls between connected clients.
Supports one-on-one messaging, one-on-one calls, and group voice calls.

New Protocol Types:
- VOICE: Voice audio data routing
- ROOM: Voice room management (create, join, leave, invite)
- SIGNAL: Call signaling

Works with:
- OTP Client (text messaging)
- OTP Voice Client (voice calls)
- OTP Generator (key generation)
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import socket
import socketserver
from datetime import datetime
from collections import defaultdict

try:
    from pyngrok import ngrok
    NGROK_AVAILABLE = True
except ImportError:
    NGROK_AVAILABLE = False


# Global client registry: {user_id: socket}
clients = {}
clients_lock = threading.Lock()

# Voice rooms registry: {room_id: VoiceRoomInfo}
voice_rooms = {}
rooms_lock = threading.Lock()


class VoiceRoomInfo:
    """Server-side voice room information."""
    
    def __init__(self, room_id: str, creator: str, salt: str):
        self.room_id = room_id
        self.creator = creator
        self.salt = salt  # Encryption salt (shared with joiners)
        self.participants = {creator}
        self.created_at = datetime.now()
    
    def add_participant(self, user_id: str):
        self.participants.add(user_id)
    
    def remove_participant(self, user_id: str):
        self.participants.discard(user_id)
        return len(self.participants) == 0  # Return True if room is now empty
    
    def get_members_str(self) -> str:
        return ",".join(sorted(self.participants))


class ThreadedTCPRequestHandler(socketserver.BaseRequestHandler):
    """Handles individual client connections in separate threads."""
    
    def handle(self):
        client_socket = self.request
        user_id = None
        
        try:
            # Receive the userID upon connection
            user_id = client_socket.recv(1024).decode("utf-8").strip()
            
            if not user_id:
                client_socket.sendall("ERROR|Invalid userID. Connection closed.".encode("utf-8"))
                return
            
            with clients_lock:
                if user_id in clients:
                    client_socket.sendall("ERROR|UserID already taken. Connection closed.".encode("utf-8"))
                    self.server.gui.log_message(f"Rejected '{user_id}' - ID already in use")
                    return
                
                # Register the client
                clients[user_id] = client_socket
            
            client_socket.sendall("OK|Connected successfully.".encode("utf-8"))
            self.server.gui.log_message(f"User '{user_id}' connected from {self.client_address[0]}")
            self.server.gui.update_client_count()
            
            # Handle incoming messages from this client
            while True:
                data = client_socket.recv(65536)  # Larger buffer for voice data
                if not data:
                    break
                
                message = data.decode("utf-8")
                self.process_message(message, user_id)
                
        except ConnectionResetError:
            self.server.gui.log_message(f"Connection reset by '{user_id or 'unknown'}'")
        except Exception as e:
            self.server.gui.log_message(f"Error with '{user_id or 'unknown'}': {e}")
        finally:
            if user_id:
                # Clean up user from any voice rooms
                self.cleanup_user_from_rooms(user_id)
                
                with clients_lock:
                    if user_id in clients:
                        del clients[user_id]
                self.server.gui.log_message(f"User '{user_id}' disconnected")
                self.server.gui.update_client_count()
                self.server.gui.update_room_count()
    
    def cleanup_user_from_rooms(self, user_id: str):
        """Remove user from all voice rooms they're in."""
        rooms_to_delete = []
        
        with rooms_lock:
            for room_id, room in voice_rooms.items():
                if user_id in room.participants:
                    is_empty = room.remove_participant(user_id)
                    if is_empty:
                        rooms_to_delete.append(room_id)
                    else:
                        # Notify other participants
                        self.broadcast_to_room(room_id, f"ROOM|LEFT|{user_id}", exclude=user_id)
            
            # Delete empty rooms
            for room_id in rooms_to_delete:
                del voice_rooms[room_id]
                self.server.gui.log_message(f"Room '{room_id}' closed (empty)")
    
    def process_message(self, message: str, sender_id: str):
        """Parse and route a message."""
        try:
            parts = message.split("|", 3)
            
            if not parts:
                return
            
            msg_type = parts[0]
            
            # Voice data routing
            if msg_type == "VOICE":
                self.handle_voice_message(parts, sender_id)
            
            # Room management
            elif msg_type == "ROOM":
                self.handle_room_command(parts, sender_id)
            
            # Signaling
            elif msg_type == "SIGNAL":
                self.handle_signal_message(parts, sender_id)
            
            # Standard OTP text message routing
            else:
                self.route_text_message(message, sender_id)
                
        except Exception as e:
            self.server.gui.log_message(f"Error processing message from '{sender_id}': {e}")
    
    def handle_voice_message(self, parts: list, sender_id: str):
        """Route voice data to room participants."""
        # Format: VOICE|room_id|sender|encoded_audio
        if len(parts) < 4:
            return
        
        room_id = parts[1]
        encoded_audio = parts[3]
        
        with rooms_lock:
            room = voice_rooms.get(room_id)
            if not room or sender_id not in room.participants:
                return
        
        # Broadcast to all other participants
        voice_msg = f"VOICE|{room_id}|{sender_id}|{encoded_audio}"
        self.broadcast_to_room(room_id, voice_msg, exclude=sender_id)
    
    def handle_room_command(self, parts: list, sender_id: str):
        """Handle room management commands."""
        if len(parts) < 3:
            return
        
        cmd = parts[1]
        
        if cmd == "CREATE":
            # Format: ROOM|CREATE|room_id|salt
            if len(parts) >= 4:
                room_id, salt = parts[2], parts[3]
                self.create_room(room_id, sender_id, salt)
        
        elif cmd == "JOIN":
            # Format: ROOM|JOIN|room_id
            room_id = parts[2]
            self.join_room(room_id, sender_id)
        
        elif cmd == "LEAVE":
            # Format: ROOM|LEAVE|room_id
            room_id = parts[2]
            self.leave_room(room_id, sender_id)
        
        elif cmd == "INVITE":
            # Format: ROOM|INVITE|target_user|room_id|salt
            if len(parts) >= 4:
                # Parse differently - we need to handle this format
                remaining = "|".join(parts[2:])
                invite_parts = remaining.split("|")
                if len(invite_parts) >= 3:
                    target_user, room_id, salt = invite_parts[0], invite_parts[1], invite_parts[2]
                    self.send_invite(sender_id, target_user, room_id, salt)
        
        elif cmd == "LIST":
            # Format: ROOM|LIST
            self.list_rooms(sender_id)
    
    def create_room(self, room_id: str, creator: str, salt: str):
        """Create a new voice room."""
        with rooms_lock:
            if room_id in voice_rooms:
                self.send_to_user(creator, f"ROOM|ERROR|Room '{room_id}' already exists")
                return
            
            room = VoiceRoomInfo(room_id, creator, salt)
            voice_rooms[room_id] = room
        
        self.server.gui.log_message(f"Room '{room_id}' created by '{creator}'")
        self.server.gui.update_room_count()
        
        # Send confirmation
        self.send_to_user(creator, f"ROOM|CREATED|{room_id}")
    
    def join_room(self, room_id: str, user_id: str):
        """Add user to a voice room."""
        with rooms_lock:
            room = voice_rooms.get(room_id)
            if not room:
                self.send_to_user(user_id, f"ROOM|ERROR|Room '{room_id}' not found")
                return
            
            # Add participant
            room.add_participant(user_id)
            
            # Send salt to new participant
            self.send_to_user(user_id, f"ROOM|SALT|{room.salt}")
            
            # Send current member list
            self.send_to_user(user_id, f"ROOM|MEMBERS|{room.get_members_str()}")
            
            # Notify other participants
            for participant in room.participants:
                if participant != user_id:
                    self.send_to_user(participant, f"ROOM|JOINED|{user_id}")
        
        self.server.gui.log_message(f"User '{user_id}' joined room '{room_id}'")
    
    def leave_room(self, room_id: str, user_id: str):
        """Remove user from a voice room."""
        room_deleted = False
        
        with rooms_lock:
            room = voice_rooms.get(room_id)
            if not room:
                return
            
            is_empty = room.remove_participant(user_id)
            
            if is_empty:
                del voice_rooms[room_id]
                room_deleted = True
            else:
                # Notify remaining participants
                for participant in room.participants:
                    self.send_to_user(participant, f"ROOM|LEFT|{user_id}")
        
        if room_deleted:
            self.server.gui.log_message(f"Room '{room_id}' closed (empty)")
        else:
            self.server.gui.log_message(f"User '{user_id}' left room '{room_id}'")
        
        self.server.gui.update_room_count()
    
    def send_invite(self, from_user: str, target_user: str, room_id: str, salt: str):
        """Send a room invite to a user."""
        with rooms_lock:
            room = voice_rooms.get(room_id)
            if not room:
                self.send_to_user(from_user, f"ROOM|ERROR|Room '{room_id}' not found")
                return
        
        # Send invite to target user
        invite_msg = f"ROOM|INVITE|{from_user}|{room_id}|{salt}"
        if self.send_to_user(target_user, invite_msg):
            self.server.gui.log_message(f"Invite sent: '{from_user}' -> '{target_user}' for room '{room_id}'")
        else:
            self.send_to_user(from_user, f"ROOM|ERROR|User '{target_user}' is not online")
    
    def list_rooms(self, user_id: str):
        """Send list of active rooms to user."""
        with rooms_lock:
            if not voice_rooms:
                self.send_to_user(user_id, "ROOM|LIST|")
                return
            
            room_list = []
            for room_id, room in voice_rooms.items():
                room_list.append(f"{room_id}:{len(room.participants)}")
            
            self.send_to_user(user_id, f"ROOM|LIST|{','.join(room_list)}")
    
    def handle_signal_message(self, parts: list, sender_id: str):
        """Handle signaling messages for call setup."""
        # Placeholder for WebRTC-style signaling if needed
        pass
    
    def route_text_message(self, message: str, sender_id: str):
        """Route a standard text message to its recipient."""
        try:
            # Message format: recipient_id|otp_identifier:encrypted_content
            recipient_id, payload = message.split("|", 1)
            
            self.server.gui.log_message(
                f"Routing message: '{sender_id}' -> '{recipient_id}' ({len(payload)} bytes)"
            )
            
            with clients_lock:
                recipient_socket = clients.get(recipient_id)
                sender_socket = clients.get(sender_id)
            
            if recipient_socket:
                try:
                    # Forward message with sender info: sender_id|payload
                    full_message = f"{sender_id}|{payload}"
                    recipient_socket.sendall(full_message.encode("utf-8"))
                except Exception as e:
                    self.server.gui.log_message(f"Failed to deliver to '{recipient_id}': {e}")
                    with clients_lock:
                        if recipient_id in clients:
                            del clients[recipient_id]
            else:
                # Notify sender that recipient is offline
                if sender_socket:
                    error_msg = f"SYSTEM|offline:{recipient_id} is not online."
                    sender_socket.sendall(error_msg.encode("utf-8"))
                self.server.gui.log_message(f"Recipient '{recipient_id}' not found")
                
        except ValueError:
            self.server.gui.log_message(f"Malformed message from '{sender_id}'")
    
    def broadcast_to_room(self, room_id: str, message: str, exclude: str = None):
        """Send a message to all participants in a room."""
        with rooms_lock:
            room = voice_rooms.get(room_id)
            if not room:
                return
            participants = list(room.participants)
        
        for participant in participants:
            if participant != exclude:
                self.send_to_user(participant, message)
    
    def send_to_user(self, user_id: str, message: str) -> bool:
        """Send a message to a specific user."""
        with clients_lock:
            socket = clients.get(user_id)
        
        if socket:
            try:
                socket.sendall(message.encode("utf-8"))
                return True
            except Exception as e:
                self.server.gui.log_message(f"Failed to send to '{user_id}': {e}")
        return False


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """Multi-threaded TCP server."""
    daemon_threads = True
    allow_reuse_address = True
    
    def __init__(self, server_address, RequestHandlerClass, gui):
        super().__init__(server_address, RequestHandlerClass)
        self.gui = gui


class RelayServerGUI:
    """Main GUI for the OTP Relay Server with Voice Support."""
    
    def __init__(self, master):
        self.master = master
        self.master.title("OTP Relay Server (Voice Enabled)")
        self.master.geometry("600x550")
        self.master.minsize(550, 500)
        
        self.HOST = "0.0.0.0"
        self.PORT = 65432
        
        self.server = None
        self.server_thread = None
        self.ngrok_tunnel = None
        
        self.setup_ui()
    
    def setup_ui(self):
        """Build the user interface."""
        style = ttk.Style()
        style.theme_use('clam')
        
        main_frame = ttk.Frame(self.master, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # --- Status Section ---
        status_frame = ttk.LabelFrame(main_frame, text="Server Status", padding="10")
        status_frame.pack(fill=tk.X, pady=(0, 10))
        
        status_row = ttk.Frame(status_frame)
        status_row.pack(fill=tk.X)
        
        self.status_indicator = tk.Label(
            status_row, text="● STOPPED", fg="red", font=("Arial", 14, "bold")
        )
        self.status_indicator.pack(side=tk.LEFT)
        
        # Stats on the right
        stats_frame = ttk.Frame(status_row)
        stats_frame.pack(side=tk.RIGHT)
        
        self.client_count_label = ttk.Label(stats_frame, text="Clients: 0")
        self.client_count_label.pack(side=tk.LEFT, padx=(0, 15))
        
        self.room_count_label = ttk.Label(stats_frame, text="Rooms: 0")
        self.room_count_label.pack(side=tk.LEFT)
        
        # --- Connection Info Section ---
        info_frame = ttk.LabelFrame(main_frame, text="Connection Details", padding="10")
        info_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Port configuration
        port_frame = ttk.Frame(info_frame)
        port_frame.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(port_frame, text="Local Port:").pack(side=tk.LEFT)
        self.port_var = tk.StringVar(value="65432")
        self.port_entry = ttk.Entry(port_frame, textvariable=self.port_var, width=8)
        self.port_entry.pack(side=tk.LEFT, padx=(5, 0))
        
        # Ngrok info display
        self.ngrok_label = ttk.Label(info_frame, text="Ngrok: Not started", foreground="gray")
        self.ngrok_label.pack(fill=tk.X, pady=(5, 0))
        
        self.connection_info = ttk.Label(info_frame, text="", font=("Consolas", 10))
        self.connection_info.pack(fill=tk.X)
        
        # --- Control Buttons ---
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.start_button = ttk.Button(
            button_frame, text="Start Server", command=self.start_server
        )
        self.start_button.pack(side=tk.LEFT, padx=(0, 5))
        
        self.stop_button = ttk.Button(
            button_frame, text="Stop Server", command=self.stop_server, state=tk.DISABLED
        )
        self.stop_button.pack(side=tk.LEFT)
        
        self.copy_button = ttk.Button(
            button_frame, text="Copy Connection Info", command=self.copy_connection_info, state=tk.DISABLED
        )
        self.copy_button.pack(side=tk.RIGHT)
        
        # --- Active Rooms Section ---
        rooms_frame = ttk.LabelFrame(main_frame, text="Active Voice Rooms", padding="5")
        rooms_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.rooms_list = tk.Listbox(rooms_frame, height=4, font=("Consolas", 9))
        self.rooms_list.pack(fill=tk.X)
        
        # --- Log Section ---
        log_frame = ttk.LabelFrame(main_frame, text="Activity Log", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        self.log_area = scrolledtext.ScrolledText(
            log_frame, height=12, state=tk.DISABLED, font=("Consolas", 9)
        )
        self.log_area.pack(fill=tk.BOTH, expand=True)
        
        # Check ngrok availability
        if not NGROK_AVAILABLE:
            self.log_message("Warning: pyngrok not installed. Install with: pip install pyngrok")
        
        # Start room list update timer
        self.update_rooms_list()
    
    def log_message(self, message):
        """Add a timestamped message to the log."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        def update():
            self.log_area.config(state=tk.NORMAL)
            self.log_area.insert(tk.END, f"[{timestamp}] {message}\n")
            self.log_area.see(tk.END)
            self.log_area.config(state=tk.DISABLED)
        
        self.master.after(0, update)
    
    def update_client_count(self):
        """Update the connected clients counter."""
        def update():
            with clients_lock:
                count = len(clients)
            self.client_count_label.config(text=f"Clients: {count}")
        
        self.master.after(0, update)
    
    def update_room_count(self):
        """Update the active rooms counter."""
        def update():
            with rooms_lock:
                count = len(voice_rooms)
            self.room_count_label.config(text=f"Rooms: {count}")
        
        self.master.after(0, update)
    
    def update_rooms_list(self):
        """Periodically update the rooms display."""
        def update():
            self.rooms_list.delete(0, tk.END)
            with rooms_lock:
                if not voice_rooms:
                    self.rooms_list.insert(tk.END, "(No active rooms)")
                else:
                    for room_id, room in voice_rooms.items():
                        participants = ", ".join(sorted(room.participants))
                        self.rooms_list.insert(
                            tk.END,
                            f"🔊 {room_id} [{len(room.participants)}] - {participants}"
                        )
        
        self.master.after(0, update)
        self.master.after(2000, self.update_rooms_list)  # Update every 2 seconds
    
    def start_server(self):
        """Start the relay server with ngrok tunnel."""
        try:
            self.PORT = int(self.port_var.get())
        except ValueError:
            messagebox.showerror("Error", "Invalid port number")
            return
        
        try:
            # Start ngrok tunnel if available
            if NGROK_AVAILABLE:
                self.log_message("Starting ngrok tunnel...")
                self.ngrok_tunnel = ngrok.connect(self.PORT, "tcp")
                public_url = self.ngrok_tunnel.public_url
                
                # Parse the public URL
                parsed = public_url.replace("tcp://", "").split(":")
                ngrok_host = parsed[0]
                ngrok_port = parsed[1]
                
                self.ngrok_label.config(text=f"Ngrok: Active", foreground="green")
                self.connection_info.config(text=f"Host: {ngrok_host}  |  Port: {ngrok_port}")
                self.ngrok_host = ngrok_host
                self.ngrok_port = ngrok_port
                self.copy_button.config(state=tk.NORMAL)
                
                self.log_message(f"Ngrok tunnel active: {public_url}")
            else:
                self.ngrok_label.config(text="Ngrok: Unavailable (local only)", foreground="orange")
                self.connection_info.config(text=f"Local: {self.HOST}:{self.PORT}")
            
            # Start the TCP server
            def run_server():
                self.server = ThreadedTCPServer(
                    (self.HOST, self.PORT), ThreadedTCPRequestHandler, self
                )
                self.log_message(f"Server listening on {self.HOST}:{self.PORT}")
                self.log_message("Voice rooms and text messaging enabled")
                self.server.serve_forever()
            
            self.server_thread = threading.Thread(target=run_server, daemon=True)
            self.server_thread.start()
            
            # Update UI state
            self.status_indicator.config(text="● RUNNING", fg="green")
            self.start_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.NORMAL)
            self.port_entry.config(state=tk.DISABLED)
            
        except Exception as e:
            self.log_message(f"Failed to start server: {e}")
            messagebox.showerror("Error", f"Failed to start server:\n{e}")
    
    def stop_server(self):
        """Stop the relay server and ngrok tunnel."""
        self.log_message("Stopping server...")
        
        # Disconnect all clients
        with clients_lock:
            for user_id, sock in list(clients.items()):
                try:
                    sock.close()
                except:
                    pass
            clients.clear()
        
        # Clear all rooms
        with rooms_lock:
            voice_rooms.clear()
        
        # Stop the server
        if self.server:
            try:
                self.server.shutdown()
                self.server.server_close()
            except Exception as e:
                self.log_message(f"Error stopping server: {e}")
        
        # Disconnect ngrok
        if self.ngrok_tunnel and NGROK_AVAILABLE:
            try:
                ngrok.disconnect(self.ngrok_tunnel.public_url)
                self.log_message("Ngrok tunnel closed")
            except Exception as e:
                self.log_message(f"Error closing ngrok: {e}")
        
        # Reset state
        self.server = None
        self.server_thread = None
        self.ngrok_tunnel = None
        
        # Update UI
        self.status_indicator.config(text="● STOPPED", fg="red")
        self.ngrok_label.config(text="Ngrok: Not started", foreground="gray")
        self.connection_info.config(text="")
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        self.port_entry.config(state=tk.NORMAL)
        self.copy_button.config(state=tk.DISABLED)
        self.update_client_count()
        self.update_room_count()
        
        self.log_message("Server stopped")
    
    def copy_connection_info(self):
        """Copy connection details to clipboard."""
        if hasattr(self, 'ngrok_host') and hasattr(self, 'ngrok_port'):
            info = f"{self.ngrok_host}:{self.ngrok_port}"
            self.master.clipboard_clear()
            self.master.clipboard_append(info)
            self.log_message("Connection info copied to clipboard")


def main():
    root = tk.Tk()
    app = RelayServerGUI(root)
    
    def on_close():
        if app.server:
            app.stop_server()
        root.destroy()
    
    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
