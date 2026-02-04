#!/usr/bin/env python3
"""
OTP Manager v2 - Per-Contact Cipher Pads
Each contact has their own completely separate cipher pad file.

Folder Structure:
    otp_data/
        contacts/
            <contact_id>/
                cipher.txt          # THE unique pad shared ONLY with this contact
                used_pages.txt      # Track which pages have been used
                info.json           # Metadata (created date, source, etc.)

Security Model:
    - Each contact relationship has a UNIQUE cipher pad
    - A pad shared with Alice is NEVER used with Bob
    - When you meet someone, you generate/share a pad specifically for them
    - That pad exists only on your device and theirs

Usage:
    python3 otp_manager.py
"""

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
import json
import os
import shutil
import string
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Tuple

# --- CONFIGURATION ---
APP_DIR = Path(__file__).parent.resolve()
OTP_DATA_DIR = APP_DIR / "otp_data"
CONTACTS_DIR = OTP_DATA_DIR / "contacts"
CONTACTS_FILE = APP_DIR / "contacts.json"
DEVICE_CONFIG_FILE = APP_DIR / "device_config.json"

# Legacy files for migration
LEGACY_OTP_FILE = APP_DIR / "otp_cipher.txt"
LEGACY_USED_FILE = APP_DIR / "used_pages.txt"

PAGE_ID_LENGTH = 8
DEFAULT_PAGE_LENGTH = 3500

# Hardware RNG (Raspberry Pi)
PI_HWRNG_DEVICE = "/dev/hwrng"


# --- PER-CONTACT PAD MANAGEMENT ---

