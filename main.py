import os
import tkinter as tk
import numpy as np
import matplotlib.pyplot as plt
from io import BytesIO
from astropy.io import fits
from PIL import Image, ImageTk
from tkinter import filedialog, messagebox, ttk, Toplevel
from calibration import set_calibration, process_calibration
from uploader import upload_calibrated_files
from auth import get_auth_token
from login import login_window, save_credentials, delete_credentials
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# Global variables for authentication and calibration
token = ""
app = None
calibrated_lights = None
lights = None
oname = ""  # Variable for ONAME (determined by camera selection)

# Main application class
class CalibrationApp:
    def __init__(self, master):
        # Initialize window and column counts for cascading logic
        self.window_count = 0
        self.column_count = 0
        self.open_windows = []

        self.master = master
        self.master.title("Telescope Automation")
        self.frame = tk.Frame(self.master)

        # Set the desired width and height for the main window
        screen_width = self.master.winfo_screenwidth()
        screen_height = self.master.winfo_screenheight()

        # Make the main window start in the center
        y = (self.master.winfo_screenheight() // 2) - (screen_height // 2)
        x = (self.master.winfo_screenwidth() // 2) - (screen_width // 2)
        self.master.geometry(f'{screen_width}x{screen_height}+{x}+{y}')

        # Create a canvas to place buttons on
        self.canvas = tk.Canvas(self.master, bg='black', highlightcolor='black', highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # Define relative size of buttons
        reference_red_button_width = 265
        reference_grey_button_width = 250
        reference_button_height = 35

        # Calculate real size of buttons
        red_button_width = int(reference_red_button_width / 1280 * screen_width)
        grey_button_width = int(reference_grey_button_width / 1280 * screen_width)
        button_height = int(reference_button_height / 720 * screen_height)

        # Place buttons on the canvas
        self.open_button = tk.Button(self.canvas, text="Open Files", command=self.open_files, bg="#de3b40", fg="white",
                                     highlightbackground="#de3b40", highlightthickness=30)
        self.canvas.create_window(0, 0, anchor='nw', window=self.open_button, width=red_button_width,
                                  height=button_height)

        # Position and initially hide the "Clear" button
        self.clear_button = tk.Button(self.canvas, text="Clear", command=self.clear_windows, bg="#9095a1", fg="white", highlightbackground="#9095a1", highlightthickness=30)
        self.clear_button_window = self.canvas.create_window(0, button_height, anchor='nw', window=self.clear_button, width=grey_button_width, height=button_height)
        self.canvas.itemconfigure(self.clear_button_window, state='hidden')  # Hide initially

        # Calibration files button
        self.calibration_button = tk.Button(self.canvas, text="Calibration", command=self.set_calibration, bg="#9095a1",
                                            fg="white", highlightbackground="#9095a1", highlightthickness=30)
        self.canvas.create_window(red_button_width, 0, anchor='nw', window=self.calibration_button,
                                  width=grey_button_width, height=button_height)

        # Upload files button
        self.bulk_upload_button = tk.Button(self.canvas, text="Bulk Upload", command=self.upload_calibrated_files, bg="#9095a1",
                                            fg="white", highlightbackground="#9095a1", highlightthickness=30)
        self.canvas.create_window(red_button_width + grey_button_width, 0, anchor='nw', window=self.bulk_upload_button,
                                  width=grey_button_width, height=button_height)

        # Run in Auto button
        self.run_in_automation_button = tk.Button(self.canvas, text="Run in Automation", command=self.run_in_automation,
                                                  bg="#9095a1", fg="white", highlightbackground="#9095a1",
                                                  highlightthickness=30)
        self.canvas.create_window(red_button_width + grey_button_width * 2, 0, anchor='nw',
                                  window=self.run_in_automation_button, width=grey_button_width, height=button_height)

        # Log Out button
        self.logout_button = tk.Button(self.canvas, text="Log Out", command=self.logout, bg="#de3b40", fg="white",
                                       highlightbackground="#de3b40", highlightthickness=30)
        self.canvas.create_window(red_button_width + grey_button_width * 3, 0, anchor='nw', window=self.logout_button,
                                  width=red_button_width, height=button_height)

        self.master.update_idletasks()

        # Observatory Selection Dropdown
        self.observatory_label = tk.Label(self.master, text="Select Observatory:", bg="black", fg="white", font=('Arial', 15))
        self.observatory_label.place(x=25, y=float(self.master.winfo_height()) - 95)

        self.observatory_combo = ttk.Combobox(self.master, values=["Lisnyky Observatory AZT-8 70-cm"], state="readonly")
        self.observatory_combo.place(x=25, y=float(self.master.winfo_height()) - 65)  # Below the label

        self.master.update_idletasks()

        # Camera Selection Dropdown
        self.camera_label = tk.Label(self.master, text="Select Camera:", bg="black", fg="white", font=('Arial', 15))
        self.camera_label.place(x=float(self.observatory_combo.winfo_width()) + 50, y=float(self.master.winfo_height()) - 95)

        self.camera_combo = ttk.Combobox(self.master, values=["FLI PL47-10", "Moravian C4-16000"], state="readonly")
        self.camera_combo.place(x=float(self.observatory_combo.winfo_width()) + 50, y=float(self.master.winfo_height()) - 65)
        self.camera_combo.bind("<<ComboboxSelected>>", self.handle_camera_selection)

    def handle_camera_selection(self, event):
        global oname
        camera = self.camera_combo.get()

        if camera == "FLI PL47-10":
            oname = "AZT-8_PL-4710"
        elif camera == "Moravian C4-16000":
            oname = "AZT-8_C4-16000"
        else:
            oname = ""  # Just in case no camera is selected, but this shouldn't happen

    def logout(self):
        delete_credentials()  # Delete stored credentials
        self.master.destroy()  # Close the main window
        login_window(handle_login)  # Reopen the login window

    def set_calibration(self):
        global calibrated_lights, lights

        # Call the calibration process from calibration.py
        calibrated_lights, lights = set_calibration()

        if calibrated_lights and lights:
            # Automatically save calibrated files without prompt
            folder_selected = filedialog.askdirectory(title="Select Folder to Save Calibrated Files")
            if not folder_selected:
                messagebox.showerror("Error", "No folder selected for saving calibrated files.")
                return

            calibrated_folder = os.path.join(folder_selected, "Calibrated files")
            os.makedirs(calibrated_folder, exist_ok=True)

            # Save and open each calibrated file
            for i, calibrated_light in enumerate(calibrated_lights):
                if isinstance(calibrated_light, np.ndarray) and calibrated_light.ndim == 2:
                    file_name = f"calibrated_{os.path.basename(lights[i])}"
                    file_path = os.path.join(calibrated_folder, file_name)

                    # Save the calibrated light as a FITS file
                    hdu = fits.PrimaryHDU(calibrated_light)
                    hdu.writeto(file_path, overwrite=True)
                    print(f"Calibrated file saved successfully: {file_path}")

                    # Automatically open the calibrated FITS file for display
                    self.display_image(calibrated_light, None, file_name)
                else:
                    print(f"Error: Calibrated light {i} is not a valid 2D array.")

            # Store the path of the most recently saved calibrated folder for bulk upload
            self.most_recent_calibrated_folder = calibrated_folder

            # Show the "Clear" button after calibration
            self.canvas.itemconfigure(self.clear_button_window, state='normal')
        else:
            messagebox.showerror("Calibration Error", "Calibration failed or returned no data.")

    def upload_calibrated_files(self):
        global token, lights, oname

        # Check if there are recently calibrated files
        if hasattr(self, 'most_recent_calibrated_folder') and self.most_recent_calibrated_folder:
            # Suggest uploading the most recent calibrated files
            use_recent_files = messagebox.askyesno("Upload Calibrated Files",
                                                   f"Would you like to upload the most recent calibrated files from:\n{self.most_recent_calibrated_folder}?")
            if use_recent_files:
                folder_selected = self.most_recent_calibrated_folder
            else:
                # Ask the user to manually select a folder
                folder_selected = filedialog.askdirectory(title="Select Folder Containing Calibrated Files")
                if not folder_selected:
                    return
        else:
            # Ask the user to manually select a folder
            folder_selected = filedialog.askdirectory(title="Select Folder Containing Calibrated Files")
            if not folder_selected:
                return

        # Get the list of calibrated FITS files
        calibrated_files = [os.path.join(folder_selected, file) for file in os.listdir(folder_selected)
                            if file.endswith(('.fit', '.fits'))]
        if not calibrated_files:
            messagebox.showerror("Error", "No calibrated files found in the selected folder.")
            return

        # Ask the user for the target name
        target_name = self.ask_target_name()
        if not target_name:
            return

        try:
            # Proceed with uploading the calibrated files
            upload_calibrated_files(calibrated_files, token, target_name, oname, self.master)
        except Exception as e:
            messagebox.showerror("Error", f"Error uploading calibrated files: {e}")
            print(f"Error uploading calibrated files: {e}")

        # Get the list of calibrated FITS files
        calibrated_files = [os.path.join(folder_selected, file) for file in os.listdir(folder_selected)
                            if file.endswith(('.fit', '.fits'))]
        if not calibrated_files:
            messagebox.showerror("Error", "No calibrated files found in the selected folder.")
            return

        # Ask the user for the target name
        target_name = self.ask_target_name()
        if not target_name:
            return

        try:
            # Proceed with uploading the calibrated files
            upload_calibrated_files(calibrated_files, token, target_name, oname, self.master)
        except Exception as e:
            messagebox.showerror("Error", f"Error uploading calibrated files: {e}")
            print(f"Error uploading calibrated files: {e}")

    def ask_target_name(self):
        target_name_window = tk.Toplevel(self.master)
        target_name_window.title("Enter Target Name")

        tk.Label(target_name_window, text="Target Name").pack(pady=5)
        target_name_entry = tk.Entry(target_name_window)
        target_name_entry.pack(pady=5)

        submit_button = tk.Button(target_name_window, text="Submit",
                                  command=lambda: target_name_window.quit())
        submit_button.pack(pady=20)

        target_name_window.mainloop()
        target_name = target_name_entry.get().strip()
        target_name_window.destroy()

        if not target_name:
            messagebox.showerror("Error", "Target name cannot be empty.")
            return None

        return target_name

    def open_files(self):
        # Open a file dialog to select multiple FIT/FITS files
        file_paths = filedialog.askopenfilenames(filetypes=[("FITS files", "*.fits *.fit")])

        if file_paths:
            # Loop over all selected files and open each one
            for file_path in file_paths:
                try:
                    # Read the FITS file
                    with fits.open(file_path) as hdulist:
                        # Get the image data from the first HDU
                        image_data = hdulist[0].data
                        header_data = hdulist[0].header

                        # Check if the image data is valid
                        if image_data is None:
                            messagebox.showerror("Error", f"No image data found in the FITS file: {file_path}")
                            continue

                        # Extract the file name from the full path
                        file_name = os.path.basename(file_path)

                        # Open a new window to display the image
                        self.display_image(image_data, header_data, file_name)

                except Exception as e:
                    messagebox.showerror("Error", f"Failed to open FITS file: {e}")

            # Show the "Clear" button after opening files
            self.canvas.itemconfigure(self.clear_button_window, state='normal')

    def display_image(self, image_data, header_data, file_name):
        # Validate the image data
        if not isinstance(image_data, np.ndarray) or image_data.ndim != 2:
            print(f"Error: Image data for {file_name} is not a valid 2D array.")
            messagebox.showerror("Image Error", f"Image data for {file_name} is not a valid 2D array.")
            return

        # Adjust contrast using percentiles
        vmin = np.percentile(image_data, 2)
        vmax = np.percentile(image_data, 98)

        # Create the figure for the image
        fig, ax = plt.subplots()
        ax.imshow(image_data, cmap='gray', origin='lower', vmin=vmin, vmax=vmax)
        ax.axis('off')  # Remove axes

        # Save the figure as a PNG to a buffer, ensuring no white corners
        buf = BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight', pad_inches=0)
        plt.close(fig)

        # Load the image from the buffer into a PIL object
        buf.seek(0)
        img = Image.open(buf)

        # Get the real size of the image
        img_width, img_height = img.size

        # Cascading logic for window positions
        initial_x = 0
        initial_y = self.clear_button.winfo_reqheight() * 2

        if self.window_count >= 8:
            self.window_count = 0
            self.column_count += 1

        if self.column_count > 10:
            self.column_count = 1

        x_offset = 10 * self.window_count
        y_offset = 20 * self.window_count
        window_x = initial_x + (self.column_count * 100) + x_offset
        window_y = initial_y + y_offset

        self.window_count += 1

        # Create a new window for the FITS image and set its size to match the image size
        image_window = tk.Toplevel(self.master)
        image_window.title(file_name)  # Set the window title to the file name
        image_window.geometry(
            f"{img_width}x{img_height + 40}+{window_x}+{window_y}")  # Add space for the button and position the window
        image_window.resizable(False, False)
        image_window.transient(self.master)  # Keep on top of the main window
        image_window.lift()  # Ensure it's topmost
        image_window.attributes('-topmost', True)

        # Create a canvas to display the image
        canvas = tk.Canvas(image_window, width=img_width, height=img_height)
        canvas.pack()

        # Convert the image to a Tkinter-compatible format
        photo = ImageTk.PhotoImage(img)

        # Display the image on the canvas
        canvas.create_image(0, 0, anchor=tk.NW, image=photo)
        canvas.image = photo  # Keep reference to avoid garbage collection

        # Add a button to read the FITS header (positioned at the bottom with minimal vertical spacing)
        header_button = tk.Button(image_window, text="View Header",
                                  command=lambda: self.show_header(header_data, file_name))
        header_button.pack(side=tk.BOTTOM, pady=5)  # Small vertical padding

        # Keep track of opened windows
        self.open_windows.append(image_window)

    def show_header(self, header_data, file_name):
        # Create a new window to display the FITS header
        header_window = tk.Toplevel(self.master)
        header_window.title(f"FITS Header: {file_name}")  # Set the window title to "FITS Header: file_name"

        # Disable resizing of the header window
        header_window.resizable(False, False)

        # Create a Text widget to display the header information
        text_widget = tk.Text(header_window, wrap="word", width=80, height=20)
        text_widget.pack()

        # Insert the header data into the Text widget
        text_widget.insert("1.0", str(header_data))

        # Disable editing
        text_widget.config(state=tk.DISABLED)

    def lift_window(self, event):
        window = event.widget.winfo_toplevel()
        window.lift()  # Bring the clicked window to the front

    def clear_windows(self):
        for window in self.open_windows:
            window.destroy()
        self.open_windows.clear()
        self.window_count = 0
        self.column_count = 0
        self.canvas.itemconfigure(self.clear_button_window, state='hidden')  # Hide Clear button

    def run_in_automation(self):
        print("Run in Automation button clicked")

# Function to handle login and open main window
def handle_login(username, password, root):
    global token
    try:
        token = get_auth_token(username, password)
        print("Successfully logged in")
        root.destroy()  # Close the login window
        save_credentials(username, password)
        create_main_window()  # Open the main window
    except Exception as e:
        print(f"Login failed: {e}")
        tk.messagebox.showerror("Login Failed", "Invalid credentials. Please try again.")

# Create main window after login
def create_main_window():
    global app
    root = tk.Tk()
    app = CalibrationApp(root)
    root.mainloop()


# Start the login process
login_window(handle_login)