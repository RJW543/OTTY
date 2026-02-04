#!/usr/bin/env python3
"""
OTP Helper - Per-Contact Cipher Pad Integration
Helper module for integrating per-contact OTP encryption with messaging clients.

IMPORTANT: Each contact has their own UNIQUE, SEPARATE cipher pad.
A pad shared with Alice is NEVER used with Bob.

Folder Structure:
    otp_data/
        contacts/
            <contact_id>/
                cipher.txt          # THE unique pad for this contact
                used_pages.txt      # Track which pages have been used

Usage:
    from otp_helper import OTPHelper
    
    helper = OTPHelper()
    
    # Check if contact has a pad
    if helper.contact_has_pad("alice123"):
        # Get a page to encrypt a message
        page_id, content = helper.get_page_for_contact("alice123")
        encrypted = xor_encrypt(message, content)
    
    # Decrypt a received message
    content = helper.find_page_for_decryption("ABCD1234", "alice123")
    decrypted = xor_decrypt(encrypted, content)
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, List

# --- CONFIGURATION ---
APP_DIR = Path(__file__).parent.resolve()
OTP_DATA_DIR = APP_DIR / "otp_data"
CONTACTS_DIR = OTP_DATA_DIR / "contacts"
CONTACTS_FILE = APP_DIR / "contacts.json"

PAGE_ID_LENGTH = 8


class OTPHelper:
    """Helper class for per-contact cipher pad operations."""
    
    def __init__(self):
        self._ensure_directories()
    
    def _ensure_directories(self):
        """Create directories if needed."""
        OTP_DATA_DIR.mkdir(exist_ok=True)
        CONTACTS_DIR.mkdir(exist_ok=True)
    
    def _get_contact_dir(self, contact_id: str) -> Path:
        """Get directory for a contact."""
        return CONTACTS_DIR / contact_id
    
    def _get_cipher_file(self, contact_id: str) -> Path:
        """Get path to contact's cipher pad."""
        return self._get_contact_dir(contact_id) / "cipher.txt"
    
    def _get_used_file(self, contact_id: str) -> Path:
        """Get path to contact's used pages tracker."""
        return self._get_contact_dir(contact_id) / "used_pages.txt"
    
    # --- Contact Pad Operations ---
    
    def contact_has_pad(self, contact_id: str) -> bool:
        """Check if contact has a cipher pad."""
        cipher_file = self._get_cipher_file(contact_id)
        return cipher_file.exists() and cipher_file.stat().st_size > 0
    
    def get_pad_pages(self, contact_id: str) -> List[str]:
        """Get all pages from contact's cipher pad."""
        cipher_file = self._get_cipher_file(contact_id)
        if not cipher_file.exists():
            return []
        
        with open(cipher_file, 'r', encoding='utf-8') as f:
            return [line.rstrip('\n') for line in f if len(line.strip()) > PAGE_ID_LENGTH]
    
    def get_used_page_ids(self, contact_id: str) -> set:
        """Get set of used page IDs for contact."""
        used_file = self._get_used_file(contact_id)
        if not used_file.exists():
            return set()
        
        with open(used_file, 'r', encoding='utf-8') as f:
            return {line.strip().split('|')[0] for line in f if line.strip()}
    
    def get_available_count(self, contact_id: str) -> int:
        """Get count of available (unused) pages for contact."""
        all_pages = self.get_pad_pages(contact_id)
        used_ids = self.get_used_page_ids(contact_id)
        return len([p for p in all_pages if p[:PAGE_ID_LENGTH] not in used_ids])
    
    def get_page_counts(self, contact_id: str) -> Tuple[int, int, int]:
        """Get (total, available, used) page counts for contact."""
        all_pages = self.get_pad_pages(contact_id)
        used_ids = self.get_used_page_ids(contact_id)
        
        total = len(all_pages)
        used = len(used_ids)
        available = total - used
        
        return (total, available, used)
    
    def get_page_for_contact(self, contact_id: str) -> Optional[Tuple[str, str]]:
        """
        Get the next available page for encrypting a message to this contact.
        The page is automatically marked as used.
        
        IMPORTANT: This page comes from the contact's dedicated cipher pad,
        which is unique to your relationship with them.
        
        Returns:
            (page_id, page_content) or None if no pages available
        """
        all_pages = self.get_pad_pages(contact_id)
        used_ids = self.get_used_page_ids(contact_id)
        
        # Find first unused page
        for page in all_pages:
            page_id = page[:PAGE_ID_LENGTH]
            if page_id not in used_ids:
                # Mark as used
                used_file = self._get_used_file(contact_id)
                used_file.parent.mkdir(exist_ok=True)
                with open(used_file, 'a', encoding='utf-8') as f:
                    f.write(f"{page_id}|sent|{datetime.now().isoformat()}\n")
                
                return (page_id, page[PAGE_ID_LENGTH:])
        
        return None
    
    def find_page_for_decryption(self, page_id: str, contact_id: str) -> Optional[str]:
        """
        Find a page by ID for decrypting a received message.
        
        IMPORTANT: We look in the sender's (contact's) dedicated cipher pad,
        NOT a shared pool. This ensures cryptographic separation.
        
        The page is marked as used if not already.
        
        Returns:
            Page content (without ID) or None if not found
        """
        all_pages = self.get_pad_pages(contact_id)
        used_ids = self.get_used_page_ids(contact_id)
        
        for page in all_pages:
            if page[:PAGE_ID_LENGTH] == page_id:
                # Mark as used if not already
                if page_id not in used_ids:
                    used_file = self._get_used_file(contact_id)
                    used_file.parent.mkdir(exist_ok=True)
                    with open(used_file, 'a', encoding='utf-8') as f:
                        f.write(f"{page_id}|received|{datetime.now().isoformat()}\n")
                
                return page[PAGE_ID_LENGTH:]
        
        return None
    
    # --- Statistics ---
    
    def get_all_contacts_with_pads(self) -> List[str]:
        """Get list of contacts that have cipher pads."""
        if not CONTACTS_DIR.exists():
            return []
        
        contacts = []
        for item in CONTACTS_DIR.iterdir():
            if item.is_dir() and (item / "cipher.txt").exists():
                contacts.append(item.name)
        
        return sorted(contacts)
    
    def get_statistics(self) -> dict:
        """Get overall OTP statistics across all contacts."""
        contacts = self.get_all_contacts_with_pads()
        
        total_pages = 0
        total_available = 0
        total_used = 0
        contact_stats = {}
        
        for contact_id in contacts:
            total, available, used = self.get_page_counts(contact_id)
            total_pages += total
            total_available += available
            total_used += used
            contact_stats[contact_id] = {
                'total': total,
                'available': available,
                'used': used
            }
        
        return {
            'num_contacts': len(contacts),
            'total_pages': total_pages,
            'total_available': total_available,
            'total_used': total_used,
            'contacts': contact_stats
        }


# --- Standalone usage ---
if __name__ == "__main__":
    helper = OTPHelper()
    stats = helper.get_statistics()
    
    print("=" * 50)
    print("OTP Statistics - Per-Contact Cipher Pads")
    print("=" * 50)
    print(f"Contacts with pads: {stats['num_contacts']}")
    print(f"Total pages across all contacts: {stats['total_pages']:,}")
    print(f"Total available: {stats['total_available']:,}")
    print(f"Total used: {stats['total_used']:,}")
    print()
    
    if stats['contacts']:
        print("Per-contact breakdown:")
        for contact_id, data in stats['contacts'].items():
            print(f"  [P] {contact_id}")
            print(f"     Total: {data['total']:,} | Available: {data['available']:,} | Used: {data['used']:,}")
    else:
        print("No contacts have cipher pads yet.")
        print("Use OTP Manager to generate pads for your contacts.")
