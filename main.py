import requests
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from calibration import load_fits_files, create_master_bias, create_master_dark, create_master_flat, calibrate_image, \
    save_fits
from uploader import upload_calibrated_files
from auth import get_auth_token

# Global variables to store file paths
image_paths = []
bias_paths = []
dark_paths = []
flat_paths = []
calibrated_image_paths = []
selected_calibrated_file = None

# Global variables for target name
target_name = ""


# Function to update progress
def update_progress(step, progress_var):
    steps = ["Loading Calibration Frames", "Creating Master Bias", "Creating Master Dark", "Creating Master Flat",
             "Calibrating Images"]
    progress_var.set(f"Step {step + 1} of {len(steps)}: {steps[step]}")


# Function to process images
def process_images(image_paths, bias_paths, dark_paths, flat_paths, token, progress_var):
    global calibrated_image_paths
    try:
        calibrated_image_paths = []  # Clear the previous paths

        for image_path in image_paths:
            # Step 1: Load calibration frames
            update_progress(0, progress_var)
            bias_ccds = load_fits_files(bias_paths) if bias_paths else None
            dark_ccds = load_fits_files(dark_paths) if dark_paths else None
            flat_ccds = load_fits_files(flat_paths) if flat_paths else None

            # Step 2: Create master bias
            update_progress(1, progress_var)
            master_bias = create_master_bias(bias_ccds) if bias_ccds else None

            # Step 3: Create master dark
            update_progress(2, progress_var)
            master_dark = create_master_dark(dark_ccds, master_bias) if dark_ccds and master_bias else None

            # Step 4: Create master flat
            update_progress(3, progress_var)
            master_flat = create_master_flat(flat_ccds, master_bias,
                                             master_dark) if flat_ccds and master_bias and master_dark else None

            # Step 5: Calibrate the image
            update_progress(4, progress_var)
            calibrated_image = calibrate_image(image_path, master_bias, master_dark,
                                               master_flat) if master_bias and master_dark and master_flat else None

            if calibrated_image:
                calibrated_image_path = image_path.replace(".fits", "_calibrated.fits").replace(".fit",
                                                                                                "_calibrated.fit")
                save_fits(calibrated_image, calibrated_image_path)
                calibrated_image_paths.append(calibrated_image_path)
            else:
                messagebox.showinfo("Calibration Not Completed",
                                    f"Calibration was not completed for {os.path.basename(image_path)} due to missing files.")

        if calibrated_image_paths:
            ask_target_name()

    except Exception as e:
        messagebox.showerror("Error", f"Error processing image {image_path}: {e}")
        print(f"Error processing image {image_path}: {e}")


# Functions to select files
def select_fits_files():
    global image_paths
    image_paths = filedialog.askopenfilenames(title="Select FITS Files", filetypes=[("FITS files", "*.fits *.fit")])
    if not image_paths:
        messagebox.showinfo("No files selected", "Please select at least one FITS file.")
        return
    fits_label.config(text=f"Selected FITS Files: {len(image_paths)} files")


def select_bias_frames():
    global bias_paths
    bias_paths = filedialog.askopenfilenames(title="Select Bias Frames", filetypes=[("FITS files", "*.fits *.fit")])
    if not bias_paths:
        messagebox.showinfo("No bias frames selected", "Please select at least one bias frame.")
    else:
        bias_label.config(text=f"Selected Bias Frames: {len(bias_paths)} files")


def select_dark_frames():
    global dark_paths
    dark_paths = filedialog.askopenfilenames(title="Select Dark Frames", filetypes=[("FITS files", "*.fits *.fit")])
    if not dark_paths:
        messagebox.showinfo("No dark frames selected", "Please select at least one dark frame.")
    else:
        dark_label.config(text=f"Selected Dark Frames: {len(dark_paths)} files")


def select_flat_frames():
    global flat_paths
    flat_paths = filedialog.askopenfilenames(title="Select Flat Frames", filetypes=[("FITS files", "*.fits *.fit")])
    if not flat_paths:
        messagebox.showinfo("No flat frames selected", "Please select at least one flat frame.")
    else:
        flat_label.config(text=f"Selected Flat Frames: {len(flat_paths)} files")


def select_calibrated_file():
    global selected_calibrated_file
    selected_calibrated_file = filedialog.askopenfilename(title="Select Calibrated FITS File",
                                                          filetypes=[("FITS files", "*.fits *.fit")])
    if not selected_calibrated_file:
        messagebox.showinfo("No file selected", "Please select a calibrated FITS file.")
    else:
        calibrated_file_label.config(text=f"Selected Calibrated File: {selected_calibrated_file}")
        ask_target_name()  # Ask for the target name after selecting the file


