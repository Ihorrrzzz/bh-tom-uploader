import tkinter as tk
import json
import os
from tkinter import Canvas, messagebox
from PIL import Image, ImageTk
from datetime import datetime, timedelta

# File where we will store the user credentials
CREDENTIALS_FILE = 'credentials.json'
EXPIRATION_HOURS = 24  # Credentials are valid for 24 hours

# Function to open the forgot password URL
def open_forgot_password(event):
    import webbrowser
    webbrowser.open("https://bh-tom2.astrolabs.pl")

# Function to manage placeholder text
def on_entry_focus_in(entry, default_text, color):
    if entry.get() == default_text:
        entry.delete(0, "end")
        entry.config(fg=color)

def on_entry_focus_out(entry, default_text, color):
    if entry.get() == '':
        entry.insert(0, default_text)
        entry.config(fg=color)

def toggle_password(entry_password, toggle_btn, visible_icon, hidden_icon):
    if entry_password.cget('show') == '':
        entry_password.config(show='*')
        toggle_btn.config(image=hidden_icon)
    else:
        entry_password.config(show='')
        toggle_btn.config(image=visible_icon)

# Function to draw a rounded rectangle on the canvas
def create_rounded_rect(canvas, x1, y1, x2, y2, radius=4, **kwargs):
    points = [
        x1 + radius, y1,
        x1 + radius, y1,
        x2 - radius, y1,
        x2 - radius, y1,
        x2, y1,
        x2, y1 + radius,
        x2, y2 - radius,
        x2, y2 - radius,
        x2, y2,
        x2 - radius, y2,
        x2 - radius, y2,
        x1 + radius, y2,
        x1 + radius, y2,
        x1, y2,
        x1, y2 - radius,
        x1, y2 - radius,
        x1, y1 + radius,
        x1, y1 + radius,
        x1, y1,
    ]
    return canvas.create_polygon(points, **kwargs, smooth=True)

