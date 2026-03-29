from typing import Annotated
from langchain_core.tools import tool

@tool
def get_current_weather(
    city: Annotated[str, "Name of the US city (e.g., 'Seattle', 'New York')"],
    state: Annotated[str, "Two-letter state code (e.g., 'WA', 'NY')"],
) -> str:
    """Get the current observed weather conditions for a US city using the National Weather Service API."""
    try:
        import httpx
        from urllib.parse import quote
        
        # First, geocode the city to get coordinates
        geocode_url = f"https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
        params = {
            "address": f"{city}, {state}",
            "benchmark": "Public_AR_Current",
            "format": "json"
        }
        
        with httpx.Client(timeout=10.0) as client:
            geo_response = client.get(geocode_url, params=params)
            geo_response.raise_for_status()
            geo_data = geo_response.json()
            
            if not geo_data.get("result", {}).get("addressMatches"):
                return f"Error: Could not find location for {city}, {state}"
            
            coords = geo_data["result"]["addressMatches"][0]["coordinates"]
            lat, lon = coords["y"], coords["x"]
            
            # Get the weather station from NWS points API
            points_url = f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}"
            points_response = client.get(points_url, headers={"User-Agent": "JARVIS-Assistant"})
            points_response.raise_for_status()
            points_data = points_response.json()
            
            # Get observation stations
            stations_url = points_data["properties"]["observationStations"]
            stations_response = client.get(stations_url, headers={"User-Agent": "JARVIS-Assistant"})
            stations_response.raise_for_status()
            stations_data = stations_response.json()
            
            if not stations_data.get("features"):
                return f"Error: No weather stations found near {city}, {state}"
            
            # Get latest observation from first station
            station_id = stations_data["features"][0]["properties"]["stationIdentifier"]
            obs_url = f"https://api.weather.gov/stations/{station_id}/observations/latest"
            obs_response = client.get(obs_url, headers={"User-Agent": "JARVIS-Assistant"})
            obs_response.raise_for_status()
            obs_data = obs_response.json()
            
            props = obs_data["properties"]
            
            # Extract weather data
            temp_c = props.get("temperature", {}).get("value")
            temp_f = (temp_c * 9/5) + 32 if temp_c is not None else None
            
            description = props.get("textDescription", "N/A")
            humidity = props.get("relativeHumidity", {}).get("value")
            wind_speed = props.get("windSpeed", {}).get("value")
            wind_dir = props.get("windDirection", {}).get("value")
            
            # Format response
            result = f"Current weather in {city}, {state}:\n"
            result += f"Conditions: {description}\n"
            if temp_f is not None:
                result += f"Temperature: {temp_f:.1f}°F ({temp_c:.1f}°C)\n"
            if humidity is not None:
                result += f"Humidity: {humidity:.0f}%\n"
            if wind_speed is not None and wind_dir is not None:
                result += f"Wind: {wind_speed:.1f} km/h from {wind_dir:.0f}°\n"
            
            return result.strip()
            
    except httpx.HTTPError as e:
        return f"Error fetching weather data: {str(e)}"
    except KeyError as e:
        return f"Error parsing weather data: missing field {str(e)}"
    except Exception as e:
        return f"Unexpected error: {str(e)}"