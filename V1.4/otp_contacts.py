#!/usr/bin/env python3
"""
OTP Contacts - Communication Hub
Central contact management and communication launcher for the OTP Secure Communications System.

Features:
- Device unique ID setup (admin pre-loads before giving to user)
- Contact management with nicknames
- Launch messaging or voice calls directly to contacts
- Persistent contact storage
- Integration with OTP Client and Voice Client

Usage:
    python3 otp_contacts.py

First Run:
    Admin enters the device's unique 11-character ID (0-9, a-z)
    This ID becomes the device's permanent identity

Contact IDs:
    - 11 characters exactly
    - Lowercase letters (a-z) and numbers (0-9) only
    - Example: "abc12def345"
"""

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from datetime import datetime

# --- CONFIGURATION ---
APP_DIR = Path(__file__).parent.resolve()
CONFIG_FILE = APP_DIR / "device_config.json"
CONTACTS_FILE = APP_DIR / "contacts.json"
CREDENTIALS_FILE = APP_DIR / "credentials.txt"

# Unique ID format: 11 characters, lowercase a-z and 0-9
ID_PATTERN = re.compile(r'^[a-z0-9]{11}$')
ID_LENGTH = 11


# --- DATA MANAGEMENT ---

class DeviceConfig:
    """Manages device configuration including unique ID."""
    
    def __init__(self):
        self.device_id = None
        self.setup_complete = False
        self.created_at = None
        self.load()
    
    def load(self):
        """Load device configuration from file."""
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, 'r') as f:
                    data = json.load(f)
                    self.device_id = data.get('device_id')
                    self.setup_complete = data.get('setup_complete', False)
                    self.created_at = data.get('created_at')
            except (json.JSONDecodeError, IOError):
                pass
    
    def save(self):
        """Save device configuration to file."""
        data = {
            'device_id': self.device_id,
            'setup_complete': self.setup_complete,
            'created_at': self.created_at
        }
        with open(CONFIG_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    
    def set_device_id(self, device_id: str) -> bool:
        """Set the device's unique ID (admin setup)."""
        if not self.validate_id(device_id):
            return False
        
        self.device_id = device_id.lower()
        self.setup_complete = True
        self.created_at = datetime.now().isoformat()
        self.save()
        
        # Also save to credentials.txt for compatibility with other apps
        self._update_credentials()
        
        return True
    
    def _update_credentials(self):
        """Update credentials.txt with the device ID."""
        try:
            with open(CREDENTIALS_FILE, 'w') as f:
                f.write(f"Username: {self.device_id}\n")
        except IOError:
            pass
    
    @staticmethod
    def validate_id(user_id: str) -> bool:
        """Validate a user ID format."""
        if not user_id:
            return False
        return bool(ID_PATTERN.match(user_id.lower()))


class ContactsManager:
    """Manages the user's contacts."""
    
    def __init__(self):
        self.contacts = {}  # {user_id: {'nickname': str, 'added_at': str, 'notes': str}}
        self.load()
    
    def load(self):
        """Load contacts from file."""
        if CONTACTS_FILE.exists():
            try:
                with open(CONTACTS_FILE, 'r') as f:
                    self.contacts = json.load(f)
            except (json.JSONDecodeError, IOError):
                self.contacts = {}
    
    def save(self):
        """Save contacts to file."""
        with open(CONTACTS_FILE, 'w') as f:
            json.dump(self.contacts, f, indent=2)
    
    def add_contact(self, user_id: str, nickname: str = None) -> tuple[bool, str]:
        """
        Add a new contact.
        
        Returns:
            (success: bool, message: str)
        """
        user_id = user_id.lower().strip()
        
        if not DeviceConfig.validate_id(user_id):
            return False, f"Invalid ID format. Must be {ID_LENGTH} characters (a-z, 0-9)."
        
        if user_id in self.contacts:
            return False, f"Contact '{user_id}' already exists."
        
        self.contacts[user_id] = {
            'nickname': nickname or user_id,
            'added_at': datetime.now().isoformat(),
            'notes': ''
        }
        self.save()
        return True, f"Contact added successfully."
    
    def remove_contact(self, user_id: str) -> bool:
        """Remove a contact."""
        user_id = user_id.lower()
        if user_id in self.contacts:
            del self.contacts[user_id]
            self.save()
            return True
        return False
    
    def update_nickname(self, user_id: str, nickname: str) -> bool:
        """Update a contact's nickname."""
        user_id = user_id.lower()
        if user_id in self.contacts:
            self.contacts[user_id]['nickname'] = nickname
            self.save()
            return True
        return False
    
    def update_notes(self, user_id: str, notes: str) -> bool:
        """Update a contact's notes."""
        user_id = user_id.lower()
        if user_id in self.contacts:
            self.contacts[user_id]['notes'] = notes
            self.save()
            return True
        return False
    
    def get_contact(self, user_id: str) -> dict:
        """Get a contact's details."""
        return self.contacts.get(user_id.lower())
    
    def get_display_name(self, user_id: str) -> str:
        """Get a contact's display name (nickname or ID)."""
        contact = self.get_contact(user_id)
        if contact:
            return contact.get('nickname', user_id)
        return user_id
    
    def get_all_contacts(self) -> list:
        """Get all contacts sorted by nickname."""
        contacts_list = [
            {'id': uid, **data}
            for uid, data in self.contacts.items()
        ]
        return sorted(contacts_list, key=lambda x: x['nickname'].lower())


# --- INITIAL SETUP DIALOG ---

class DeviceSetupDialog:
    """Dialog for initial device setup (admin enters unique ID)."""
    
    def __init__(self, parent):
        self.result = None
        
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Device Setup - Admin Configuration")
        self.dialog.geometry("450x350")
        self.dialog.resizable(False, False)
        self.dialog.configure(bg='#0d1117')
        
        # Make modal
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        # Center on screen
        self.dialog.update_idletasks()
        x = (self.dialog.winfo_screenwidth() - 450) // 2
        y = (self.dialog.winfo_screenheight() - 350) // 2
        self.dialog.geometry(f"+{x}+{y}")
        
        # Prevent closing without setup
        self.dialog.protocol("WM_DELETE_WINDOW", self.on_cancel)
        
        self.setup_ui()
    
    def setup_ui(self):
        # Header
        header_frame = tk.Frame(self.dialog, bg='#0d1117')
        header_frame.pack(fill=tk.X, padx=30, pady=(30, 20))
        
        tk.Label(
            header_frame,
            text="[W]",
            font=("Helvetica", 36),
            fg='#58a6ff',
            bg='#0d1117'
        ).pack()
        
        tk.Label(
            header_frame,
            text="Device Setup",
            font=("Helvetica", 20, "bold"),
            fg='#c9d1d9',
            bg='#0d1117'
        ).pack(pady=(10, 5))
        
        tk.Label(
            header_frame,
            text="Administrator Configuration",
            font=("Helvetica", 10),
            fg='#8b949e',
            bg='#0d1117'
        ).pack()
        
        # Instructions
        instructions = tk.Label(
            self.dialog,
            text="Enter the unique device ID.\nThis ID will identify this device on the network.",
            font=("Helvetica", 10),
            fg='#8b949e',
            bg='#0d1117',
            justify=tk.CENTER
        )
        instructions.pack(pady=(10, 20))
        
        # Input frame
        input_frame = tk.Frame(self.dialog, bg='#0d1117')
        input_frame.pack(pady=10)
        
        tk.Label(
            input_frame,
            text="Device ID:",
            font=("Helvetica", 11),
            fg='#c9d1d9',
            bg='#0d1117'
        ).pack(side=tk.LEFT, padx=(0, 10))
        
        self.id_var = tk.StringVar()
        self.id_var.trace('w', self.on_id_change)
        
        self.id_entry = tk.Entry(
            input_frame,
            textvariable=self.id_var,
            font=("Consolas", 14),
            width=15,
            justify=tk.CENTER
        )
        self.id_entry.pack(side=tk.LEFT)
        self.id_entry.focus_set()
        
        # Format hint
        self.hint_label = tk.Label(
            self.dialog,
            text=f"Format: {ID_LENGTH} characters (a-z, 0-9)",
            font=("Helvetica", 9),
            fg='#6e7681',
            bg='#0d1117'
        )
        self.hint_label.pack(pady=(5, 0))
        
        # Character counter
        self.counter_label = tk.Label(
            self.dialog,
            text=f"0/{ID_LENGTH}",
            font=("Consolas", 10),
            fg='#6e7681',
            bg='#0d1117'
        )
        self.counter_label.pack(pady=(5, 20))
        
        # Buttons
        btn_frame = tk.Frame(self.dialog, bg='#0d1117')
        btn_frame.pack(pady=10)
        
        self.confirm_btn = tk.Button(
            btn_frame,
            text="+ Confirm Setup",
            font=("Helvetica", 11),
            width=15,
            height=2,
            bg='#238636',
            fg='white',
            activebackground='#2ea043',
            activeforeground='white',
            relief='flat',
            state=tk.DISABLED,
            command=self.on_confirm
        )
        self.confirm_btn.pack(side=tk.LEFT, padx=5)
        
        tk.Button(
            btn_frame,
            text="x Exit",
            font=("Helvetica", 11),
            width=10,
            height=2,
            bg='#21262d',
            fg='#c9d1d9',
            activebackground='#30363d',
            activeforeground='#c9d1d9',
            relief='flat',
            command=self.on_cancel
        ).pack(side=tk.LEFT, padx=5)
        
        # Bind enter key
        self.id_entry.bind('<Return>', lambda e: self.on_confirm() if self.confirm_btn['state'] == tk.NORMAL else None)
    
    def on_id_change(self, *args):
        """Handle ID input changes."""
        value = self.id_var.get().lower()
        
        # Filter to valid characters only
        filtered = ''.join(c for c in value if c in 'abcdefghijklmnopqrstuvwxyz0123456789')
        filtered = filtered[:ID_LENGTH]
        
        if filtered != value:
            self.id_var.set(filtered)
            return
        
        # Update counter
        length = len(filtered)
        self.counter_label.config(text=f"{length}/{ID_LENGTH}")
        
        # Update counter color
        if length == ID_LENGTH:
            self.counter_label.config(fg='#3fb950')
            self.confirm_btn.config(state=tk.NORMAL)
        else:
            self.counter_label.config(fg='#6e7681')
            self.confirm_btn.config(state=tk.DISABLED)
    
    def on_confirm(self):
        """Confirm the setup."""
        device_id = self.id_var.get().lower().strip()
        
        if DeviceConfig.validate_id(device_id):
            self.result = device_id
            self.dialog.destroy()
        else:
            messagebox.showerror(
                "Invalid ID",
                f"Please enter exactly {ID_LENGTH} characters (a-z, 0-9).",
                parent=self.dialog
            )
    
    def on_cancel(self):
        """Cancel setup (exit application)."""
        if messagebox.askyesno(
            "Exit Setup",
            "Device setup is required.\nExit the application?",
            parent=self.dialog
        ):
            self.result = None
            self.dialog.destroy()


# --- ADD CONTACT DIALOG ---

class AddContactDialog:
    """Dialog for adding a new contact."""
    
    def __init__(self, parent, device_id: str):
        self.result = None
        self.device_id = device_id
        
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Add Contact")
        self.dialog.geometry("400x300")
        self.dialog.resizable(False, False)
        self.dialog.configure(bg='#0d1117')
        
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        # Center
        self.dialog.update_idletasks()
        x = (self.dialog.winfo_screenwidth() - 400) // 2
        y = (self.dialog.winfo_screenheight() - 300) // 2
        self.dialog.geometry(f"+{x}+{y}")
        
        self.setup_ui()
    
    def setup_ui(self):
        # Header
        tk.Label(
            self.dialog,
            text="[@] Add New Contact",
            font=("Helvetica", 16, "bold"),
            fg='#c9d1d9',
            bg='#0d1117'
        ).pack(pady=(25, 20))
        
        # Contact ID input
        id_frame = tk.Frame(self.dialog, bg='#0d1117')
        id_frame.pack(fill=tk.X, padx=40, pady=10)
        
        tk.Label(
            id_frame,
            text="Contact ID:",
            font=("Helvetica", 11),
            fg='#c9d1d9',
            bg='#0d1117',
            anchor='w'
        ).pack(fill=tk.X)
        
        self.id_var = tk.StringVar()
        self.id_var.trace('w', self.on_id_change)
        
        self.id_entry = tk.Entry(
            id_frame,
            textvariable=self.id_var,
            font=("Consolas", 12),
            width=20
        )
        self.id_entry.pack(fill=tk.X, pady=(5, 0))
        self.id_entry.focus_set()
        
        self.id_hint = tk.Label(
            id_frame,
            text=f"0/{ID_LENGTH} characters",
            font=("Helvetica", 9),
            fg='#6e7681',
            bg='#0d1117',
            anchor='w'
        )
        self.id_hint.pack(fill=tk.X, pady=(2, 0))
        
        # Nickname input
        nick_frame = tk.Frame(self.dialog, bg='#0d1117')
        nick_frame.pack(fill=tk.X, padx=40, pady=10)
        
        tk.Label(
            nick_frame,
            text="Nickname (optional):",
            font=("Helvetica", 11),
            fg='#c9d1d9',
            bg='#0d1117',
            anchor='w'
        ).pack(fill=tk.X)
        
        self.nick_var = tk.StringVar()
        self.nick_entry = tk.Entry(
            nick_frame,
            textvariable=self.nick_var,
            font=("Helvetica", 12),
            width=20
        )
        self.nick_entry.pack(fill=tk.X, pady=(5, 0))
        
        # Buttons
        btn_frame = tk.Frame(self.dialog, bg='#0d1117')
        btn_frame.pack(pady=25)
        
        self.add_btn = tk.Button(
            btn_frame,
            text="+ Add Contact",
            font=("Helvetica", 11),
            width=12,
            bg='#238636',
            fg='white',
            activebackground='#2ea043',
            relief='flat',
            state=tk.DISABLED,
            command=self.on_add
        )
        self.add_btn.pack(side=tk.LEFT, padx=5)
        
        tk.Button(
            btn_frame,
            text="Cancel",
            font=("Helvetica", 11),
            width=10,
            bg='#21262d',
            fg='#c9d1d9',
            activebackground='#30363d',
            relief='flat',
            command=self.dialog.destroy
        ).pack(side=tk.LEFT, padx=5)
        
        self.id_entry.bind('<Return>', lambda e: self.on_add() if self.add_btn['state'] == tk.NORMAL else None)
    
    def on_id_change(self, *args):
        """Handle ID input changes."""
        value = self.id_var.get().lower()
        filtered = ''.join(c for c in value if c in 'abcdefghijklmnopqrstuvwxyz0123456789')
        filtered = filtered[:ID_LENGTH]
        
        if filtered != value:
            self.id_var.set(filtered)
            return
        
        length = len(filtered)
        
        if length == ID_LENGTH:
            if filtered == self.device_id:
                self.id_hint.config(text="Cannot add yourself!", fg='#f85149')
                self.add_btn.config(state=tk.DISABLED)
            else:
                self.id_hint.config(text=f"+ Valid ID", fg='#3fb950')
                self.add_btn.config(state=tk.NORMAL)
        else:
            self.id_hint.config(text=f"{length}/{ID_LENGTH} characters", fg='#6e7681')
            self.add_btn.config(state=tk.DISABLED)
    
    def on_add(self):
        """Add the contact."""
        contact_id = self.id_var.get().lower().strip()
        nickname = self.nick_var.get().strip() or contact_id
        
        if DeviceConfig.validate_id(contact_id):
            self.result = (contact_id, nickname)
            self.dialog.destroy()


# --- EDIT CONTACT DIALOG ---

class EditContactDialog:
    """Dialog for editing a contact."""
    
    def __init__(self, parent, contact_id: str, contact_data: dict):
        self.result = None
        self.contact_id = contact_id
        self.deleted = False
        
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Edit Contact")
        self.dialog.geometry("400x350")
        self.dialog.resizable(False, False)
        self.dialog.configure(bg='#0d1117')
        
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        # Center
        self.dialog.update_idletasks()
        x = (self.dialog.winfo_screenwidth() - 400) // 2
        y = (self.dialog.winfo_screenheight() - 350) // 2
        self.dialog.geometry(f"+{x}+{y}")
        
        self.contact_data = contact_data
        self.setup_ui()
    
    def setup_ui(self):
        # Header
        tk.Label(
            self.dialog,
            text="[E] Edit Contact",
            font=("Helvetica", 16, "bold"),
            fg='#c9d1d9',
            bg='#0d1117'
        ).pack(pady=(25, 10))
        
        # Contact ID (read-only)
        id_frame = tk.Frame(self.dialog, bg='#0d1117')
        id_frame.pack(fill=tk.X, padx=40, pady=10)
        
        tk.Label(
            id_frame,
            text="Contact ID:",
            font=("Helvetica", 10),
            fg='#8b949e',
            bg='#0d1117',
            anchor='w'
        ).pack(fill=tk.X)
        
        tk.Label(
            id_frame,
            text=self.contact_id,
            font=("Consolas", 12),
            fg='#58a6ff',
            bg='#0d1117',
            anchor='w'
        ).pack(fill=tk.X)
        
        # Nickname input
        nick_frame = tk.Frame(self.dialog, bg='#0d1117')
        nick_frame.pack(fill=tk.X, padx=40, pady=10)
        
        tk.Label(
            nick_frame,
            text="Nickname:",
            font=("Helvetica", 11),
            fg='#c9d1d9',
            bg='#0d1117',
            anchor='w'
        ).pack(fill=tk.X)
        
        self.nick_var = tk.StringVar(value=self.contact_data.get('nickname', ''))
        self.nick_entry = tk.Entry(
            nick_frame,
            textvariable=self.nick_var,
            font=("Helvetica", 12),
            width=20
        )
        self.nick_entry.pack(fill=tk.X, pady=(5, 0))
        self.nick_entry.focus_set()
        self.nick_entry.select_range(0, tk.END)
        
        # Notes input
        notes_frame = tk.Frame(self.dialog, bg='#0d1117')
        notes_frame.pack(fill=tk.X, padx=40, pady=10)
        
        tk.Label(
            notes_frame,
            text="Notes:",
            font=("Helvetica", 11),
            fg='#c9d1d9',
            bg='#0d1117',
            anchor='w'
        ).pack(fill=tk.X)
        
        self.notes_text = tk.Text(
            notes_frame,
            font=("Helvetica", 10),
            width=30,
            height=3
        )
        self.notes_text.pack(fill=tk.X, pady=(5, 0))
        self.notes_text.insert('1.0', self.contact_data.get('notes', ''))
        
        # Buttons
        btn_frame = tk.Frame(self.dialog, bg='#0d1117')
        btn_frame.pack(pady=20)
        
        tk.Button(
            btn_frame,
            text="+ Save",
            font=("Helvetica", 11),
            width=10,
            bg='#238636',
            fg='white',
            activebackground='#2ea043',
            relief='flat',
            command=self.on_save
        ).pack(side=tk.LEFT, padx=5)
        
        tk.Button(
            btn_frame,
            text="[X] Delete",
            font=("Helvetica", 11),
            width=10,
            bg='#da3633',
            fg='white',
            activebackground='#f85149',
            relief='flat',
            command=self.on_delete
        ).pack(side=tk.LEFT, padx=5)
        
        tk.Button(
            btn_frame,
            text="Cancel",
            font=("Helvetica", 11),
            width=10,
            bg='#21262d',
            fg='#c9d1d9',
            activebackground='#30363d',
            relief='flat',
            command=self.dialog.destroy
        ).pack(side=tk.LEFT, padx=5)
    
    def on_save(self):
        """Save changes."""
        nickname = self.nick_var.get().strip() or self.contact_id
        notes = self.notes_text.get('1.0', tk.END).strip()
        
        self.result = {
            'nickname': nickname,
            'notes': notes
        }
        self.dialog.destroy()
    
    def on_delete(self):
        """Delete the contact."""
        if messagebox.askyesno(
            "Delete Contact",
            f"Delete contact '{self.contact_data.get('nickname', self.contact_id)}'?",
            parent=self.dialog
        ):
            self.deleted = True
            self.dialog.destroy()


# --- MAIN APPLICATION ---

class ContactsApp:
    """Main Contacts Application - Communication Hub."""
    
    def __init__(self, master):
        self.master = master
        self.master.title("OTP Contacts")
        self.master.geometry("500x650")
        self.master.minsize(450, 550)
        self.master.configure(bg='#0d1117')
        
        # Initialize managers
        self.config = DeviceConfig()
        self.contacts = ContactsManager()
        
        self.selected_contact = None
        
        # Check if setup is needed
        if not self.config.setup_complete:
            self.run_setup()
        
        if self.config.setup_complete:
            self.setup_ui()
            self.refresh_contacts()
        else:
            # Setup was cancelled
            self.master.destroy()
    
    def run_setup(self):
        """Run the initial device setup."""
        dialog = DeviceSetupDialog(self.master)
        self.master.wait_window(dialog.dialog)
        
        if dialog.result:
            if self.config.set_device_id(dialog.result):
                messagebox.showinfo(
                    "Setup Complete",
                    f"Device ID set to:\n{dialog.result}\n\nThis device is now ready for use."
                )
            else:
                messagebox.showerror("Error", "Failed to save device configuration.")
    
    def setup_ui(self):
        """Build the main user interface."""
        # Header
        header_frame = tk.Frame(self.master, bg='#161b22', pady=15)
        header_frame.pack(fill=tk.X)
        
        tk.Label(
            header_frame,
            text="[C] Contacts",
            font=("Helvetica", 20, "bold"),
            fg='#c9d1d9',
            bg='#161b22'
        ).pack(side=tk.LEFT, padx=20)
        
        # Device ID display
        id_frame = tk.Frame(header_frame, bg='#161b22')
        id_frame.pack(side=tk.RIGHT, padx=20)
        
        tk.Label(
            id_frame,
            text="My ID:",
            font=("Helvetica", 9),
            fg='#8b949e',
            bg='#161b22'
        ).pack(side=tk.LEFT)
        
        self.my_id_label = tk.Label(
            id_frame,
            text=self.config.device_id,
            font=("Consolas", 10, "bold"),
            fg='#58a6ff',
            bg='#161b22',
            cursor='hand2'
        )
        self.my_id_label.pack(side=tk.LEFT, padx=(5, 0))
        self.my_id_label.bind('<Button-1>', self.copy_my_id)
        
        # Search/Add bar
        action_frame = tk.Frame(self.master, bg='#0d1117', pady=10)
        action_frame.pack(fill=tk.X, padx=15)
        
        # Search entry
        self.search_var = tk.StringVar()
        self.search_var.trace('w', self.on_search)
        
        search_entry = tk.Entry(
            action_frame,
            textvariable=self.search_var,
            font=("Helvetica", 11),
            bg='#21262d',
            fg='#c9d1d9',
            insertbackground='#c9d1d9',
            relief='flat',
            width=25
        )
        search_entry.pack(side=tk.LEFT, padx=(0, 10), ipady=8, ipadx=10)
        search_entry.insert(0, "")
        
        # Placeholder behavior
        def on_focus_in(e):
            if search_entry.get() == "":
                pass
        def on_focus_out(e):
            pass
        search_entry.bind('<FocusIn>', on_focus_in)
        search_entry.bind('<FocusOut>', on_focus_out)
        
        # Add contact button
        add_btn = tk.Button(
            action_frame,
            text="+ Add Contact",
            font=("Helvetica", 10),
            bg='#238636',
            fg='white',
            activebackground='#2ea043',
            activeforeground='white',
            relief='flat',
            padx=15,
            pady=8,
            cursor='hand2',
            command=self.add_contact
        )
        add_btn.pack(side=tk.RIGHT)
        
        # OTP Manager button
        manager_btn = tk.Button(
            action_frame,
            text="[K] OTP Manager",
            font=("Helvetica", 10),
            bg='#8957e5',
            fg='white',
            activebackground='#a371f7',
            activeforeground='white',
            relief='flat',
            padx=15,
            pady=8,
            cursor='hand2',
            command=self.open_otp_manager
        )
        manager_btn.pack(side=tk.RIGHT, padx=(0, 10))
        
        # Contacts list frame
        list_frame = tk.Frame(self.master, bg='#0d1117')
        list_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=(5, 10))
        
        # Contacts listbox with scrollbar
        self.contacts_canvas = tk.Canvas(
            list_frame,
            bg='#0d1117',
            highlightthickness=0
        )
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.contacts_canvas.yview)
        
        self.contacts_inner = tk.Frame(self.contacts_canvas, bg='#0d1117')
        
        self.contacts_canvas.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.contacts_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        self.canvas_window = self.contacts_canvas.create_window(
            (0, 0),
            window=self.contacts_inner,
            anchor='nw'
        )
        
        self.contacts_inner.bind('<Configure>', self.on_frame_configure)
        self.contacts_canvas.bind('<Configure>', self.on_canvas_configure)
        
        # Mouse wheel scrolling
        self.contacts_canvas.bind_all('<MouseWheel>', self.on_mousewheel)
        
        # Action panel (shown when contact selected)
        self.action_panel = tk.Frame(self.master, bg='#161b22', pady=15)
        
        self.selected_label = tk.Label(
            self.action_panel,
            text="",
            font=("Helvetica", 14, "bold"),
            fg='#c9d1d9',
            bg='#161b22'
        )
        self.selected_label.pack(pady=(0, 10))
        
        btn_row = tk.Frame(self.action_panel, bg='#161b22')
        btn_row.pack()
        
        # Message button
        self.msg_btn = tk.Button(
            btn_row,
            text="[M] Message",
            font=("Helvetica", 11),
            width=12,
            height=2,
            bg='#238636',
            fg='white',
            activebackground='#2ea043',
            relief='flat',
            cursor='hand2',
            command=self.message_contact
        )
        self.msg_btn.pack(side=tk.LEFT, padx=5)
        
        # Call button
        self.call_btn = tk.Button(
            btn_row,
            text="[V] Voice Call",
            font=("Helvetica", 11),
            width=12,
            height=2,
            bg='#8957e5',
            fg='white',
            activebackground='#a371f7',
            relief='flat',
            cursor='hand2',
            command=self.call_contact
        )
        self.call_btn.pack(side=tk.LEFT, padx=5)
        
        # Edit button
        self.edit_btn = tk.Button(
            btn_row,
            text="[E] Edit",
            font=("Helvetica", 11),
            width=10,
            height=2,
            bg='#21262d',
            fg='#c9d1d9',
            activebackground='#30363d',
            relief='flat',
            cursor='hand2',
            command=self.edit_contact
        )
        self.edit_btn.pack(side=tk.LEFT, padx=5)
        
        # Status bar
        self.status_bar = tk.Label(
            self.master,
            text="",
            font=("Helvetica", 9),
            fg='#6e7681',
            bg='#0d1117',
            anchor='w'
        )
        self.status_bar.pack(fill=tk.X, padx=15, pady=(0, 10))
    
    def on_frame_configure(self, event):
        """Update scrollregion when inner frame changes."""
        self.contacts_canvas.configure(scrollregion=self.contacts_canvas.bbox('all'))
    
    def on_canvas_configure(self, event):
        """Resize inner frame to canvas width."""
        self.contacts_canvas.itemconfig(self.canvas_window, width=event.width)
    
    def on_mousewheel(self, event):
        """Handle mouse wheel scrolling."""
        self.contacts_canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')
    
    def copy_my_id(self, event=None):
        """Copy device ID to clipboard."""
        self.master.clipboard_clear()
        self.master.clipboard_append(self.config.device_id)
        self.status_bar.config(text="+ Device ID copied to clipboard")
        self.master.after(2000, lambda: self.status_bar.config(text=""))
    
    def refresh_contacts(self):
        """Refresh the contacts list display."""
        # Clear existing
        for widget in self.contacts_inner.winfo_children():
            widget.destroy()
        
        contacts = self.contacts.get_all_contacts()
        search_term = self.search_var.get().lower()
        
        # Filter by search
        if search_term:
            contacts = [
                c for c in contacts
                if search_term in c['id'].lower() or search_term in c['nickname'].lower()
            ]
        
        if not contacts:
            empty_label = tk.Label(
                self.contacts_inner,
                text="No contacts found\n\nClick '+ Add Contact' to add one",
                font=("Helvetica", 11),
                fg='#6e7681',
                bg='#0d1117',
                justify=tk.CENTER
            )
            empty_label.pack(pady=50)
            self.action_panel.pack_forget()
            return
        
        # Create contact cards
        for contact in contacts:
            self.create_contact_card(contact)
        
        self.status_bar.config(text=f"{len(contacts)} contact(s)")
    
    def create_contact_card(self, contact: dict):
        """Create a contact card widget."""
        card = tk.Frame(
            self.contacts_inner,
            bg='#21262d',
            cursor='hand2'
        )
        card.pack(fill=tk.X, pady=3, ipady=10, ipadx=15)
        
        # Avatar/initial
        initial = contact['nickname'][0].upper() if contact['nickname'] else '?'
        avatar = tk.Label(
            card,
            text=initial,
            font=("Helvetica", 14, "bold"),
            fg='white',
            bg='#30363d',
            width=3,
            height=1
        )
        avatar.pack(side=tk.LEFT, padx=(10, 15), pady=5)
        
        # Info
        info_frame = tk.Frame(card, bg='#21262d')
        info_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        name_label = tk.Label(
            info_frame,
            text=contact['nickname'],
            font=("Helvetica", 12, "bold"),
            fg='#c9d1d9',
            bg='#21262d',
            anchor='w'
        )
        name_label.pack(fill=tk.X)
        
        id_label = tk.Label(
            info_frame,
            text=contact['id'],
            font=("Consolas", 9),
            fg='#8b949e',
            bg='#21262d',
            anchor='w'
        )
        id_label.pack(fill=tk.X)
        
        # Bind click events
        for widget in [card, avatar, info_frame, name_label, id_label]:
            widget.bind('<Button-1>', lambda e, c=contact: self.select_contact(c))
            widget.bind('<Enter>', lambda e, w=card: w.configure(bg='#30363d'))
            widget.bind('<Leave>', lambda e, w=card: w.configure(bg='#21262d'))
        
        # Update child backgrounds on hover
        def on_enter(e, card=card, info=info_frame, name=name_label, id_l=id_label):
            for w in [card, info, name, id_l]:
                w.configure(bg='#30363d')
        
        def on_leave(e, card=card, info=info_frame, name=name_label, id_l=id_label):
            for w in [card, info, name, id_l]:
                w.configure(bg='#21262d')
        
        card.bind('<Enter>', on_enter)
        card.bind('<Leave>', on_leave)
    
    def select_contact(self, contact: dict):
        """Select a contact and show action panel."""
        self.selected_contact = contact
        self.selected_label.config(text=f"{contact['nickname']}")
        self.action_panel.pack(fill=tk.X, before=self.status_bar)
    
    def on_search(self, *args):
        """Handle search input changes."""
        self.refresh_contacts()
    
    def add_contact(self):
        """Show add contact dialog."""
        dialog = AddContactDialog(self.master, self.config.device_id)
        self.master.wait_window(dialog.dialog)
        
        if dialog.result:
            contact_id, nickname = dialog.result
            success, message = self.contacts.add_contact(contact_id, nickname)
            
            if success:
                self.refresh_contacts()
                self.status_bar.config(text=f"+ Added contact: {nickname}")
            else:
                messagebox.showerror("Error", message)
    
    def edit_contact(self):
        """Show edit contact dialog."""
        if not self.selected_contact:
            return
        
        contact_id = self.selected_contact['id']
        contact_data = self.contacts.get_contact(contact_id)
        
        dialog = EditContactDialog(self.master, contact_id, contact_data)
        self.master.wait_window(dialog.dialog)
        
        if dialog.deleted:
            self.contacts.remove_contact(contact_id)
            self.selected_contact = None
            self.action_panel.pack_forget()
            self.refresh_contacts()
            self.status_bar.config(text="Contact deleted")
        elif dialog.result:
            self.contacts.update_nickname(contact_id, dialog.result['nickname'])
            self.contacts.update_notes(contact_id, dialog.result['notes'])
            self.refresh_contacts()
            self.status_bar.config(text="Contact updated")
    
    def message_contact(self):
        """Launch messenger with this contact."""
        if not self.selected_contact:
            return
        
        contact_id = self.selected_contact['id']
        contact_name = self.selected_contact['nickname']
        
        # Try v2 first (per-contact pads), fall back to v1
        client_v2_path = APP_DIR / "otp_client_v2.py"
        client_v1_path = APP_DIR / "otp_client.py"
        
        if client_v2_path.exists():
            self._launch_with_recipient("otp_client_v2.py", contact_id)
            self.status_bar.config(text=f"Opening messenger for {contact_name}...")
        elif client_v1_path.exists():
            self._launch_with_recipient("otp_client.py", contact_id)
            self.status_bar.config(text=f"Opening messenger for {contact_name}...")
        else:
            messagebox.showerror("Error", "otp_client.py not found!")
    
    def call_contact(self):
        """Launch voice client for this contact."""
        if not self.selected_contact:
            return
        
        contact_id = self.selected_contact['id']
        contact_name = self.selected_contact['nickname']
        
        # Find and launch otp_voice_client.py
        voice_path = APP_DIR / "otp_voice_client.py"
        
        if voice_path.exists():
            self._launch_with_recipient("otp_voice_client.py", contact_id)
            self.status_bar.config(text=f"Opening voice call for {contact_name}...")
        else:
            messagebox.showerror("Error", "otp_voice_client.py not found!")
    
    def _launch_with_recipient(self, app_name: str, recipient_id: str):
        """Launch an app with recipient information."""
        app_path = APP_DIR / app_name
        
        # Set environment variable for the recipient (apps can check this)
        env = os.environ.copy()
        env['OTP_RECIPIENT'] = recipient_id
        env['OTP_RECIPIENT_NAME'] = self.contacts.get_display_name(recipient_id)
        
        subprocess.Popen(
            [sys.executable, str(app_path)],
            cwd=str(APP_DIR),
            env=env
        )
    
    def open_otp_manager(self):
        """Launch OTP Manager for per-contact pad management."""
        manager_path = APP_DIR / "otp_manager.py"
        
        if manager_path.exists():
            subprocess.Popen(
                [sys.executable, str(manager_path)],
                cwd=str(APP_DIR)
            )
            self.status_bar.config(text="Opening OTP Manager...")
        else:
            messagebox.showerror("Error", "otp_manager.py not found!")


def main():
    root = tk.Tk()
    
    # Set dark theme for ttk
    style = ttk.Style()
    style.theme_use('clam')
    
    app = ContactsApp(root)
    
    # Only run mainloop if setup completed
    if hasattr(app, 'config') and app.config.setup_complete:
        root.mainloop()


if __name__ == "__main__":
    main()
