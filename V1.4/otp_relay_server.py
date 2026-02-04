"""
OTP Relay Server - Text Message Routing
Routes encrypted OTP messages between connected clients.

This is the basic text-only relay server.
For voice + text support, use otp_relay_server_voice.py instead.

Compatible with:
- otp_client.py (legacy shared pad)
- otp_client_v2.py (per-contact pads)

Note: The relay server only routes encrypted messages - it never sees plaintext.
All encryption/decryption happens client-side using their OTP pads.

Usage:
    python3 otp_relay_server.py
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import socket
import socketserver
from datetime import datetime

try:
    from pyngrok import ngrok
    NGROK_AVAILABLE = True
except ImportError:
    NGROK_AVAILABLE = False


# Global client registry: {user_id: socket}
clients = {}
clients_lock = threading.Lock()


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
                data = client_socket.recv(8192)
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
                with clients_lock:
                    if user_id in clients:
                        del clients[user_id]
                self.server.gui.log_message(f"User '{user_id}' disconnected")
                self.server.gui.update_client_count()
    
    def process_message(self, message, sender_id):
        """Parse and route a message to its recipient."""
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


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """Multi-threaded TCP server."""
    daemon_threads = True
    allow_reuse_address = True
    
    def __init__(self, server_address, RequestHandlerClass, gui):
        super().__init__(server_address, RequestHandlerClass)
        self.gui = gui


class RelayServerGUI:
    """Main GUI for the OTP Relay Server."""
    
    def __init__(self, master):
        self.master = master
        self.master.title("OTP Relay Server")
        self.master.geometry("550x450")
        self.master.minsize(500, 400)
        
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
        
        self.status_indicator = tk.Label(
            status_frame, text="* STOPPED", fg="red", font=("Arial", 14, "bold")
        )
        self.status_indicator.pack(side=tk.LEFT)
        
        self.client_count_label = ttk.Label(status_frame, text="Clients: 0")
        self.client_count_label.pack(side=tk.RIGHT)
        
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
        
        # --- Log Section ---
        log_frame = ttk.LabelFrame(main_frame, text="Activity Log", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        self.log_area = scrolledtext.ScrolledText(
            log_frame, height=10, state=tk.DISABLED, font=("Consolas", 9)
        )
        self.log_area.pack(fill=tk.BOTH, expand=True)
        
        # Check ngrok availability
        if not NGROK_AVAILABLE:
            self.log_message("Warning: pyngrok not installed. Install with: pip install pyngrok")
    
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
                self.server.serve_forever()
            
            self.server_thread = threading.Thread(target=run_server, daemon=True)
            self.server_thread.start()
            
            # Update UI state
            self.status_indicator.config(text="* RUNNING", fg="green")
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
        self.status_indicator.config(text="* STOPPED", fg="red")
        self.ngrok_label.config(text="Ngrok: Not started", foreground="gray")
        self.connection_info.config(text="")
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        self.port_entry.config(state=tk.NORMAL)
        self.copy_button.config(state=tk.DISABLED)
        self.update_client_count()
        
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
