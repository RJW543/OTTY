import tkinter as tk
from tkinter import messagebox

def save_credentials():
    # Get the text from the entry box
    username = entry_user.get()
    
    if username.strip():
        try:
            # Open the file in append mode ('a') so we don't overwrite previous entries
            with open("credentials.txt", "a") as file:
                file.write(f"Username: {username}\n")
            
            messagebox.showinfo("Success", "Username saved to credentials.txt")
            entry_user.delete(0, tk.END)  # Clear the input box
        except Exception as e:
            messagebox.showerror("Error", f"Could not save file: {e}")
    else:
        messagebox.showwarning("Input Error", "Please enter a username.")

# --- UI Setup ---
root = tk.Tk()
root.title("Credential Saver")
root.geometry("300x150")

# Label
label = tk.Label(root, text="Enter Username:", pady=10)
label.pack()

# Entry Box
entry_user = tk.Entry(root, width=30)
entry_user.pack(pady=5)

# Save Button
save_button = tk.Button(root, text="Save to File", command=save_credentials, bg="#4CAF50", fg="white")
save_button.pack(pady=20)

root.mainloop()