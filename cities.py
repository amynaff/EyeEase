"""
cities.py — a small offline gazetteer, so people can say where they are
without knowing their own latitude.

Coordinates are city-centre, to four decimal places at most and often fewer.
That is deliberate: sunset moves by roughly one minute per 20km of longitude,
so a few kilometres of error is far below anything you could notice on a
screen that takes an hour to warm up. Anyone who wants exact numbers can
still type them — resolve() takes raw coordinates too.

This exists instead of a location lookup. Asking macOS for your position
means a permission prompt and an app that knows where you live; calling a
geolocation API means this thing talks to the network. Neither is a
reasonable trade for working out when the sun goes down, and a list of
cities in the binary costs about 20KB.

The list is hand-curated rather than generated, so it is not exhaustive —
it covers large cities and capitals. Pick the nearest one; being 50km off
shifts sunset by about two minutes.
"""

import math

from auto_schedule import parse_latitude, parse_longitude

# (name, region, latitude, longitude)
CITIES = [
    # -- United States
    ("New York", "NY, US", 40.7128, -74.0060),
    ("Los Angeles", "CA, US", 34.0522, -118.2437),
    ("Chicago", "IL, US", 41.8781, -87.6298),
    ("Houston", "TX, US", 29.7604, -95.3698),
    ("Phoenix", "AZ, US", 33.4484, -112.0740),
    ("Philadelphia", "PA, US", 39.9526, -75.1652),
    ("San Antonio", "TX, US", 29.4241, -98.4936),
    ("San Diego", "CA, US", 32.7157, -117.1611),
    ("Dallas", "TX, US", 32.7767, -96.7970),
    ("San Jose", "CA, US", 37.3382, -121.8863),
    ("Austin", "TX, US", 30.2672, -97.7431),
    ("Jacksonville", "FL, US", 30.3322, -81.6557),
    ("San Francisco", "CA, US", 37.7749, -122.4194),
    ("Columbus", "OH, US", 39.9612, -82.9988),
    ("Indianapolis", "IN, US", 39.7684, -86.1581),
    ("Seattle", "WA, US", 47.6062, -122.3321),
    ("Denver", "CO, US", 39.7392, -104.9903),
    ("Boston", "MA, US", 42.3601, -71.0589),
    ("Portland", "OR, US", 45.5152, -122.6784),
    ("Las Vegas", "NV, US", 36.1699, -115.1398),
    ("Detroit", "MI, US", 42.3314, -83.0458),
    ("Memphis", "TN, US", 35.1495, -90.0490),
    ("Baltimore", "MD, US", 39.2904, -76.6122),
    ("Milwaukee", "WI, US", 43.0389, -87.9065),
    ("Albuquerque", "NM, US", 35.0844, -106.6504),
    ("Tucson", "AZ, US", 32.2226, -110.9747),
    ("Sacramento", "CA, US", 38.5816, -121.4944),
    ("Kansas City", "MO, US", 39.0997, -94.5786),
    ("Atlanta", "GA, US", 33.7490, -84.3880),
    ("Miami", "FL, US", 25.7617, -80.1918),
    ("Raleigh", "NC, US", 35.7796, -78.6382),
    ("Minneapolis", "MN, US", 44.9778, -93.2650),
    ("New Orleans", "LA, US", 29.9511, -90.0715),
    ("Cleveland", "OH, US", 41.4993, -81.6944),
    ("Pittsburgh", "PA, US", 40.4406, -79.9959),
    ("St. Louis", "MO, US", 38.6270, -90.1994),
    ("Salt Lake City", "UT, US", 40.7608, -111.8910),
    ("Nashville", "TN, US", 36.1627, -86.7816),
    ("Oklahoma City", "OK, US", 35.4676, -97.5164),
    ("Charlotte", "NC, US", 35.2271, -80.8431),
    ("Tampa", "FL, US", 27.9506, -82.4572),
    ("Orlando", "FL, US", 28.5383, -81.3792),
    ("Buffalo", "NY, US", 42.8864, -78.8784),
    ("Boise", "ID, US", 43.6150, -116.2023),
    ("Anchorage", "AK, US", 61.2181, -149.9003),
    ("Honolulu", "HI, US", 21.3069, -157.8583),
    ("Omaha", "NE, US", 41.2565, -95.9345),
    ("Richmond", "VA, US", 37.5407, -77.4360),
    ("Providence", "RI, US", 41.8240, -71.4128),
    ("Hartford", "CT, US", 41.7658, -72.6734),
    ("Des Moines", "IA, US", 41.5868, -93.6250),
    ("Spokane", "WA, US", 47.6588, -117.4260),
    ("Reno", "NV, US", 39.5296, -119.8138),
    ("Santa Fe", "NM, US", 35.6870, -105.9378),
    ("Burlington", "VT, US", 44.4759, -73.2121),
    ("Portland", "ME, US", 43.6591, -70.2568),
    ("Fairbanks", "AK, US", 64.8378, -147.7164),
    # -- Canada
    ("Toronto", "ON, CA", 43.6532, -79.3832),
    ("Montreal", "QC, CA", 45.5019, -73.5674),
    ("Vancouver", "BC, CA", 49.2827, -123.1207),
    ("Calgary", "AB, CA", 51.0447, -114.0719),
    ("Ottawa", "ON, CA", 45.4215, -75.6972),
    ("Edmonton", "AB, CA", 53.5461, -113.4938),
    ("Winnipeg", "MB, CA", 49.8951, -97.1384),
    ("Halifax", "NS, CA", 44.6488, -63.5752),
    ("Quebec City", "QC, CA", 46.8139, -71.2080),
    ("Whitehorse", "YT, CA", 60.7212, -135.0568),
    # -- Latin America
    ("Mexico City", "MX", 19.4326, -99.1332),
    ("Guadalajara", "MX", 20.6597, -103.3496),
    ("Monterrey", "MX", 25.6866, -100.3161),
    ("Tijuana", "MX", 32.5149, -117.0382),
    ("Guatemala City", "GT", 14.6349, -90.5069),
    ("San José", "CR", 9.9281, -84.0907),
    ("Panama City", "PA", 8.9824, -79.5199),
    ("Bogotá", "CO", 4.7110, -74.0721),
    ("Medellín", "CO", 6.2442, -75.5812),
    ("Quito", "EC", -0.1807, -78.4678),
    ("Lima", "PE", -12.0464, -77.0428),
    ("La Paz", "BO", -16.4897, -68.1193),
    ("Santiago", "CL", -33.4489, -70.6693),
    ("Buenos Aires", "AR", -34.6037, -58.3816),
    ("Montevideo", "UY", -34.9011, -56.1645),
    ("Asunción", "PY", -25.2637, -57.5759),
    ("São Paulo", "BR", -23.5505, -46.6333),
    ("Rio de Janeiro", "BR", -22.9068, -43.1729),
    ("Brasília", "BR", -15.7975, -47.8919),
    ("Salvador", "BR", -12.9777, -38.5016),
    ("Manaus", "BR", -3.1190, -60.0217),
    ("Caracas", "VE", 10.4806, -66.9036),
    ("Havana", "CU", 23.1136, -82.3666),
    ("San Juan", "PR", 18.4655, -66.1057),
    ("Santo Domingo", "DO", 18.4861, -69.9312),
    ("Kingston", "JM", 17.9714, -76.7920),
    # -- Europe
    ("London", "GB", 51.5074, -0.1278),
    ("Manchester", "GB", 53.4808, -2.2426),
    ("Birmingham", "GB", 52.4862, -1.8904),
    ("Glasgow", "GB", 55.8642, -4.2518),
    ("Edinburgh", "GB", 55.9533, -3.1883),
    ("Dublin", "IE", 53.3498, -6.2603),
    ("Paris", "FR", 48.8566, 2.3522),
    ("Marseille", "FR", 43.2965, 5.3698),
    ("Lyon", "FR", 45.7640, 4.8357),
    ("Madrid", "ES", 40.4168, -3.7038),
    ("Barcelona", "ES", 41.3874, 2.1686),
    ("Seville", "ES", 37.3891, -5.9845),
    ("Lisbon", "PT", 38.7223, -9.1393),
    ("Porto", "PT", 41.1579, -8.6291),
    ("Rome", "IT", 41.9028, 12.4964),
    ("Milan", "IT", 45.4642, 9.1900),
    ("Naples", "IT", 40.8518, 14.2681),
    ("Berlin", "DE", 52.5200, 13.4050),
    ("Munich", "DE", 48.1351, 11.5820),
    ("Hamburg", "DE", 53.5511, 9.9937),
    ("Frankfurt", "DE", 50.1109, 8.6821),
    ("Cologne", "DE", 50.9375, 6.9603),
    ("Amsterdam", "NL", 52.3676, 4.9041),
    ("Rotterdam", "NL", 51.9244, 4.4777),
    ("Brussels", "BE", 50.8503, 4.3517),
    ("Zurich", "CH", 47.3769, 8.5417),
    ("Geneva", "CH", 46.2044, 6.1432),
    ("Vienna", "AT", 48.2082, 16.3738),
    ("Prague", "CZ", 50.0755, 14.4378),
    ("Warsaw", "PL", 52.2297, 21.0122),
    ("Kraków", "PL", 50.0647, 19.9450),
    ("Budapest", "HU", 47.4979, 19.0402),
    ("Bucharest", "RO", 44.4268, 26.1025),
    ("Sofia", "BG", 42.6977, 23.3219),
    ("Athens", "GR", 37.9838, 23.7275),
    ("Belgrade", "RS", 44.7866, 20.4489),
    ("Zagreb", "HR", 45.8150, 15.9819),
    ("Copenhagen", "DK", 55.6761, 12.5683),
    ("Stockholm", "SE", 59.3293, 18.0686),
    ("Gothenburg", "SE", 57.7089, 11.9746),
    ("Oslo", "NO", 59.9139, 10.7522),
    ("Bergen", "NO", 60.3913, 5.3221),
    ("Tromsø", "NO", 69.6492, 18.9553),
    ("Helsinki", "FI", 60.1699, 24.9384),
    ("Reykjavík", "IS", 64.1466, -21.9426),
    ("Tallinn", "EE", 59.4370, 24.7536),
    ("Riga", "LV", 56.9496, 24.1052),
    ("Vilnius", "LT", 54.6872, 25.2797),
    ("Kyiv", "UA", 50.4501, 30.5234),
    ("Moscow", "RU", 55.7558, 37.6173),
    ("Saint Petersburg", "RU", 59.9311, 30.3609),
    ("Istanbul", "TR", 41.0082, 28.9784),
    ("Ankara", "TR", 39.9334, 32.8597),
    # -- Africa & Middle East
    ("Cairo", "EG", 30.0444, 31.2357),
    ("Lagos", "NG", 6.5244, 3.3792),
    ("Abuja", "NG", 9.0765, 7.3986),
    ("Accra", "GH", 5.6037, -0.1870),
    ("Nairobi", "KE", -1.2921, 36.8219),
    ("Addis Ababa", "ET", 9.0320, 38.7469),
    ("Dar es Salaam", "TZ", -6.7924, 39.2083),
    ("Kampala", "UG", 0.3476, 32.5825),
    ("Johannesburg", "ZA", -26.2041, 28.0473),
    ("Cape Town", "ZA", -33.9249, 18.4241),
    ("Durban", "ZA", -29.8587, 31.0218),
    ("Casablanca", "MA", 33.5731, -7.5898),
    ("Marrakesh", "MA", 31.6295, -7.9811),
    ("Algiers", "DZ", 36.7538, 3.0588),
    ("Tunis", "TN", 36.8065, 10.1815),
    ("Dakar", "SN", 14.7167, -17.4677),
    ("Tel Aviv", "IL", 32.0853, 34.7818),
    ("Jerusalem", "IL", 31.7683, 35.2137),
    ("Amman", "JO", 31.9454, 35.9284),
    ("Beirut", "LB", 33.8938, 35.5018),
    ("Dubai", "AE", 25.2048, 55.2708),
    ("Abu Dhabi", "AE", 24.4539, 54.3773),
    ("Doha", "QA", 25.2854, 51.5310),
    ("Riyadh", "SA", 24.7136, 46.6753),
    ("Jeddah", "SA", 21.4858, 39.1925),
    ("Kuwait City", "KW", 29.3759, 47.9774),
    ("Tehran", "IR", 35.6892, 51.3890),
    # -- Asia
    ("Tokyo", "JP", 35.6762, 139.6503),
    ("Osaka", "JP", 34.6937, 135.5023),
    ("Kyoto", "JP", 35.0116, 135.7681),
    ("Sapporo", "JP", 43.0618, 141.3545),
    ("Seoul", "KR", 37.5665, 126.9780),
    ("Busan", "KR", 35.1796, 129.0756),
    ("Beijing", "CN", 39.9042, 116.4074),
    ("Shanghai", "CN", 31.2304, 121.4737),
    ("Guangzhou", "CN", 23.1291, 113.2644),
    ("Shenzhen", "CN", 22.5431, 114.0579),
    ("Chengdu", "CN", 30.5728, 104.0668),
    ("Hong Kong", "HK", 22.3193, 114.1694),
    ("Taipei", "TW", 25.0330, 121.5654),
    ("Manila", "PH", 14.5995, 120.9842),
    ("Singapore", "SG", 1.3521, 103.8198),
    ("Kuala Lumpur", "MY", 3.1390, 101.6869),
    ("Jakarta", "ID", -6.2088, 106.8456),
    ("Bangkok", "TH", 13.7563, 100.5018),
    ("Hanoi", "VN", 21.0285, 105.8542),
    ("Ho Chi Minh City", "VN", 10.8231, 106.6297),
    ("Phnom Penh", "KH", 11.5564, 104.9282),
    ("Yangon", "MM", 16.8661, 96.1951),
    ("Dhaka", "BD", 23.8103, 90.4125),
    ("Kolkata", "IN", 22.5726, 88.3639),
    ("Delhi", "IN", 28.7041, 77.1025),
    ("Mumbai", "IN", 19.0760, 72.8777),
    ("Bengaluru", "IN", 12.9716, 77.5946),
    ("Chennai", "IN", 13.0827, 80.2707),
    ("Hyderabad", "IN", 17.3850, 78.4867),
    ("Karachi", "PK", 24.8607, 67.0011),
    ("Lahore", "PK", 31.5204, 74.3587),
    ("Islamabad", "PK", 33.6844, 73.0479),
    ("Kathmandu", "NP", 27.7172, 85.3240),
    ("Colombo", "LK", 6.9271, 79.8612),
    ("Tashkent", "UZ", 41.2995, 69.2401),
    ("Almaty", "KZ", 43.2220, 76.8512),
    ("Ulaanbaatar", "MN", 47.8864, 106.9057),
    ("Vladivostok", "RU", 43.1332, 131.9113),
    ("Novosibirsk", "RU", 55.0084, 82.9357),
    # -- Oceania
    ("Sydney", "AU", -33.8688, 151.2093),
    ("Melbourne", "AU", -37.8136, 144.9631),
    ("Brisbane", "AU", -27.4698, 153.0251),
    ("Perth", "AU", -31.9505, 115.8605),
    ("Adelaide", "AU", -34.9285, 138.6007),
    ("Canberra", "AU", -35.2809, 149.1300),
    ("Hobart", "AU", -42.8821, 147.3272),
    ("Darwin", "AU", -12.4634, 130.8456),
    ("Auckland", "NZ", -36.8485, 174.7633),
    ("Wellington", "NZ", -41.2866, 174.7756),
    ("Christchurch", "NZ", -43.5321, 172.6362),
    ("Suva", "FJ", -18.1248, 178.4501),
    ("Port Moresby", "PG", -9.4438, 147.1803),
]


