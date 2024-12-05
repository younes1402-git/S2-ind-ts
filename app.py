import streamlit as st
import ee
from datetime import date
import plotly.graph_objects as go
import pandas as pd
import folium
from folium import Map, TileLayer
from folium.plugins import Draw
from streamlit_folium import st_folium
import traceback

# Authenticate Earth Engine
try:
    ee.Initialize()
except ee.EEException:
    ee.Authenticate()
    ee.Initialize()

# Title and Sidebar Inputs
st.title("NDVI Time Series from Sentinel-2")
st.sidebar.header("User Input")
start_date = st.sidebar.date_input("Start Date", date(2020, 1, 1))
end_date = st.sidebar.date_input("End Date", date(2023, 1, 1))

# Convert dates to strings
start_date_str = start_date.strftime('%Y-%m-%d')
end_date_str = end_date.strftime('%Y-%m-%d')

# Map with Drawing Tools
st.sidebar.write("Draw a polygon or place a marker on the map to define your region of interest.")
m = Map(location=[36.59, 53.16], zoom_start=10)
TileLayer(
    tiles="https://{s}.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
    attr="Google",
    name="Google Satellite",
    max_zoom=20,
    subdomains=["mt0", "mt1", "mt2", "mt3"]
).add_to(m)

draw = Draw(export=True, filename='draw.geojson')
draw.add_to(m)
output = st_folium(m, width=700, height=500)

# Extract Geometry (Point or Polygon)
geometry = None
if output and 'last_active_drawing' in output:
    geojson = output['last_active_drawing']
    if geojson and geojson['geometry']['type'] == 'Polygon':
        try:
            coordinates = geojson['geometry']['coordinates']
            geometry = ee.Geometry.Polygon(coordinates)
            st.success("Polygon successfully created and passed to Earth Engine!")
        except Exception as e:
            st.error(f"Error creating polygon geometry: {e}")
    elif geojson and geojson['geometry']['type'] == 'Point':
        try:
            coordinates = geojson['geometry']['coordinates']
            geometry = ee.Geometry.Point(coordinates)
            st.success("Point successfully created and passed to Earth Engine!")
        except Exception as e:
            st.error(f"Error creating point geometry: {e}")
    else:
        st.error("Please draw a valid polygon or place a marker on the map.")
else:
    st.warning("No geometry detected. Draw a polygon or place a marker and press Finish.")

# Fetch Image Collection for NDVI
def get_ndvi_collection(start_date, end_date, geometry):
    def calculate_ndvi(image):
        # Calculate NDVI using the formula (NIR - RED) / (NIR + RED)
        ndvi = image.normalizedDifference(['B8', 'B4']).rename('NDVI')
        return image.addBands(ndvi)

    # Get the Sentinel-2 collection, filtered by date and region
    sentinel_collection = ee.ImageCollection('COPERNICUS/S2_SR') \
        .filterDate(start_date, end_date) \
        .filterBounds(geometry) \
        .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 20))  # Optional: Cloud filtering

    # Apply the NDVI calculation to each image in the collection
    ndvi_collection = sentinel_collection.map(calculate_ndvi)

    return ndvi_collection

# Compute NDVI Time Series
def compute_time_series(collection, geometry):
    def extract_ndvi(image):
        # Extract the date from the image
        date = image.get('system:time_start')

        # For point geometry: extract NDVI at the specific point
        if geometry.type().getInfo() == 'Point':
            ndvi_value = image.select('NDVI').reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=geometry,
                scale=10,  # Sentinel-2 has a resolution of 10 meters for RGB bands
                maxPixels=1e8
            ).get('NDVI')
        else:  # For polygon geometry, calculate mean NDVI over the region
            ndvi_value = image.select('NDVI').reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=geometry,
                scale=10,
                maxPixels=1e8
            ).get('NDVI')

        return ee.Feature(None, {
            'date': ee.Date(date).format('YYYY-MM-dd'),
            'ndvi': ndvi_value
        })

    # Map the extraction function over the collection
    ndvi_time_series = collection.map(extract_ndvi)

    # Convert the time series to a pandas dataframe
    try:
        ndvi_list = ndvi_time_series.getInfo()
    except Exception as e:
        st.error(f"Error fetching time series: {e}")
        return None

    return ndvi_list

# Plot Time Series (with Plotly)
def plot_time_series(data):
    dates = [entry['properties']['date'] for entry in data['features']]
    ndvi_values = [entry['properties']['ndvi'] for entry in data['features']]

    # Only display the first day of each month for x-axis labels
    months = []
    for date_str in dates:
        year_month = date_str[:7]  # Extract YYYY-MM
        if year_month not in months:
            months.append(year_month)

    # Create the plot using Plotly
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=dates,
        y=ndvi_values,
        mode='lines+markers',
        marker=dict(color='blue'),
        hovertemplate='Date: %{x}<br>NDVI: %{y}<extra></extra>'
    ))

    # Set the x-axis to show only the first day of each month
    fig.update_xaxes(tickvals=months, ticktext=months)

    fig.update_layout(
        title="NDVI Time Series",
        xaxis_title="Date",
        yaxis_title="NDVI",
        template="plotly_dark",
        showlegend=False
    )

    # Show the interactive plot
    st.plotly_chart(fig)

    # Generate the CSV file for download
    df = pd.DataFrame({'Date': dates, 'NDVI': ndvi_values})
    csv = df.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="Download as CSV",
        data=csv,
        file_name="ndvi_time_series.csv",
        mime="text/csv"
    )

    # Save the figure as PNG
    fig.write_image("ndvi_time_series.png")
    with open("ndvi_time_series.png", "rb") as png_file:
        st.download_button(
            label="Download as PNG",
            data=png_file,
            file_name="ndvi_time_series.png",
            mime="image/png"
        )

# Generate NDVI Time Series
if st.sidebar.button("Generate NDVI Time Series"):
    try:
        if not geometry:
            st.error("Please draw a polygon or place a marker on the map to define your region.")
        else:
            # Fetch the NDVI collection
            collection = get_ndvi_collection(start_date_str, end_date_str, geometry)

            # Compute the time series
            time_series_data = compute_time_series(collection, geometry)
            if time_series_data:
                # Plot the time series using Plotly
                plot_time_series(time_series_data)
    except Exception as e:
        st.error("An error occurred while generating the NDVI time series.")
        st.write(traceback.format_exc())
