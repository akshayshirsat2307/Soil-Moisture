"""
Daily India Soil Moisture Actual / Normal / Departure Export
================================================================
Run via GitHub Actions on a schedule. Reads the Earth Engine service
account key from the EE_SERVICE_ACCOUNT_KEY environment variable
(set from a GitHub Secret), computes actual vs. 5-year-normal soil
moisture for a rolling window, and starts export tasks to Google Drive.

This script returns as soon as the export tasks are STARTED - Earth
Engine generates the actual GeoTIFFs on its own servers afterward.
"""

import os
import json
import datetime
import ee

# ----------------------------------------------------------
# CONFIG - edit these
# ----------------------------------------------------------
BAND = 'sm_surface'          # or 'sm_rootzone'
LAG_DAYS = 3                 # days behind "today" for the window's end date
WINDOW_DAYS = 9              # length of the averaging window
NORMAL_YEARS_BACK = 5        # how many previous years count as "normal"
DRIVE_FOLDER = 'GEE_exports'


def init_earth_engine():
    key_json = os.environ['EE_SERVICE_ACCOUNT_KEY']  # full JSON key as a string
    key_data = json.loads(key_json)
    credentials = ee.ServiceAccountCredentials(
        key_data['client_email'], key_data=key_json
    )
    ee.Initialize(credentials)


def india_geometry():
    india = ee.FeatureCollection('USDOS/LSIB_SIMPLE/2017') \
        .filter(ee.Filter.eq('country_na', 'India'))
    return india.geometry()


def period_mean(collection, start_date, end_date):
    return collection.filterDate(start_date, end_date).mean()


def run_export():
    init_earth_engine()
    india_geom = india_geometry()
    smap = ee.ImageCollection('NASA/SMAP/SPL4SMGP/008').select(BAND)

    today = datetime.date.today()
    window_end = today - datetime.timedelta(days=LAG_DAYS)
    window_start = window_end - datetime.timedelta(days=WINDOW_DAYS - 1)

    current_start_str = window_start.isoformat()
    current_end_str = (window_end + datetime.timedelta(days=1)).isoformat()

    actual = period_mean(smap, current_start_str, current_end_str) \
        .clip(india_geom).rename('sm_actual')

    years = [window_end.year - i for i in range(1, NORMAL_YEARS_BACK + 1)]
    yearly_images = []
    for y in years:
        try:
            y_start = window_start.replace(year=y)
            y_end = window_end.replace(year=y)
        except ValueError:
            y_start = window_start.replace(year=y, day=28)
            y_end = window_end.replace(year=y, day=28)
        y_start_str = y_start.isoformat()
        y_end_str = (y_end + datetime.timedelta(days=1)).isoformat()
        yearly_images.append(period_mean(smap, y_start_str, y_end_str))

    normal = ee.ImageCollection.fromImages(yearly_images).mean() \
        .clip(india_geom).rename('sm_normal')

    departure = actual.subtract(normal).rename('sm_departure')
    departure_pct = departure.divide(normal).multiply(100).rename('sm_departure_pct')

    date_tag = window_end.strftime('%Y%m%d')
    for name, image in [
        (f'India_SoilMoisture_Actual_{date_tag}', actual),
        (f'India_SoilMoisture_Normal_{date_tag}', normal),
        (f'India_SoilMoisture_Departure_{date_tag}', departure),
        (f'India_SoilMoisture_DeparturePct_{date_tag}', departure_pct),
    ]:
        task = ee.batch.Export.image.toDrive(
            image=image,
            description=name,
            folder=DRIVE_FOLDER,
            region=india_geom,
            scale=11000,
            crs='EPSG:4326',
            maxPixels=1e13,
        )
        task.start()
        print(f"Started export task: {name}")

    print(f"Window: {current_start_str} to {window_end.isoformat()}")
    print(f"Normal years used: {years}")


if __name__ == '__main__':
    run_export()