def _fold(text: str) -> str:
    """Lowercase and strip accents, so "sao paulo" finds "São Paulo"."""
    import unicodedata

    stripped = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in stripped if unicodedata.category(c) != "Mn")


def search(query: str, limit: int = 6):
    """Cities matching `query`, best first.

    Prefix matches rank above interior ones so typing "san" offers San
    Francisco before Santa Fe's neighbours — the thing you're partway through
    typing is more likely the thing you mean.
    """
    q = _fold(query).strip()
    if not q:
        return []

    starts, contains = [], []
    for entry in CITIES:
        name = _fold(entry[0])
        haystack = f"{name} {_fold(entry[1])}"
        if name.startswith(q):
            starts.append(entry)
        elif q in haystack:
            contains.append(entry)
    return (starts + contains)[:limit]


def nearest_label(latitude: float, longitude: float, within_km: float = 120.0):
    """Name the closest known city, or fall back to the raw numbers.

    Used to show a saved location back as a place rather than a pair of
    decimals. Coordinates typed by hand, or a town that isn't in the list,
    stay as numbers instead of being relabelled as a city the user never
    chose — claiming "London" when they entered somewhere 80km away would
    be worse than showing the truth.
    """
    best, best_km = None, None
    for name, region, lat, lon in CITIES:
        # Equirectangular approximation: plenty at this range, and it avoids
        # pulling in anything to do great-circle distance properly.
        dlat = lat - latitude
        dlon = (lon - longitude) * math.cos(math.radians((lat + latitude) / 2))
        km = math.hypot(dlat, dlon) * 111.32
        if best_km is None or km < best_km:
            best, best_km = (name, region), km

    if best is not None and best_km <= within_km:
        return f"{best[0]}, {best[1]}"
    return f"{latitude:.4f}, {longitude:.4f}"


def resolve(query: str):
    """Turn typed text into (label, latitude, longitude), or None.

    Accepts a city name or a raw "lat, lon" pair, so the same single field
    serves someone who knows exactly where they are and someone who only
    knows what their city is called.
    """
    if query is None:
        return None
    text = query.strip()
    if not text:
        return None

    if "," in text:
        left, _, right = text.partition(",")
        lat = parse_latitude(left)
        lon = parse_longitude(right)
        if lat is not None and lon is not None:
            # Echoed back at the precision it was given, near enough:
            # %g would print 37.7749 as "37.77" and look like the app had
            # quietly thrown away what was typed.
            return (f"{lat:.4f}, {lon:.4f}".replace(".0000", ""), lat, lon)

    matches = search(text, limit=1)
    if matches:
        name, region, lat, lon = matches[0]
        return (f"{name}, {region}", lat, lon)
    return None
