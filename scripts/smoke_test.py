#!/usr/bin/env python3
"""Vérification de bout en bout de la plateforme.

Teste l'API module par module et distingue clairement trois cas :
  * ce qui marche ;
  * ce qui est désactivé faute de configuration (normal) ;
  * ce qui est réellement cassé.

Écrit en Python plutôt qu'en shell pour se comporter identiquement sous
Windows, macOS et Linux.

    python scripts/smoke_test.py
    python scripts/smoke_test.py --url http://localhost:8000
    python scripts/smoke_test.py --quick     # ignore les services externes lents
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

DEFAULT_URL = "http://127.0.0.1:8000"

# Couleurs ANSI, désactivées si le terminal ne suit pas
if sys.platform == "win32":
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleMode(
            ctypes.windll.kernel32.GetStdHandle(-11), 7
        )
        COLOR = True
    except Exception:
        COLOR = False
else:
    COLOR = sys.stdout.isatty()


def paint(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if COLOR else text


def green(t): return paint(t, "0;32")
def red(t): return paint(t, "0;31")
def yellow(t): return paint(t, "0;33")
def cyan(t): return paint(t, "0;36")
def dim(t): return paint(t, "2")


class Result:
    OK = "ok"
    DISABLED = "disabled"
    BROKEN = "broken"


def call(url: str, path: str, payload: dict | None = None, timeout: int = 45):
    """Appelle l'API. Retourne (statut_http, données, durée_ms)."""
    full = url + path
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    request = urllib.request.Request(full, data=data, headers=headers)
    start = time.time()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode())
            return response.status, body, int((time.time() - start) * 1000)
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode())
        except Exception:
            body = {"detail": exc.reason}
        return exc.code, body, int((time.time() - start) * 1000)
    except Exception as exc:
        return 0, {"detail": str(exc)}, int((time.time() - start) * 1000)


def wait_for_api(url: str, seconds: int = 30) -> bool:
    print(cyan(f"Connexion à {url} …"), end=" ", flush=True)
    for _ in range(seconds):
        status, _, _ = call(url, "/health", timeout=3)
        if status == 200:
            print(green("OK"))
            return True
        time.sleep(1)
    print(red("échec"))
    return False