class ContactPadManager:
    """Manages per-contact cipher pads."""
    
    def __init__(self):
        self.ensure_directories()
    
    def ensure_directories(self):
        """Create necessary directories."""
        OTP_DATA_DIR.mkdir(exist_ok=True)
        CONTACTS_DIR.mkdir(exist_ok=True)
    
    # --- Contact Directory Management ---
    
    def get_contact_dir(self, contact_id: str) -> Path:
        """Get directory for a contact's pad."""
        contact_dir = CONTACTS_DIR / contact_id
        contact_dir.mkdir(exist_ok=True)
        return contact_dir
    
    def get_cipher_file(self, contact_id: str) -> Path:
        """Get path to contact's cipher pad file."""
        return self.get_contact_dir(contact_id) / "cipher.txt"
    
    def get_used_file(self, contact_id: str) -> Path:
        """Get path to contact's used pages tracker."""
        return self.get_contact_dir(contact_id) / "used_pages.txt"
    
    def get_info_file(self, contact_id: str) -> Path:
        """Get path to contact's pad info/metadata."""
        return self.get_contact_dir(contact_id) / "info.json"
    
    # --- Pad Information ---
    
    def has_pad(self, contact_id: str) -> bool:
        """Check if a contact has a cipher pad."""
        cipher_file = self.get_cipher_file(contact_id)
        return cipher_file.exists() and cipher_file.stat().st_size > 0
    
    def get_pad_info(self, contact_id: str) -> Optional[dict]:
        """Get metadata about a contact's pad."""
        info_file = self.get_info_file(contact_id)
        if info_file.exists():
            try:
                with open(info_file, 'r') as f:
                    return json.load(f)
            except:
                pass
        return None
    
    def save_pad_info(self, contact_id: str, info: dict):
        """Save metadata about a contact's pad."""
        info_file = self.get_info_file(contact_id)
        with open(info_file, 'w') as f:
            json.dump(info, f, indent=2)
    
    def get_page_counts(self, contact_id: str) -> Tuple[int, int]:
        """Get (total, used) page counts for a contact."""
        cipher_file = self.get_cipher_file(contact_id)
        used_file = self.get_used_file(contact_id)
        
        total = 0
        used = 0
        
        if cipher_file.exists():
            with open(cipher_file, 'r') as f:
                total = sum(1 for line in f if len(line.strip()) > PAGE_ID_LENGTH)
        
        if used_file.exists():
            with open(used_file, 'r') as f:
                used = sum(1 for line in f if line.strip())
        
        return (total, used)
    
    def get_available_count(self, contact_id: str) -> int:
        """Get number of available (unused) pages for a contact."""
        total, used = self.get_page_counts(contact_id)
        return total - used
    
    # --- Page Operations ---
    
    def get_all_pages(self, contact_id: str) -> List[str]:
        """Get all pages from a contact's cipher pad."""
        cipher_file = self.get_cipher_file(contact_id)
        if not cipher_file.exists():
            return []
        
        with open(cipher_file, 'r') as f:
            return [line.rstrip('\n') for line in f if len(line.strip()) > PAGE_ID_LENGTH]
    
    def get_used_page_ids(self, contact_id: str) -> set:
        """Get set of used page IDs for a contact."""
        used_file = self.get_used_file(contact_id)
        if not used_file.exists():
            return set()
        
        with open(used_file, 'r') as f:
            return {line.strip().split('|')[0] for line in f if line.strip()}
    
    def get_next_available_page(self, contact_id: str) -> Optional[Tuple[str, str]]:
        """
        Get the next unused page for a contact.
        Returns (page_id, page_content) or None.
        Marks the page as used.
        """
        pages = self.get_all_pages(contact_id)
        used_ids = self.get_used_page_ids(contact_id)
        
        for page in pages:
            page_id = page[:PAGE_ID_LENGTH]
            if page_id not in used_ids:
                # Mark as used
                self._mark_page_used(contact_id, page_id)
                return (page_id, page[PAGE_ID_LENGTH:])
        
        return None
    
    def find_page_by_id(self, contact_id: str, page_id: str) -> Optional[str]:
        """
        Find a specific page by ID for decryption.
        If found in unused pages, marks it as used.
        Returns page content (without ID) or None.
        """
        pages = self.get_all_pages(contact_id)
        used_ids = self.get_used_page_ids(contact_id)
        
        for page in pages:
            if page[:PAGE_ID_LENGTH] == page_id:
                # Mark as used if not already
                if page_id not in used_ids:
                    self._mark_page_used(contact_id, page_id)
                return page[PAGE_ID_LENGTH:]
        
        return None
    
    def _mark_page_used(self, contact_id: str, page_id: str):
        """Mark a page as used."""
        used_file = self.get_used_file(contact_id)
        with open(used_file, 'a') as f:
            f.write(f"{page_id}|{datetime.now().isoformat()}\n")
    
    # --- Pad Generation ---
    
    def generate_pad_for_contact(self, contact_id: str, num_pages: int, 
                                  use_hwrng: bool = True) -> Tuple[bool, str]:
        """
        Generate a new cipher pad for a contact.
        
        Args:
            contact_id: The contact's ID
            num_pages: Number of pages to generate
            use_hwrng: Use hardware RNG if available
            
        Returns:
            (success, message)
        """
        cipher_file = self.get_cipher_file(contact_id)
        
        # Check if pad already exists
        if cipher_file.exists() and cipher_file.stat().st_size > 0:
            return False, "Contact already has a cipher pad. Delete it first to generate a new one."
        
        try:
            pages = self._generate_pages(num_pages, use_hwrng)
            
            # Write to cipher file
            with open(cipher_file, 'w') as f:
                for page in pages:
                    f.write(page + '\n')
            
            # Clear any used pages tracker
            used_file = self.get_used_file(contact_id)
            if used_file.exists():
                used_file.unlink()
            
            # Save metadata
            self.save_pad_info(contact_id, {
                'created': datetime.now().isoformat(),
                'source': 'generated',
                'num_pages': num_pages,
                'hwrng_used': use_hwrng and os.path.exists(PI_HWRNG_DEVICE),
                'page_length': DEFAULT_PAGE_LENGTH
            })
            
            return True, f"Generated {num_pages} pages for contact"
            
        except Exception as e:
            return False, f"Generation failed: {e}"
    
    def _generate_pages(self, num_pages: int, use_hwrng: bool = True) -> List[str]:
        """Generate random OTP pages."""
        chars = string.ascii_uppercase + string.digits + string.punctuation
        charset_len = len(chars)  # 68
        pages = []
        
        # Try hardware RNG first
        if use_hwrng and os.path.exists(PI_HWRNG_DEVICE):
            try:
                pages = self._generate_hwrng_pages(num_pages, chars, charset_len)
                return pages
            except Exception as e:
                print(f"HWRNG failed, falling back to urandom: {e}")
        
        # Fallback to /dev/urandom
        pages = self._generate_urandom_pages(num_pages, chars, charset_len)
        return pages
    
    def _generate_hwrng_pages(self, num_pages: int, chars: str, charset_len: int) -> List[str]:
        """Generate pages using hardware RNG."""
        limit = (256 // charset_len) * charset_len  # Rejection sampling limit
        pages = []
        
        with open(PI_HWRNG_DEVICE, 'rb') as rng:
            for _ in range(num_pages):
                page_chars = []
                while len(page_chars) < DEFAULT_PAGE_LENGTH:
                    raw_bytes = rng.read((DEFAULT_PAGE_LENGTH - len(page_chars)) * 4)
                    for byte in raw_bytes:
                        if byte < limit:
                            page_chars.append(chars[byte % charset_len])
                            if len(page_chars) >= DEFAULT_PAGE_LENGTH:
                                break
                pages.append(''.join(page_chars))
        
        return pages
    
    def _generate_urandom_pages(self, num_pages: int, chars: str, charset_len: int) -> List[str]:
        """Generate pages using /dev/urandom."""
        import secrets
        pages = []
        
        for _ in range(num_pages):
            page = ''.join(secrets.choice(chars) for _ in range(DEFAULT_PAGE_LENGTH))
            pages.append(page)
        
        return pages
    
    # --- Pad Import/Export ---
    
    def import_pad_for_contact(self, contact_id: str, pages: List[str], 
                                source: str = "bluetooth") -> Tuple[bool, str]:
        """
        Import a cipher pad for a contact (e.g., received via Bluetooth).
        
        Args:
            contact_id: The contact's ID
            pages: List of page strings
            source: Where the pad came from
            
        Returns:
            (success, message)
        """
        cipher_file = self.get_cipher_file(contact_id)
        
        # Check if pad already exists
        if cipher_file.exists() and cipher_file.stat().st_size > 0:
            return False, "Contact already has a cipher pad. Delete it first to import."
        
        try:
            # Write pages
            with open(cipher_file, 'w') as f:
                for page in pages:
                    f.write(page + '\n')
            
            # Clear used pages
            used_file = self.get_used_file(contact_id)
            if used_file.exists():
                used_file.unlink()
            
            # Save metadata
            self.save_pad_info(contact_id, {
                'created': datetime.now().isoformat(),
                'source': source,
                'num_pages': len(pages),
                'imported': True
            })
            
            return True, f"Imported {len(pages)} pages for contact"
            
        except Exception as e:
            return False, f"Import failed: {e}"
    
    def export_pad(self, contact_id: str) -> Optional[List[str]]:
        """Export a contact's cipher pad (for Bluetooth sharing)."""
        if not self.has_pad(contact_id):
            return None
        return self.get_all_pages(contact_id)
    
    # --- Pad Deletion ---
    
    def delete_pad(self, contact_id: str) -> bool:
        """Delete a contact's cipher pad entirely."""
        contact_dir = self.get_contact_dir(contact_id)
        
        if contact_dir.exists():
            shutil.rmtree(contact_dir)
            return True
        return False
    
    def delete_used_pages(self, contact_id: str) -> int:
        """
        Delete used pages from a contact's pad to save space.
        Returns number of pages removed.
        """
        used_ids = self.get_used_page_ids(contact_id)
        if not used_ids:
            return 0
        
        pages = self.get_all_pages(contact_id)
        remaining = [p for p in pages if p[:PAGE_ID_LENGTH] not in used_ids]
        removed = len(pages) - len(remaining)
        
        # Rewrite cipher file
        cipher_file = self.get_cipher_file(contact_id)
        with open(cipher_file, 'w') as f:
            for page in remaining:
                f.write(page + '\n')
        
        # Clear used tracker
        used_file = self.get_used_file(contact_id)
        if used_file.exists():
            used_file.unlink()
        
        return removed
    
    # --- Statistics ---
    
    def get_all_contacts_with_pads(self) -> List[str]:
        """Get list of contact IDs that have pads."""
        if not CONTACTS_DIR.exists():
            return []
        
        contacts = []
        for item in CONTACTS_DIR.iterdir():
            if item.is_dir() and (item / "cipher.txt").exists():
                contacts.append(item.name)
        return sorted(contacts)
    
    def get_statistics(self) -> dict:
        """Get overall statistics."""
        contacts = self.get_all_contacts_with_pads()
        
        total_pages = 0
        total_used = 0
        contact_stats = {}
        
        for contact_id in contacts:
            total, used = self.get_page_counts(contact_id)
            total_pages += total
            total_used += used
            contact_stats[contact_id] = {
                'total': total,
                'used': used,
                'available': total - used
            }
        
        return {
            'num_contacts': len(contacts),
            'total_pages': total_pages,
            'total_used': total_used,
            'total_available': total_pages - total_used,
            'contacts': contact_stats
        }


# --- CONTACTS HELPER ---

def load_contacts() -> dict:
    """Load contacts from contacts.json."""
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


def load_device_id() -> Optional[str]:
    """Load this device's ID."""
    if DEVICE_CONFIG_FILE.exists():
        try:
            with open(DEVICE_CONFIG_FILE, 'r') as f:
                return json.load(f).get('device_id')
        except:
            pass
    return None


# --- GUI APPLICATION ---

class OTPManagerApp:
    """GUI application for managing per-contact cipher pads."""
    
    def __init__(self, master):
        self.master = master
        self.master.title("OTP Manager - Per-Contact Pads")
        self.master.geometry("950x700")
        self.master.minsize(850, 600)
        self.master.configure(bg='#0d1117')
        
        self.manager = ContactPadManager()
        self.contacts = load_contacts()
        self.selected_contact = None
        
        self.setup_ui()
        self.refresh_all()
    
    def setup_ui(self):
        """Build the user interface."""
        main = tk.Frame(self.master, bg='#0d1117')
        main.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)
        
        # --- Header ---
        header = tk.Frame(main, bg='#0d1117')
        header.pack(fill=tk.X, pady=(0, 15))
        
        tk.Label(
            header,
            text="[K] OTP Manager",
            font=("Helvetica", 24, "bold"),
            fg='#c9d1d9',
            bg='#0d1117'
        ).pack(side=tk.LEFT)
        
        tk.Label(
            header,
            text="Per-Contact Cipher Pads",
            font=("Helvetica", 12),
            fg='#8b949e',
            bg='#0d1117'
        ).pack(side=tk.LEFT, padx=(15, 0))
        
        self.stats_label = tk.Label(
            header,
            text="",
            font=("Consolas", 10),
            fg='#8b949e',
            bg='#0d1117'
        )
        self.stats_label.pack(side=tk.RIGHT)
        
        # --- Info Banner ---
        info_frame = tk.Frame(main, bg='#1c2128')
        info_frame.pack(fill=tk.X, pady=(0, 15))
        
        tk.Label(
            info_frame,
            text="[i] Each contact has their own unique cipher pad. "
                 "A pad shared with Alice is NEVER used with Bob.",
            font=("Helvetica", 10),
            fg='#58a6ff',
            bg='#1c2128',
            padx=15,
            pady=10
        ).pack(fill=tk.X)
        
        # --- Main Content ---
        content = tk.Frame(main, bg='#0d1117')
        content.pack(fill=tk.BOTH, expand=True)
        
        # Left panel - Contacts list
        left_panel = tk.Frame(content, bg='#161b22', width=300)
        left_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        left_panel.pack_propagate(False)
        
        self.setup_left_panel(left_panel)
        
        # Right panel - Pad details
        right_panel = tk.Frame(content, bg='#161b22')
        right_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        self.setup_right_panel(right_panel)
    
    def setup_left_panel(self, parent):
        """Setup the contacts list panel."""
        # Header
        header = tk.Frame(parent, bg='#161b22')
        header.pack(fill=tk.X, padx=10, pady=10)
        
        tk.Label(
            header,
            text="[U] Contacts with Pads",
            font=("Helvetica", 12, "bold"),
            fg='#c9d1d9',
            bg='#161b22'
        ).pack(side=tk.LEFT)
        
        # Contacts list
        self.contacts_listbox = tk.Listbox(
            parent,
            font=("Helvetica", 11),
            bg='#0d1117',
            fg='#c9d1d9',
            selectbackground='#1f6feb',
            selectforeground='white',
            relief='flat',
            highlightthickness=1,
            highlightcolor='#30363d',
            highlightbackground='#21262d',
            activestyle='none'
        )
        self.contacts_listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        self.contacts_listbox.bind('<<ListboxSelect>>', self.on_contact_select)
        
        # Buttons
        btn_frame = tk.Frame(parent, bg='#161b22')
        btn_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        tk.Button(
            btn_frame,
            text="[N] New Pad for Contact",
            command=self.new_pad_dialog,
            font=("Helvetica", 10),
            bg='#238636',
            fg='white',
            activebackground='#2ea043',
            activeforeground='white',
            relief='flat',
            cursor='hand2',
            pady=8
        ).pack(fill=tk.X, pady=(0, 5))
        
        tk.Button(
            btn_frame,
            text="[B] Bluetooth Share",
            command=self.open_bluetooth,
            font=("Helvetica", 10),
            bg='#1f6feb',
            fg='white',
            activebackground='#388bfd',
            activeforeground='white',
            relief='flat',
            cursor='hand2',
            pady=8
        ).pack(fill=tk.X)
    
    def setup_right_panel(self, parent):
        """Setup the pad details panel."""
        # Header
        self.detail_header = tk.Frame(parent, bg='#161b22')
        self.detail_header.pack(fill=tk.X, padx=15, pady=15)
        
        self.detail_title = tk.Label(
            self.detail_header,
            text="Select a contact to view their pad",
            font=("Helvetica", 16, "bold"),
            fg='#c9d1d9',
            bg='#161b22'
        )
        self.detail_title.pack(side=tk.LEFT)
        
        # Pad info frame
        self.info_frame = tk.Frame(parent, bg='#0d1117')
        self.info_frame.pack(fill=tk.X, padx=15, pady=(0, 15))
        
        # Stats row
        self.stats_frame = tk.Frame(self.info_frame, bg='#0d1117')
        self.stats_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.pages_total_label = tk.Label(
            self.stats_frame,
            text="",
            font=("Consolas", 12),
            fg='#c9d1d9',
            bg='#0d1117'
        )
        self.pages_total_label.pack(side=tk.LEFT, padx=(0, 20))
        
        self.pages_used_label = tk.Label(
            self.stats_frame,
            text="",
            font=("Consolas", 12),
            fg='#f85149',
            bg='#0d1117'
        )
        self.pages_used_label.pack(side=tk.LEFT, padx=(0, 20))
        
        self.pages_avail_label = tk.Label(
            self.stats_frame,
            text="",
            font=("Consolas", 12),
            fg='#3fb950',
            bg='#0d1117'
        )
        self.pages_avail_label.pack(side=tk.LEFT)
        
        # Metadata
        self.meta_label = tk.Label(
            self.info_frame,
            text="",
            font=("Helvetica", 10),
            fg='#8b949e',
            bg='#0d1117'
        )
        self.meta_label.pack(anchor='w')
        
        # Pages preview
        preview_frame = tk.LabelFrame(
            parent,
            text="Pages Preview",
            font=("Helvetica", 10, "bold"),
            fg='#8b949e',
            bg='#161b22',
            padx=10,
            pady=10
        )
        preview_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 15))
        
        # Treeview for pages
        columns = ('status', 'page_id', 'preview', 'hash')
        self.pages_tree = ttk.Treeview(
            preview_frame,
            columns=columns,
            show='headings',
            selectmode='extended'
        )
        
        self.pages_tree.heading('status', text='Status')
        self.pages_tree.heading('page_id', text='Page ID')
        self.pages_tree.heading('preview', text='Preview')
        self.pages_tree.heading('hash', text='Hash')
        
        self.pages_tree.column('status', width=80, minwidth=60)
        self.pages_tree.column('page_id', width=100, minwidth=80)
        self.pages_tree.column('preview', width=300, minwidth=200)
        self.pages_tree.column('hash', width=120, minwidth=100)
        
        scrollbar = ttk.Scrollbar(preview_frame, orient=tk.VERTICAL, command=self.pages_tree.yview)
        self.pages_tree.configure(yscrollcommand=scrollbar.set)
        
        self.pages_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Style treeview
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('Treeview',
                       background='#0d1117',
                       foreground='#c9d1d9',
                       fieldbackground='#0d1117',
                       rowheight=28)
        style.configure('Treeview.Heading',
                       background='#21262d',
                       foreground='#c9d1d9',
                       relief='flat')
        style.map('Treeview', background=[('selected', '#1f6feb')])
        
        # Action buttons
        actions = tk.Frame(parent, bg='#161b22')
        actions.pack(fill=tk.X, padx=15, pady=(0, 15))
        
        self.generate_btn = tk.Button(
            actions,
            text="[G] Generate New Pad",
            command=self.generate_pad,
            font=("Helvetica", 10),
            bg='#238636',
            fg='white',
            activebackground='#2ea043',
            activeforeground='white',
            relief='flat',
            padx=15,
            pady=8,
            cursor='hand2',
            state=tk.DISABLED
        )
        self.generate_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        self.cleanup_btn = tk.Button(
            actions,
            text="[D] Remove Used Pages",
            command=self.cleanup_used,
            font=("Helvetica", 10),
            bg='#d29922',
            fg='white',
            activebackground='#bb8009',
            activeforeground='white',
            relief='flat',
            padx=15,
            pady=8,
            cursor='hand2',
            state=tk.DISABLED
        )
        self.cleanup_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        self.delete_btn = tk.Button(
            actions,
            text="[X] Delete Entire Pad",
            command=self.delete_pad,
            font=("Helvetica", 10),
            bg='#f85149',
            fg='white',
            activebackground='#da3633',
            activeforeground='white',
            relief='flat',
            padx=15,
            pady=8,
            cursor='hand2',
            state=tk.DISABLED
        )
        self.delete_btn.pack(side=tk.LEFT)
    
    def refresh_all(self):
        """Refresh all displays."""
        self.refresh_stats()
        self.refresh_contacts_list()
        self.refresh_pad_details()
    
    def refresh_stats(self):
        """Refresh overall statistics."""
        stats = self.manager.get_statistics()
        self.stats_label.config(
            text=f"Contacts: {stats['num_contacts']} | "
                 f"Total Pages: {stats['total_pages']:,} | "
                 f"Available: {stats['total_available']:,}"
        )
    
    def refresh_contacts_list(self):
        """Refresh the contacts list."""
        self.contacts_listbox.delete(0, tk.END)
        
        contacts_with_pads = self.manager.get_all_contacts_with_pads()
        
        for contact_id in contacts_with_pads:
            total, used = self.manager.get_page_counts(contact_id)
            available = total - used
            name = get_contact_name(contact_id, self.contacts)
            
            status = "[ok]" if available > 0 else "[!]"
            display = f"{status} {name} ({available}/{total})"
            self.contacts_listbox.insert(tk.END, display)
    
    def refresh_pad_details(self):
        """Refresh the pad details panel."""
        # Clear tree
        for item in self.pages_tree.get_children():
            self.pages_tree.delete(item)
        
        if not self.selected_contact:
            self.detail_title.config(text="Select a contact to view their pad")
            self.pages_total_label.config(text="")
            self.pages_used_label.config(text="")
            self.pages_avail_label.config(text="")
            self.meta_label.config(text="")
            self.generate_btn.config(state=tk.DISABLED)
            self.cleanup_btn.config(state=tk.DISABLED)
            self.delete_btn.config(state=tk.DISABLED)
            return
        
        contact_id = self.selected_contact
        name = get_contact_name(contact_id, self.contacts)
        
        self.detail_title.config(text=f"[O] {name}'s Cipher Pad")
        
        if not self.manager.has_pad(contact_id):
            self.pages_total_label.config(text="No pad exists")
            self.pages_used_label.config(text="")
            self.pages_avail_label.config(text="")
            self.meta_label.config(text="Generate a new pad or receive one via Bluetooth")
            self.generate_btn.config(state=tk.NORMAL)
            self.cleanup_btn.config(state=tk.DISABLED)
            self.delete_btn.config(state=tk.DISABLED)
            return
        
        # Show stats
        total, used = self.manager.get_page_counts(contact_id)
        available = total - used
        
        self.pages_total_label.config(text=f"Total: {total:,}")
        self.pages_used_label.config(text=f"Used: {used:,}")
        self.pages_avail_label.config(text=f"Available: {available:,}")
        
        # Show metadata
        info = self.manager.get_pad_info(contact_id)
        if info:
            created = info.get('created', 'Unknown')[:10]
            source = info.get('source', 'Unknown')
            hwrng = "[ok] HWRNG" if info.get('hwrng_used') else "urandom"
            self.meta_label.config(text=f"Created: {created} | Source: {source} | RNG: {hwrng}")
        else:
            self.meta_label.config(text="")
        
        # Enable buttons
        self.generate_btn.config(state=tk.DISABLED)  # Can't generate if pad exists
        self.cleanup_btn.config(state=tk.NORMAL if used > 0 else tk.DISABLED)
        self.delete_btn.config(state=tk.NORMAL)
        
        # Populate pages tree (show first 100)
        pages = self.manager.get_all_pages(contact_id)
        used_ids = self.manager.get_used_page_ids(contact_id)
        
        for i, page in enumerate(pages[:100]):
            page_id = page[:PAGE_ID_LENGTH]
            content = page[PAGE_ID_LENGTH:]
            preview = content[:35] + "..." if len(content) > 35 else content
            page_hash = hashlib.sha256(page.encode()).hexdigest()[:10]
            
            status = "[X] Used" if page_id in used_ids else "[O] Available"
            
            self.pages_tree.insert('', tk.END, values=(status, page_id, preview, page_hash))
        
        if len(pages) > 100:
            self.pages_tree.insert('', tk.END, values=('...', f'+{len(pages)-100} more', '', ''))
    
    def on_contact_select(self, event):
        """Handle contact selection."""
        selection = self.contacts_listbox.curselection()
        if not selection:
            return
        
        idx = selection[0]
        contacts = self.manager.get_all_contacts_with_pads()
        
        if idx < len(contacts):
            self.selected_contact = contacts[idx]
            self.refresh_pad_details()
    
    def new_pad_dialog(self):
        """Show dialog to create a new pad for a contact."""
        # Get list of contacts without pads
        all_contacts = list(self.contacts.keys())
        contacts_with_pads = set(self.manager.get_all_contacts_with_pads())
        contacts_without_pads = [c for c in all_contacts if c not in contacts_with_pads]
        
        if not contacts_without_pads and not all_contacts:
            messagebox.showinfo(
                "No Contacts",
                "No contacts found. Add contacts first using the Contacts app."
            )
            return
        
        # Dialog
        dialog = tk.Toplevel(self.master)
        dialog.title("Generate New Pad")
        dialog.geometry("450x350")
        dialog.resizable(False, False)
        dialog.configure(bg='#0d1117')
        dialog.transient(self.master)
        dialog.grab_set()
        
        # Center
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() - 450) // 2
        y = (dialog.winfo_screenheight() - 350) // 2
        dialog.geometry(f"+{x}+{y}")
        
        # Content
        tk.Label(
            dialog,
            text="Generate New Cipher Pad",
            font=("Helvetica", 14, "bold"),
            fg='#c9d1d9',
            bg='#0d1117'
        ).pack(pady=(20, 10))
        
        tk.Label(
            dialog,
            text="This will create a unique pad for one contact.\n"
                 "Share this pad via Bluetooth when you meet them.",
            font=("Helvetica", 10),
            fg='#8b949e',
            bg='#0d1117'
        ).pack(pady=(0, 20))
        
        # Contact selection
        contact_frame = tk.Frame(dialog, bg='#0d1117')
        contact_frame.pack(fill=tk.X, padx=30, pady=(0, 15))
        
        tk.Label(
            contact_frame,
            text="Contact:",
            font=("Helvetica", 11),
            fg='#c9d1d9',
            bg='#0d1117'
        ).pack(anchor='w')
        
        contact_var = tk.StringVar()
        
        # Show all contacts but warn about existing pads
        contact_options = [
            f"{get_contact_name(cid, self.contacts)} ({cid})" + 
            (" [!] has pad" if cid in contacts_with_pads else "")
            for cid in all_contacts
        ]
        
        if contact_options:
            contact_combo = ttk.Combobox(
                contact_frame,
                textvariable=contact_var,
                values=contact_options,
                state='readonly',
                width=40
            )
            contact_combo.pack(fill=tk.X, pady=(5, 0))
            if contacts_without_pads:
                # Select first contact without pad
                for i, cid in enumerate(all_contacts):
                    if cid not in contacts_with_pads:
                        contact_combo.current(i)
                        break
            else:
                contact_combo.current(0)
        else:
            tk.Label(
                contact_frame,
                text="No contacts available",
                font=("Helvetica", 10),
                fg='#f85149',
                bg='#0d1117'
            ).pack(anchor='w')
            return
        
        # Number of pages
        num_frame = tk.Frame(dialog, bg='#0d1117')
        num_frame.pack(fill=tk.X, padx=30, pady=(0, 15))
        
        tk.Label(
            num_frame,
            text="Number of pages:",
            font=("Helvetica", 11),
            fg='#c9d1d9',
            bg='#0d1117'
        ).pack(anchor='w')
        
        num_var = tk.StringVar(value="1000")
        tk.Entry(
            num_frame,
            textvariable=num_var,
            font=("Consolas", 11),
            bg='#161b22',
            fg='#c9d1d9',
            insertbackground='#c9d1d9',
            relief='flat',
            width=15
        ).pack(anchor='w', pady=(5, 0))
        
        tk.Label(
            num_frame,
            text="Recommended: 1000+ pages per contact",
            font=("Helvetica", 9),
            fg='#8b949e',
            bg='#0d1117'
        ).pack(anchor='w', pady=(5, 0))
        
        # Buttons
        btn_frame = tk.Frame(dialog, bg='#0d1117')
        btn_frame.pack(pady=20)
        
        def do_generate():
            try:
                num = int(num_var.get())
                if num <= 0:
                    raise ValueError()
            except ValueError:
                messagebox.showerror("Error", "Please enter a valid number")
                return
            
            # Extract contact ID
            selection = contact_var.get()
            contact_id = selection.split('(')[-1].rstrip(')').replace(' [!] has pad', '')
            
            # Check if already has pad
            if self.manager.has_pad(contact_id):
                if not messagebox.askyesno(
                    "Pad Exists",
                    f"{get_contact_name(contact_id, self.contacts)} already has a pad.\n\n"
                    "Delete existing pad and generate new one?"
                ):
                    return
                self.manager.delete_pad(contact_id)
            
            # Generate
            dialog.config(cursor='wait')
            dialog.update()
            
            success, message = self.manager.generate_pad_for_contact(contact_id, num)
            
            dialog.config(cursor='')
            
            if success:
                messagebox.showinfo("Success", message)
                dialog.destroy()
                self.selected_contact = contact_id
                self.refresh_all()
            else:
                messagebox.showerror("Error", message)
        
        tk.Button(
            btn_frame,
            text="Generate",
            command=do_generate,
            font=("Helvetica", 11),
            bg='#238636',
            fg='white',
            activebackground='#2ea043',
            activeforeground='white',
            relief='flat',
            padx=20,
            pady=8,
            cursor='hand2'
        ).pack(side=tk.LEFT, padx=5)
        
        tk.Button(
            btn_frame,
            text="Cancel",
            command=dialog.destroy,
            font=("Helvetica", 11),
            bg='#21262d',
            fg='#c9d1d9',
            activebackground='#30363d',
            activeforeground='#c9d1d9',
            relief='flat',
            padx=20,
            pady=8,
            cursor='hand2'
        ).pack(side=tk.LEFT, padx=5)
    
    def generate_pad(self):
        """Generate new pad for selected contact."""
        if not self.selected_contact:
            return
        
        # This button is only enabled when contact has no pad
        self.new_pad_dialog()
    
    def cleanup_used(self):
        """Remove used pages from selected contact's pad."""
        if not self.selected_contact:
            return
        
        total, used = self.manager.get_page_counts(self.selected_contact)
        
        if used == 0:
            messagebox.showinfo("Info", "No used pages to remove.")
            return
        
        if not messagebox.askyesno(
            "Confirm Cleanup",
            f"Remove {used} used pages from this pad?\n\n"
            "This will free up disk space but the pages cannot be recovered."
        ):
            return
        
        removed = self.manager.delete_used_pages(self.selected_contact)
        messagebox.showinfo("Success", f"Removed {removed} used pages.")
        self.refresh_all()
    
    def delete_pad(self):
        """Delete the entire pad for selected contact."""
        if not self.selected_contact:
            return
        
        name = get_contact_name(self.selected_contact, self.contacts)
        
        if not messagebox.askyesno(
            "Confirm Delete",
            f"Delete the ENTIRE cipher pad for {name}?\n\n"
            "[!] This cannot be undone!\n"
            "[!] You will not be able to communicate with {name} until you share a new pad!"
        ):
            return
        
        self.manager.delete_pad(self.selected_contact)
        self.selected_contact = None
        self.refresh_all()
        messagebox.showinfo("Deleted", f"Cipher pad for {name} has been deleted.")
    
    def open_bluetooth(self):
        """Open Bluetooth sharing app."""
        import subprocess
        import sys
        
        bt_path = APP_DIR / "otp_bluetooth_share.py"
        if bt_path.exists():
            subprocess.Popen([sys.executable, str(bt_path)], cwd=str(APP_DIR))
        else:
            messagebox.showerror("Error", "otp_bluetooth_share.py not found!")


# --- MAIN ---

def main():
    root = tk.Tk()
    app = OTPManagerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
