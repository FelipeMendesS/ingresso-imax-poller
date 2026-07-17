"""One-time helper: discover the city / theater / film IDs to paste into config.py.

Usage examples:
    python discover_ids.py                          # defaults: SP / São Paulo / cinepolis / JK Iguatemi / Odisseia
    python discover_ids.py --uf RJ --city "Rio de Janeiro" --partnership cinemark
    python discover_ids.py --theater "Iguatemi" --film "Avatar"

It prints matching IDs so you can copy them into the WATCH block in config.py.
Nothing is written automatically.
"""

import argparse

import fetcher  # reuse the same UA/jitter HTTP helper
import config


def find_city(uf, city_name):
    data = fetcher._http_get_json(config.CITIES_BY_STATE_URL.format(uf=uf.upper()))
    cities = data.get("cities", []) if isinstance(data, dict) else []
    needle = city_name.strip().lower()
    matches = [c for c in cities if needle in (c.get("name") or "").lower()]
    return matches, cities


def find_theaters(city_id, partnership, theater_name):
    data = fetcher._http_get_json(
        config.THEATERS_BY_CITY_URL.format(city_id=city_id, partnership=partnership)
    )
    theaters = data if isinstance(data, list) else data.get("items", [])
    needle = theater_name.strip().lower()
    matches = [t for t in theaters if needle in (t.get("name") or "").lower()]
    return matches, theaters


def find_films(city_id, theater_id, partnership, film_name):
    url = config.SESSIONS_BY_THEATER_URL.format(
        city_id=city_id, theater_id=theater_id, partnership=partnership
    )
    raw = fetcher._http_get_json(url)
    needle = film_name.strip().lower()
    seen, matches = {}, {}
    for day in raw or []:
        for movie in day.get("movies") or []:
            mid, title = str(movie.get("id")), movie.get("title") or ""
            seen[mid] = title
            if needle in title.lower():
                matches[mid] = title
    return matches, seen


def main():
    p = argparse.ArgumentParser(description="Discover Ingresso city/theater/film IDs")
    p.add_argument("--uf", default="SP", help="state code, e.g. SP, RJ")
    p.add_argument("--city", default="São Paulo", help="city name substring")
    p.add_argument("--partnership", default="cinepolis", help="cinema chain / partnership")
    p.add_argument("--theater", default="JK Iguatemi", help="theater name substring")
    p.add_argument("--film", default="Odisseia", help="film title substring")
    args = p.parse_args()

    print("== Cities in %s matching %r ==" % (args.uf.upper(), args.city))
    city_matches, all_cities = find_city(args.uf, args.city)
    for c in city_matches:
        print("  city_id=%s  %s" % (c.get("id"), c.get("name")))
    if not city_matches:
        print("  (no match; %d cities available in %s)" % (len(all_cities), args.uf.upper()))
        return
    city_id = city_matches[0]["id"]

    print("\n== '%s' theaters in city %s matching %r ==" % (
        args.partnership, city_id, args.theater))
    th_matches, all_th = find_theaters(city_id, args.partnership, args.theater)
    for t in th_matches:
        print("  theater_id=%s  %s" % (t.get("id"), t.get("name")))
    if not th_matches:
        print("  (no match). All %s theaters in city %s:" % (args.partnership, city_id))
        for t in all_th:
            print("    theater_id=%s  %s" % (t.get("id"), t.get("name")))
        return
    theater_id = th_matches[0]["id"]

    print("\n== Films now at theater %s matching %r ==" % (theater_id, args.film))
    film_matches, all_films = find_films(city_id, theater_id, args.partnership, args.film)
    for mid, title in film_matches.items():
        print("  film_id=%s  %s" % (mid, title))
    if not film_matches:
        print("  (no match). Films currently listed at theater %s:" % theater_id)
        for mid, title in sorted(all_films.items(), key=lambda kv: kv[1]):
            print("    film_id=%s  %s" % (mid, title))
        return

    print("\n--- Paste into config.py WATCH ---")
    print('  "city_id": "%s",' % city_id)
    print('  "theater_id": "%s",' % theater_id)
    print('  "partnership": "%s",' % args.partnership)
    for mid, title in film_matches.items():
        print('  "film_id": "%s",   # %s' % (mid, title))
        break


if __name__ == "__main__":
    main()
