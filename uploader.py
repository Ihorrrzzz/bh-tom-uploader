import os
import requests
import tkinter as tk
from tkinter import messagebox, simpledialog, filedialog, Button
from PIL import Image, ImageTk
import json
import plotly.graph_objs as go
from plotly.subplots import make_subplots
from datetime import datetime
from astropy.time import Time
import random
import plotly.io as pio
import webbrowser
import tempfile
import io


# Converts MJD to standard date format (DD-MM-YYYY)
def mjd_to_date(mjd):
    t = Time(mjd, format='mjd')
    return t.datetime.strftime('%d-%m-%Y')


# Generate a shade of a given color
def adjust_color_shade(color, factor):
    color = color.lstrip('#')
    r, g, b = tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))
    r = int(r * factor)
    g = int(g * factor)
    b = int(b * factor)
    return f'#{r:02x}{g:02x}{b:02x}'


# Parse the photometry data and create a light curve
def plot_light_curve(data, app):
    if not data:
        messagebox.showinfo("No Data", "No photometry data available to plot.")
        return

    lines = data.splitlines()
    headers = lines[0].split(';')

    if len(headers) < 6:
        messagebox.showerror("Error", "Unexpected photometry data format.")
        return

    # Initialize lists
    mjd = []
    magnitude = []
    error = []
    observer = []
    filter_name = []
    date = []

    # Parse data
    for line in lines[1:]:
        fields = line.split(';')
        if len(fields) >= 6:
            mjd_value = float(fields[0])
            date.append(mjd_to_date(mjd_value))
            mjd.append(mjd_value)
            magnitude.append(float(fields[1]))
            error.append(float(fields[2]))
            filter_name.append(fields[4])
            observer.append(fields[5])

    # Assign random colors to each observer and shades for each filter
    unique_observers = list(set(observer))
    observer_colors = {obs: f'#{random.randint(0, 0xFFFFFF):06x}' for obs in unique_observers}
    obs_filter_colors = {}

    for obs in unique_observers:
        obs_filters = list(set([filter_name[i] for i in range(len(observer)) if observer[i] == obs]))
        n_filters = len(obs_filters)
        for i, filt in enumerate(obs_filters):
            shade_factor = 1 - (i / (n_filters + 1))
            base_color = observer_colors[obs]
            obs_filter_colors[(obs, filt)] = adjust_color_shade(base_color, shade_factor)

    # Create a Plotly figure
    fig = make_subplots(rows=1, cols=1)

    for obs in unique_observers:
        obs_mjd = [date[i] for i in range(len(observer)) if observer[i] == obs]
        obs_magnitude = [magnitude[i] for i in range(len(observer)) if observer[i] == obs]
        obs_error = [error[i] for i in range(len(observer)) if observer[i] == obs]
        obs_filters = [filter_name[i] for i in range(len(observer)) if observer[i] == obs]

        for filt in set(obs_filters):
            filtered_indices = [i for i in range(len(obs_filters)) if obs_filters[i] == filt]
            filt_mjd = [obs_mjd[i] for i in filtered_indices]
            filt_magnitude = [obs_magnitude[i] for i in filtered_indices]
            filt_error = [obs_error[i] for i in filtered_indices]
            filt_color = obs_filter_colors[(obs, filt)]

            fig.add_trace(go.Scatter(
                x=filt_mjd,
                y=filt_magnitude,
                mode='markers+lines',
                error_y=dict(type='data', array=filt_error, visible=True, color=filt_color),
                name=f"{obs} - {filt}",
                marker=dict(color=filt_color, size=4),  # 50% smaller points
                line=dict(width=0.75)  # 50% thinner lines
            ))

    fig.update_layout(
        title="Light Curve",
        xaxis_title="Date (DD-MM-YYYY)",
        yaxis_title="Magnitude",
        yaxis_autorange='reversed',  # Common in astronomy for magnitudes
        height=600,
        width=800,
        legend_title="Observers"
    )

    # Convert the figure to an image and display it in a Tkinter window
    img_buffer = io.BytesIO()
    fig.write_image(img_buffer, format='png')
    img_buffer.seek(0)

    img = Image.open(img_buffer)
    img_tk = ImageTk.PhotoImage(img)

    light_curve_window = tk.Toplevel(app)
    light_curve_window.title("Light Curve")

    label = tk.Label(light_curve_window, image=img_tk)
    label.image = img_tk  # Keep a reference to avoid garbage collection
    label.pack()

    # Add a button to open the full interactive plot in the browser
    def open_in_browser():
        # Use a temporary file to open the interactive plot in the default browser
        with tempfile.NamedTemporaryFile(delete=False, suffix=".html") as tmp_file:
            tmp_file.write(pio.to_html(fig, full_html=False).encode('utf-8'))
            webbrowser.open(f"file://{tmp_file.name}")

    open_browser_button = Button(light_curve_window, text="Open in Browser", command=open_in_browser)
    open_browser_button.pack()


