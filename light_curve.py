import matplotlib.pyplot as plt
import plotly.graph_objs as go
from plotly.subplots import make_subplots
from astropy.time import Time
import random
import io
from PIL import Image, ImageTk
import tkinter as tk
from tkinter import Button, messagebox
import tempfile
import plotly.io as pio
import webbrowser
import requests  # Ensure requests is imported here


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


# Ensure that the generated color is not too light
def generate_non_white_color():
    while True:
        color = f'#{random.randint(0, 0xFFFFFF):06x}'
        r, g, b = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
        if (r + g + b) < 700:  # Avoid light colors
            return color


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
    observer_colors = {obs: generate_non_white_color() for obs in unique_observers}
    obs_filter_colors = {}

    for obs in unique_observers:
        obs_filters = list(set([filter_name[i] for i in range(len(observer)) if observer[i] == obs]))
        n_filters = len(obs_filters)
        for i, filt in enumerate(obs_filters):
            shade_factor = 1 - (i / (n_filters + 1))
            base_color = observer_colors[obs]
            obs_filter_colors[(obs, filt)] = adjust_color_shade(base_color, shade_factor)

    # Create a Plotly figure with adjusted dimensions
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
                marker=dict(color=filt_color, size=4),  # Keep the same size for dots
                line=dict(width=0.75)  # Keep the same width for lines
            ))

    # Adjust the layout to fit the window size
    fig.update_layout(
        title="Light Curve",
        xaxis_title="Date (DD-MM-YYYY)",
        yaxis_title="Magnitude",
        yaxis_autorange='reversed',  # Common in astronomy for magnitudes
        height=500,  # Adjust the height to fit the Tkinter window
        width=1200,  # Adjust the width to fit the Tkinter window
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

    # Set the size of the window
    light_curve_window.geometry("1200x550")

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