# Function to save credentials to a file
def save_credentials(username, password):
    data = {
        'username': username,
        'password': password,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    with open(CREDENTIALS_FILE, 'w') as file:
        json.dump(data, file)

# Function to load saved credentials from the file (if they exist and are not expired)
def load_credentials():
    if os.path.exists(CREDENTIALS_FILE):
        with open(CREDENTIALS_FILE, 'r') as file:
            data = json.load(file)
            # Check if the saved credentials are still valid
            saved_time = datetime.strptime(data['timestamp'], '%Y-%m-%d %H:%M:%S')
            if datetime.now() - saved_time < timedelta(hours=EXPIRATION_HOURS):
                return data['username'], data['password']
    return None, None

# Function to delete saved credentials
def delete_credentials():
    if os.path.exists(CREDENTIALS_FILE):
        os.remove(CREDENTIALS_FILE)

# Function to display the login window
def login_window(handle_login):
    root = tk.Tk()
    root.geometry("540x640")
    root.configure(bg='#151515')
    root.resizable(False, False)

    height = 640
    width = 540

    # Make the main window start in the center
    y = (root.winfo_screenheight() // 2) - (height // 2)
    x = (root.winfo_screenwidth() // 2) - (width // 2)
    root.geometry('{}x{}+{}+{}'.format(width, height, x, y))

    # Load the images for the toggle button and the black hole image
    hidden_icon = ImageTk.PhotoImage(Image.open("hidden.png").resize((16, 16)))
    visible_icon = ImageTk.PhotoImage(Image.open("visible.png").resize((16, 16)))
    logo_icon = ImageTk.PhotoImage(Image.open("logo.png").resize((157, 80)))

    # Create a Canvas to hold the background image and text
    canvas_welcome = Canvas(root, width=width, height=100, bg='#151515', highlightthickness=0)
    canvas_welcome.place(x=0, y=47)  # logo image at y=47

    # Place the logo image on the canvas
    canvas_welcome.create_image(width // 2, 47, image=logo_icon)

    # Overlay the "Welcome Back" text on top of the image
    canvas_welcome.create_text(width // 2, 41, text="Welcome Back", font=("Lexend", 41, "bold"), fill="white")

    # Create "Sign in to your BHTOM account" label
    signin_label = tk.Label(root, text="Sign in to your BHTOM account", font=("Lexend", 24, "bold"), fg="#A09FA0", bg="#151515")
    signin_label.place(x=(width - signin_label.winfo_reqwidth()) // 2, y=154)

    # Set common x and width values for entry fields
    entry_x = 35
    entry_width = width - 2 * entry_x

    # Styling variables
    entry_default_bg = '#FFFFFF'  # White background for both label and canvas
    entry_hover_bg = '#FFFFFF'    # White background
    entry_default_fg = '#BDC1CA'  # Neutral-400 for placeholder text
    entry_typing_fg = '#171A1F'   # Neutral-900 for typed text
    label_bg = entry_default_bg   # Make label background the same as the canvas
    label_fg = '#171A1F'          # Neutral-900 for label text
    font = ('Manrope', 14)
    radius = 4                    # Radius for rounded corners

    # Canvas dimensions
    canvas_width = 469
    canvas_height = 71

    # Calculate starting y positions based on constraints
    email_y = 210
    password_y = email_y + canvas_height + 30
    forgot_password_y = password_y + canvas_height + 30
    signin_button_y = forgot_password_y + 60
    continue_label_y = signin_button_y + 44 + 15

    # Create Canvas for Email
    canvas_email = Canvas(root, width=canvas_width, height=canvas_height, bg='#2c2c2c', highlightthickness=0)
    canvas_email.place(x=entry_x, y=email_y)

    # Draw the rounded rectangle
    create_rounded_rect(canvas_email, 0, 0, canvas_width, canvas_height, radius, fill=entry_default_bg)

    # Place Email label
    label_email = tk.Label(canvas_email, text="Username", fg=label_fg, bg=label_bg, font=(font[0], 14, 'bold'))
    canvas_email.create_window(12, 13.5, anchor='nw', window=label_email)  # Positioning Email label

    # Create and place Email entry
    entry_email = tk.Entry(canvas_email, fg=entry_default_fg, bg=entry_default_bg, font=font, bd=0, highlightthickness=0, width=38)
    entry_email.insert(0, 'example.username')
    canvas_email.create_window(12.5, canvas_height - 12.5 - 22, anchor='nw', window=entry_email)  # Positioning Email entry

    entry_email.bind("<FocusIn>", lambda event: on_entry_focus_in(entry_email, 'example.username', entry_typing_fg))
    entry_email.bind("<FocusOut>", lambda event: on_entry_focus_out(entry_email, 'example.username', entry_default_fg))

    # Create Canvas for Password
    canvas_password = Canvas(root, width=canvas_width, height=canvas_height, bg='#2c2c2c', highlightthickness=0)
    canvas_password.place(x=entry_x, y=password_y)

    # Draw the rounded rectangle
    create_rounded_rect(canvas_password, 0, 0, canvas_width, canvas_height, radius, fill=entry_default_bg)

    # Place Password label
    label_password = tk.Label(canvas_password, text="Password", fg=label_fg, bg=label_bg, font=(font[0], 14, 'bold'))
    canvas_password.create_window(12, 13.5, anchor='nw', window=label_password)  # Positioning Password label

    # Create and place Password entry
    entry_password = tk.Entry(canvas_password, fg=entry_default_fg, bg=entry_default_bg, font=font, bd=0, highlightthickness=0, width=34, show='*')
    entry_password.insert(0, 'Enter at least 8+ characters')
    canvas_password.create_window(12.5, canvas_height - 10 - 22, anchor='nw', window=entry_password)  # Positioning Password entry

    entry_password.bind("<FocusIn>", lambda event: on_entry_focus_in(entry_password, 'Enter at least 8+ characters', entry_typing_fg))
    entry_password.bind("<FocusOut>", lambda event: on_entry_focus_out(entry_password, 'Enter at least 8+ characters', entry_default_fg))

    # Password Toggle Button with Image
    toggle_btn = tk.Label(canvas_password, image=hidden_icon, bg=entry_default_bg)
    toggle_btn.bind("<Button-1>", lambda event: toggle_password(entry_password, toggle_btn, visible_icon, hidden_icon))
    canvas_password.create_window(canvas_width - 12 - 16, canvas_height - 18 - 16, anchor='nw', window=toggle_btn)  # Aligning the button

    # Create the "Remember me" checkbox
    remember_var = tk.IntVar()
    remember_checkbox = tk.Checkbutton(root, text="Remember me", font=("Manrope", 14), fg="#BDC1CA", bg="#151515", variable=remember_var, activebackground="#1E2128")
    remember_checkbox.place(x=entry_x, y=forgot_password_y)  # 30px from the password field

    # Create the "Forgot password?" label with click functionality
    forgot_label = tk.Label(root, text="Forgot password?", font=("Manrope", 14), fg="#BDC1CA", bg="#151515", cursor="hand2")
    forgot_label.place(x=(width - forgot_label.winfo_reqwidth()) - 35, y=forgot_password_y)  # Align on the right
    forgot_label.bind("<Button-1>", open_forgot_password)

    # Create a Canvas to draw the rounded button
    canvas = tk.Canvas(root, width=entry_width, height=44, bg='#151515', highlightthickness=0)
    canvas.place(x=entry_x, y=signin_button_y)  # Properly positioned 30px below the "Forgot password?" label and checkbox

    # Draw the rounded rectangle button
    create_rounded_rect(canvas, 0, 0, entry_width, 44, radius=4, fill="#DE3B40", outline="")

    # Add text to the button
    canvas.create_text(entry_width // 2, 22, text="Sign in", font=("Manrope", 16), fill="white")

    # Bind a click event to the button
    canvas.tag_bind("all", "<Button-1>", lambda e: handle_login(entry_email.get(), entry_password.get(), root))

    # Create "Continue without login" label
    continue_label = tk.Label(root, text="Continue without login", font=("Manrope", 14), fg="#BDC1CA", bg="#151515", cursor="hand2")
    continue_label.place(x=(width - continue_label.winfo_reqwidth()) // 2, y=continue_label_y)

    # Load saved credentials (if available and not expired)
    saved_username, saved_password = load_credentials()
    if saved_username and saved_password:
        entry_email.delete(0, tk.END)
        entry_email.insert(0, saved_username)
        entry_email.config(fg=entry_typing_fg)  # Set to typing color (black)

        entry_password.delete(0, tk.END)
        entry_password.insert(0, saved_password)
        entry_password.config(fg=entry_typing_fg)  # Set to typing color (black)

        remember_var.set(1)  # Set the "Remember me" checkbox to checked

    root.mainloop()