def start_processing():
    if not image_paths:
        messagebox.showinfo("No FITS files", "Please select at least one FITS file.")
        return
    try:
        token = get_auth_token(username, password)
        process_images(image_paths, bias_paths, dark_paths, flat_paths, token, progress_var)
    except Exception as e:
        messagebox.showerror("Error", f"Error processing selected files: {e}")
        print(f"Error processing selected files: {e}")


def upload_selected_calibrated_file():
    if not selected_calibrated_file:
        messagebox.showinfo("No file selected", "Please select a calibrated FITS file.")
        return
    try:
        token = get_auth_token(username, password)
        upload_calibrated_files([selected_calibrated_file], token, target_name, app)
    except Exception as e:
        messagebox.showerror("Error", f"Error uploading calibrated file: {e}")
        print(f"Error uploading calibrated file: {e}")


# Function to handle login
def handle_login():
    global username
    global password
    username = username_entry.get()
    password = password_entry.get()

    try:
        global token
        token = get_auth_token(username, password)
        login_window.destroy()
        create_main_window()
    except requests.exceptions.HTTPError as e:
        messagebox.showerror("Login Failed", f"Invalid credentials. Please try again.\nDetails: {e}")
        print(f"Login failed: {e.response.content}")


# Function to ask for Target Name
def ask_target_name():
    global target_name_entry
    target_name_window = tk.Tk()
    target_name_window.title("Enter Target Name")

    tk.Label(target_name_window, text="Target Name").pack(pady=5)
    target_name_entry = tk.Entry(target_name_window)
    target_name_entry.pack(pady=5)

    submit_button = tk.Button(target_name_window, text="Submit",
                              command=lambda: handle_target_name_submit(target_name_window))
    submit_button.pack(pady=20)


def handle_target_name_submit(window):
    global target_name
    target_name = target_name_entry.get()
    window.destroy()
    upload_button.config(state=tk.NORMAL)  # Enable the upload button after target name is entered


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
    global progress_var
    global fits_label
    global bias_label
    global dark_label
    global flat_label
    global upload_button
    global calibrated_file_label
    global app

    app = tk.Tk()
    app.title("Telescope Automation")

    frame = tk.Frame(app)
    frame.pack(pady=20, padx=20)

    fits_button = tk.Button(frame, text="Select FITS Files", command=select_fits_files)
    fits_button.pack(side=tk.TOP, padx=10, pady=5)
    fits_label = tk.Label(frame, text="No FITS files selected")
    fits_label.pack(side=tk.TOP, padx=10, pady=5)

    bias_button = tk.Button(frame, text="Select Bias Frames", command=select_bias_frames)
    bias_button.pack(side=tk.TOP, padx=10, pady=5)
    bias_label = tk.Label(frame, text="No Bias frames selected")
    bias_label.pack(side=tk.TOP, padx=10, pady=5)

    dark_button = tk.Button(frame, text="Select Dark Frames", command=select_dark_frames)
    dark_button.pack(side=tk.TOP, padx=10, pady=5)
    dark_label = tk.Label(frame, text="No Dark frames selected")
    dark_label.pack(side=tk.TOP, padx=10, pady=5)

    flat_button = tk.Button(frame, text="Select Flat Frames", command=select_flat_frames)
    flat_button.pack(side=tk.TOP, padx=10, pady=5)
    flat_label = tk.Label(frame, text="No Flat frames selected")
    flat_label.pack(side=tk.TOP, padx=10, pady=5)

    start_button = tk.Button(frame, text="Start Processing", command=start_processing)
    start_button.pack(side=tk.TOP, padx=10, pady=20)

    progress_var = tk.StringVar()
    progress_label = tk.Label(frame, textvariable=progress_var)
    progress_label.pack(side=tk.TOP, padx=10, pady=5)

    upload_button = tk.Button(frame, text="Upload Result to BHTOM",
                              command=lambda: upload_calibrated_files(calibrated_image_paths, token, target_name, app))
    upload_button.pack(side=tk.TOP, padx=10, pady=20)
    upload_button.config(state=tk.DISABLED)  # Disable initially until calibration is complete

    tk.Button(frame, text="Choose Calibrated File", command=select_calibrated_file).pack(side=tk.TOP, padx=10, pady=5)
    calibrated_file_label = tk.Label(frame, text="No calibrated file selected")
    calibrated_file_label.pack(side=tk.TOP, padx=10, pady=5)

    tk.Button(frame, text="Upload Selected Calibrated File to BHTOM", command=upload_selected_calibrated_file).pack(
        side=tk.TOP, padx=10, pady=20)

    app.mainloop()

login_window.mainloop()
