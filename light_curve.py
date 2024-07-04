import matplotlib.pyplot as plt


def display_light_curve(light_curve_data):
    times = [point['time'] for point in light_curve_data]
    magnitudes = [point['magnitude'] for point in light_curve_data]

    plt.plot(times, magnitudes, 'o-')
    plt.xlabel('Time')
    plt.ylabel('Magnitude')
    plt.title('Light Curve')
    plt.gca().invert_yaxis()  # Magnitude decreases as brightness increases
    plt.show()
