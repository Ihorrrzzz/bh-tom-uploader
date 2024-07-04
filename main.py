import configparser

import tkinter as tk
from tkinter import filedialog
from tkinter import messagebox
from calibration import calibrate_image
from uploader import upload_to_bhtom, get_light_curve_data
from light_curve import display_light_curve
import requests


# Function to get auth token
def get_auth_token(username, password):
    url = "https://bh-tom2.astrolabs.pl/api/token-auth/"
    payload = {
        'username': username,
        'password': password
    }
    headers = {
        'Content-Type': 'application/json'
    }

    response = requests.post(url, json=payload, headers=headers)
    response.raise_for_status()
    return response.json()['token']


# Function to process image
def process_image(image_path, token):
    print(f"Processing image: {image_path}")
    try:
        calibrated_image_path = calibrate_image(image_path)
        upload_response = upload_to_bhtom(calibrated_image_path, token)
        if upload_response:
            light_curve_data = get_light_curve_data(upload_response, token)
            if light_curve_data:
                display_light_curve(light_curve_data)
    except Exception as e:
        print(f"Error processing image {image_path}: {e}")


# Function to select files
def select_files():
    file_paths = filedialog.askopenfilenames(filetypes=[("FITS files", "*.fits *.fit")])
    if file_paths:
        listbox.delete(0, tk.END)
        for file_path in file_paths:
            listbox.insert(tk.END, file_path)
        process_selected_files(file_paths)
    else:
        messagebox.showinfo("No file selected", "Please select at least one FITS file.")


# Function to process selected files
def process_selected_files(file_paths):
    token = get_auth_token(username, password)
    for file_path in file_paths:
        process_image(file_path, token)


# Function to handle login
def handle_login():
    global username
    global password
    username = username_entry.get()
    password = password_entry.get()
    login_window.destroy()
    create_main_window()


# Create login window
login_window = tk.Tk()
login_window.title("Login to BHTOM")

tk.Label(login_window, text="Username").pack(pady=5)
username_entry = tk.Entry(login_window)
username_entry.pack(pady=5)

tk.Label(login_window, text="Password").pack(pady=5)
password_entry = tk.Entry(login_window, show="*")
password_entry.pack(pady=5)

login_button = tk.Button(login_window, text="Login", command=handle_login)
login_button.pack(pady=20)


# Function to create the main window
def create_main_window():
    global listbox
    app = tk.Tk()
    app.title("Telescope Automation")

    frame = tk.Frame(app)
    frame.pack(pady=20, padx=20)

    select_button = tk.Button(frame, text="Select FITS Files", command=select_files)
    select_button.pack(side=tk.LEFT, padx=10)

    listbox = tk.Listbox(frame, width=50, height=10)
    listbox.pack(side=tk.LEFT, padx=10)

    app.mainloop()


login_window.mainloop()
