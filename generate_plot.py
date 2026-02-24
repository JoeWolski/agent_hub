import numpy as np
from scipy import stats
import plotly.graph_objects as go
import os

def generate_example_plot():
    # Generate data using scipy
    x = np.linspace(-5, 5, 100)
    y = stats.norm.pdf(x, 0, 1)

    # Create plot using plotly
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=y, mode='lines', name='Normal Distribution'))

    fig.update_layout(
        title='Example Plot (Normal Distribution)',
        xaxis_title='Value',
        yaxis_title='Probability Density',
        template='plotly_dark'
    )

    # Save as PNG
    output_path = 'example_plot.png'
    fig.write_image(output_path)
    print(f"Plot saved to {output_path}")

if __name__ == "__main__":
    generate_example_plot()
