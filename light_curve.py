import matplotlib.pyplot as plt

def display_light_curve(light_curve_data):
    mjd = [point['mjd'] for point in light_curve_data]
    magnitude = [point['magnitude'] for point in light_curve_data]
    error = [point['error'] for point in light_curve_data]

    plt.errorbar(mjd, magnitude, yerr=error, fmt='o')
    plt.gca().invert_yaxis()  # Magnitudes are typically plotted in reverse
    plt.xlabel('MJD')
    plt.ylabel('Magnitude')
    plt.title('Light Curve')
    plt.show()
