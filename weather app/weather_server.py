import json
import calendar
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import urlopen


APP_DIRECTORY = Path(__file__).resolve().parent
WEATHER_CODES = {
    0: ("clear sky", "01"),
    1: ("mainly clear", "02"),
    2: ("partly cloudy", "02"),
    3: ("overcast", "04"),
    45: ("fog", "50"),
    48: ("rime fog", "50"),
    51: ("light drizzle", "09"),
    53: ("drizzle", "09"),
    55: ("heavy drizzle", "09"),
    56: ("freezing drizzle", "13"),
    57: ("heavy freezing drizzle", "13"),
    61: ("light rain", "10"),
    63: ("rain", "10"),
    65: ("heavy rain", "10"),
    66: ("freezing rain", "13"),
    67: ("heavy freezing rain", "13"),
    71: ("light snow", "13"),
    73: ("snow", "13"),
    75: ("heavy snow", "13"),
    77: ("snow grains", "13"),
    80: ("light rain showers", "09"),
    81: ("rain showers", "09"),
    82: ("heavy rain showers", "09"),
    85: ("light snow showers", "13"),
    86: ("heavy snow showers", "13"),
    95: ("thunderstorm", "11"),
    96: ("thunderstorm with hail", "11"),
    99: ("heavy thunderstorm with hail", "11"),
}


def fetch_json(url):
    with urlopen(url, timeout=12) as response:
        return json.loads(response.read())


def local_time_as_timestamp(value, timezone_offset):
    local_time = datetime.fromisoformat(value)
    return calendar.timegm(local_time.timetuple()) - timezone_offset


def normalize_weather(place, forecast):
    current = forecast["current"]
    daily = forecast["daily"]
    timezone_offset = forecast["utc_offset_seconds"]
    description, icon_code = WEATHER_CODES.get(current["weather_code"], ("unknown", "01"))
    icon = f"{icon_code}{'d' if current['is_day'] else 'n'}"
    current_time = local_time_as_timestamp(current["time"], timezone_offset)

    return {
        "name": place["name"],
        "sys": {
            "country": place.get("country_code", ""),
            "sunrise": local_time_as_timestamp(daily["sunrise"][0], timezone_offset),
            "sunset": local_time_as_timestamp(daily["sunset"][0], timezone_offset),
        },
        "timezone": timezone_offset,
        "dt": current_time,
        "main": {
            "temp": current["temperature_2m"],
            "feels_like": current["apparent_temperature"],
            "humidity": current["relative_humidity_2m"],
        },
        "weather": [{"description": description, "icon": icon}],
        "wind": {"speed": round(current["wind_speed_10m"] / 3.6, 1)},
        "visibility": current["visibility"],
    }


class WeatherRequestHandler(BaseHTTPRequestHandler):
    def send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        request = urlsplit(self.path)

        if request.path in ("/", "/index.html"):
            page = (APP_DIRECTORY / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
            return

        if request.path != "/api/weather":
            self.send_json(404, {"message": "Not found."})
            return

        city = parse_qs(request.query, keep_blank_values=True).get("q", [""])[0].strip()
        if not city:
            self.send_json(400, {"message": "Enter a city to search."})
            return

        try:
            geocoding_query = urlencode({"name": city, "count": 1, "language": "en", "format": "json"})
            places = fetch_json(f"https://geocoding-api.open-meteo.com/v1/search?{geocoding_query}").get("results", [])
            if not places:
                self.send_json(404, {"message": "We couldn't find that city. Check the spelling and try again."})
                return

            place = places[0]
            forecast_query = urlencode({
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "current": "temperature_2m,relative_humidity_2m,apparent_temperature,is_day,weather_code,wind_speed_10m,visibility",
                "daily": "sunrise,sunset",
                "timezone": "auto",
                "forecast_days": 1,
            })
            forecast = fetch_json(f"https://api.open-meteo.com/v1/forecast?{forecast_query}")
        except (HTTPError, TimeoutError, URLError, ValueError, KeyError):
            self.send_json(502, {"message": "Could not reach the weather service. Try again shortly."})
            return

        self.send_json(200, normalize_weather(place, forecast))


if __name__ == "__main__":
    address = ("127.0.0.1", 8000)
    server = ThreadingHTTPServer(address, WeatherRequestHandler)
    print(f"Daylight is running at http://{address[0]}:{address[1]}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Daylight.")
    finally:
        server.server_close()