# Function to handle the photometry download and plot
def download_photometry_request(auth_token, name, app):
    request_body = {
        "name": name,
    }

    headers = {
        'accept': 'application/json',
        'Authorization': f'Token {auth_token}',
        'Content-Type': 'application/json',
        'X-CSRFToken': 'uUz2fRnXhPuvD9YuuiDW9cD1LsajeaQnE4hwtEAfR00SgV9bD5HCe5i8n4m4KcOr'
    }
    api_url = "https://bh-tom2.astrolabs.pl/targets/download-photometry/"

    response = requests.post(api_url, json=request_body, headers=headers)

    if response.status_code == 200:
        if response.text:
            print("Photometry Data Received:")
            print(response.text)  # Debug: print raw data
            plot_light_curve(response.text, app)
        else:
            print("Empty Response")
            messagebox.showinfo("Photometry Data", "The photometry response is empty.")
    else:
        print(f"Request for {name} failed with status code {response.status_code}")
        messagebox.showerror("Photometry Request Failed",
                             f"Request for {name} failed with status code {response.status_code}")


# Function to create a new target if it doesn't exist
def create_target(name, ra, dec, epoch, classification, discovery_date, importance, cadence, token):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Token {token}",
    }

    data = {
        "name": name,
        "ra": ra,
        "dec": dec,
        "epoch": epoch if epoch else 2000.0,
        "classification": classification if classification else "Unknown",
        "discovery_date": discovery_date if discovery_date else "2023-01-01T00:00:01Z",
        "importance": importance if importance else 9.97,
        "cadence": cadence if cadence else 1.0,
    }

    api_url = "https://bh-tom2.astrolabs.pl/targets/createTarget/"
    response = requests.post(api_url, headers=headers, json=data)
    response_json = response.json()
    print("Create Target Response:", response_json)

    if response.status_code == 201:  # HTTP status code 201 indicates successful creation
        messagebox.showinfo("Target Created", f"Target '{name}' has been successfully created.")
        return True
    else:
        messagebox.showerror("Target Creation Failed", f"Failed to create target '{name}'.\nDetails: {response_json}")
        return False


# Function to upload calibrated files
def upload_calibrated_files(calibrated_image_paths, token, target_name, app):
    observatory_name = 'AZT-8_C4-16000'
    filter_name = 'GaiaSP/any'

    for calibrated_image_path in calibrated_image_paths:
        with open(calibrated_image_path, 'rb') as f:
            print("Sending...")

            data = {
                'target': target_name,
                'filter': filter_name,
                'data_product_type': 'fits_file',
                'dry_run': 'False',
                'observatory': observatory_name,
            }

            response = requests.post(
                url='https://uploadsvc2.astrolabs.pl/upload/',
                headers={
                    'Authorization': "Token " + str(token)
                },
                data=data,
                files={'files': f}
            )
            result = response.json()
            print("Upload Response:", result)

            if 'target' in result and any("does not exist in the bhtom" in msg for msg in result['target']):
                messagebox.showwarning("Target Not Found",
                                       f"Target '{target_name}' does not exist. Please enter the necessary details to create it.")

                ra = simpledialog.askstring("Input", "Enter Right Ascension (RA) for the target:", parent=app)
                dec = simpledialog.askstring("Input", "Enter Declination (Dec) for the target:", parent=app)

                if ra is None or dec is None:
                    messagebox.showerror("Input Error", "RA and Dec are mandatory fields. Target creation aborted.")
                    return

                ra = float(ra)
                dec = float(dec)

                epoch = simpledialog.askstring("Input", "Enter Epoch (default 2000.0):", parent=app)
                classification = simpledialog.askstring("Input", "Enter Classification (default 'Unknown'):",
                                                        parent=app)
                discovery_date = simpledialog.askstring("Input",
                                                        "Enter Discovery Date (default '2023-01-01T00:00:01Z'):",
                                                        parent=app)
                importance = simpledialog.askstring("Input", "Enter Importance (default 9.97):", parent=app)
                cadence = simpledialog.askstring("Input", "Enter Cadence (default 1.0):", parent=app)

                if create_target(
                        name=target_name,
                        ra=ra,
                        dec=dec,
                        epoch=float(epoch) if epoch else None,
                        classification=classification,
                        discovery_date=discovery_date,
                        importance=float(importance) if importance else None,
                        cadence=float(cadence) if cadence else None,
                        token=token,
                ):
                    with open(calibrated_image_path, 'rb') as retry_f:
                        retry_response = requests.post(
                            url='https://uploadsvc2.astrolabs.pl/upload/',
                            headers={
                                'Authorization': "Token " + str(token)
                            },
                            data=data,
                            files={'files': retry_f}
                        )
                        retry_result = retry_response.json()
                        print("Retry Upload Response:", retry_result)

                        if 'target' not in retry_result:
                            messagebox.showinfo("Upload Successful",
                                                f"Calibrated file successfully uploaded to BHTOM under target '{target_name}'.")
                            download_photometry_request(token, target_name, app)
                        else:
                            messagebox.showerror("Upload Failed",
                                                 f"Failed to upload calibrated file after target creation.\nDetails: {retry_result}")
                        return
            elif 'non_field_errors' in result:
                messagebox.showerror("Upload Error", f"Non-field error: {result['non_field_errors']}")
                return

    messagebox.showinfo("Upload Completed", "All calibrated files have been uploaded to BHTOM.")
    download_photometry_request(token, target_name, app)