def report(name: str, verdict: str, detail: str = "", ms: int | None = None) -> str:
    marks = {
        Result.OK: green("  OK    "),
        Result.DISABLED: yellow("  INACTIF"),
        Result.BROKEN: red("  ERREUR"),
    }
    timing = dim(f" {ms} ms") if ms and ms > 1500 else ""
    print(f"{marks[verdict]} {name:<34}{dim(detail)}{timing}")
    return verdict


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--quick", action="store_true", help="ignore les services externes lents")
    args = parser.parse_args()
    url = args.url.rstrip("/")

    if not wait_for_api(url):
        print()
        print(red("L'API ne répond pas."))
        print()
        print("Démarrez-la dans un autre terminal :")
        print(cyan("  cd apps/api"))
        if sys.platform == "win32":
            print(cyan(r"  ..\..\.venv\Scripts\python.exe -m uvicorn pratisig_api.main:app --port 8000"))
        else:
            print(cyan("  ../../.venv/bin/python -m uvicorn pratisig_api.main:app --port 8000"))
        return 1

    results: list[str] = []
    dakar = {"center": [-17.44, 14.69], "radius_m": 1200}

    # ── Socle : doit fonctionner sans réseau externe ──────────────
    print()
    print(cyan("── Socle (hors ligne) ──"))

    status, health, _ = call(url, "/health")
    services = health.get("services", {})
    results.append(report("API et catalogue", Result.OK if status == 200 else Result.BROKEN))

    for path, key, label in [
        ("/api/catalog", "modules", "Catalogue des modules"),
        ("/api/overture/themes", "themes", "Thèmes Overture"),
        ("/api/osm/presets", "presets", "Gabarits OSM"),
        ("/api/buildings/countries", "countries", "Liste des pays"),
        ("/api/agriculture/crops", "crops", "Base de cultures"),
        ("/api/land/references", "cities", "Villes de référence"),
        ("/api/spatial/operations", "operations", "Opérations spatiales"),
        ("/api/exports/formats", "formats", "Formats d'export"),
    ]:
        status, body, ms = call(url, path)
        count = len(body.get(key, [])) if status == 200 else 0
        results.append(
            report(label, Result.OK if count else Result.BROKEN, f"{count} entrées", ms)
        )

    # Analyse spatiale locale : aucun réseau requis
    points = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-17.44, 14.69]},
             "properties": {"n": 1}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-17.46, 14.71]},
             "properties": {"n": 2}},
        ],
    }
    status, body, ms = call(url, "/api/spatial/run",
                            {"operation": "buffer", "layer_a": points, "params": {"radius_m": 500}})
    results.append(report("Analyse spatiale (buffer)",
                          Result.OK if status == 200 else Result.BROKEN,
                          body.get("detail", "") if status != 200 else "", ms))

    if args.quick:
        print()
        print(dim("Services externes ignorés (--quick)."))
        return summary(results, services)

    # ── Services externes : le point que je n'ai pas pu valider ───
    print()
    print(cyan("── Services externes (réseau requis) ──"))

    checks = [
        ("Géocodage (Nominatim)", "GET", "/api/geocoding/search?q=Dakar&limit=1", None, "results"),
        ("Limites admin (GADM)", "GET", "/api/admin/senegal/regions?with_geometry=false", None, "features"),
        ("OpenStreetMap (Overpass)", "POST", "/api/osm/query",
         {"preset": "health", "area": dakar, "limit": 30}, "features"),
        ("Itinéraire (OSRM)", "POST", "/api/routing/route",
         {"waypoints": [[-17.44, 14.69], [-16.92, 14.79]], "profile": "car"}, "features"),
        ("Isochrone (OSRM)", "POST", "/api/routing/isochrone",
         {"center": [-17.44, 14.69], "minutes": [10], "profile": "car"}, "features"),
        ("Climat (NASA POWER)", "POST", "/api/climate/timeseries",
         {"latitude": 14.69, "longitude": -17.44, "start": "2024-06-01", "end": "2024-08-31"}, "dates"),
        ("Bâtiments (source.coop)", "POST", "/api/buildings/query",
         {"country_iso3": "SEN", "area": dakar, "limit": 200}, "features"),
        ("Overture Maps (S3)", "POST", "/api/overture/query",
         {"theme": "places", "area": dakar, "limit": 50}, "features"),
        ("Foncier (multi-sources)", "POST", "/api/land/analyze",
         {"latitude": 14.75, "longitude": -17.30, "include_services": False}, "score"),
    ]

    for label, method, path, payload, key in checks:
        status, body, ms = call(url, path, payload if method == "POST" else None)
        if status == 200:
            value = body.get(key)
            count = len(value) if isinstance(value, (list, dict)) else 1
            note = f"{count} résultats" if isinstance(value, list) else "réponse valide"

            # Un HTTP 200 ne suffit pas : certains modules répondent en mode
            # dégradé quand une source externe manque. Il faut le dire.
            meta = body.get("metadata", {}) if isinstance(body, dict) else {}
            if meta.get("approximate"):
                results.append(report(label, Result.BROKEN,
                                      f"repli approximatif ({meta.get('engine', '?')})", ms))
                continue
            if isinstance(value, dict) and value.get("reliable") is False:
                results.append(report(label, Result.BROKEN,
                                      f"couverture {value.get('coverage_pct')} % — non concluant", ms))
                continue
            if isinstance(value, list) and not value:
                results.append(report(label, Result.BROKEN, "réponse vide", ms))
                continue

            results.append(report(label, Result.OK, note, ms))
        elif status in (502, 503, 504):
            results.append(report(label, Result.BROKEN,
                                  f"service injoignable : {str(body.get('detail', ''))[:45]}", ms))
        elif status == 422:
            results.append(report(label, Result.DISABLED,
                                  f"aucune donnée : {str(body.get('detail', ''))[:45]}", ms))
        else:
            results.append(report(label, Result.BROKEN,
                                  f"HTTP {status} {str(body.get('detail', ''))[:40]}", ms))

    # ── Modules optionnels ────────────────────────────────────────
    print()
    print(cyan("── Modules optionnels ──"))
    for key, label, variable in [
        ("earthengine", "Imagerie et inondations", "PRATISIG_GEE_SERVICE_ACCOUNT_*"),
        ("llm", "Assistant cartographique", "PRATISIG_LLM_API_KEY"),
        ("geopandas", "Exports GeoPackage/Shapefile", "requirements-full.txt"),
        ("isochrone_shapes", "Isochrones en alpha-shape", "scipy"),
    ]:
        service = services.get(key, {})
        if service.get("status") == "ok":
            results.append(report(label, Result.OK))
        else:
            results.append(report(label, Result.DISABLED, f"nécessite {variable}"))

    return summary(results, services)


def summary(results: list[str], services: dict) -> int:
    ok = results.count(Result.OK)
    disabled = results.count(Result.DISABLED)
    broken = results.count(Result.BROKEN)

    print()
    print(cyan("── Bilan ──"))
    print(f"  {green(str(ok))} fonctionnels · {yellow(str(disabled))} inactifs · {red(str(broken))} en erreur")
    print()

    if broken:
        print(red("Des services sont en erreur."))
        print("  Réseau injoignable ? Testez : ", end="")
        print(cyan("curl https://nominatim.openstreetmap.org/status.php"))
        print("  Si l'erreur persiste, envoyez cette sortie complète.")
        return 1

    print(green("La plateforme fonctionne."))
    if disabled:
        print(dim("  Les modules inactifs demandent une configuration ; c'est normal."))
    print()
    print("  Interface : " + cyan("http://localhost:5173"))
    print("  API       : " + cyan("http://localhost:8000/docs"))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrompu.")
        sys.exit(130)
