#!/usr/bin/env python3
"""Diagnostic DuckDB : inspecte les schémas distants réels.

Deux erreurs ne se reproduisent pas sans accès réseau à source.coop et à S3 :

  * « Binder Error » sur Open Buildings — une colonne interrogée n'existe pas
    dans le GeoParquet ;
  * « No files found » sur Overture — la version de release configurée est
    introuvable sur S3.

Ce script lit les schémas réels et propose la configuration correcte.

    python scripts/diagnose_duckdb.py
"""

from __future__ import annotations

import sys

VIDA_BASE = "https://data.source.coop/vida/google-microsoft-open-buildings/geoparquet/by_country"
OVERTURE_S3 = "s3://overturemaps-us-west-2/release"
OVERTURE_HTTPS = "https://overturemaps-us-west-2.s3.amazonaws.com/release"

# Versions Overture à tester, de la plus récente à la plus ancienne
CANDIDATE_RELEASES = [
    "2025-06-25.0", "2025-05-21.0", "2025-04-23.0", "2025-03-19.0",
    "2025-02-19.0", "2025-01-22.0", "2024-12-18.0", "2024-11-13.0",
]


def connect():
    import duckdb

    conn = duckdb.connect(":memory:")
    for ext in ("spatial", "httpfs"):
        try:
            conn.execute(f"INSTALL {ext}; LOAD {ext};")
        except Exception as exc:
            print(f"  extension {ext} indisponible : {exc}")
    conn.execute("SET s3_region='us-west-2';")
    return conn


def inspect_buildings(conn, iso3: str = "SEN") -> None:
    print("=" * 68)
    print(f"OPEN BUILDINGS — schéma réel du parquet {iso3}")
    print("=" * 68)
    url = f"{VIDA_BASE}/country_iso={iso3}/{iso3}.parquet"
    print(f"Source : {url}\n")

    try:
        rows = conn.execute(f"DESCRIBE SELECT * FROM read_parquet('{url}') LIMIT 1").fetchall()
    except Exception as exc:
        print(f"ÉCHEC : {exc}")
        return

    print(f"{'colonne':<28} {'type'}")
    print("-" * 68)
    names = []
    for row in rows:
        names.append(row[0])
        print(f"{row[0]:<28} {row[1]}")

    print("\nColonnes attendues par la plateforme :")
    for expected in ("bbox", "confidence", "area_in_meters", "bf_source", "geometry", "id"):
        mark = "OK  " if expected in names else "MANQUE"
        print(f"  {mark}  {expected}")

    if "bbox" in names:
        try:
            bbox_type = conn.execute(
                f"SELECT typeof(bbox) FROM read_parquet('{url}') LIMIT 1"
            ).fetchone()[0]
            print(f"\nStructure de bbox : {bbox_type}")
        except Exception as exc:
            print(f"\nbbox illisible : {exc}")

    missing = [c for c in ("area_in_meters", "bf_source") if c not in names]
    if missing:
        print(f"\n=> Colonnes absentes : {missing}")
        print("   C'est la cause du « Binder Error ».")


def probe_overture(conn) -> tuple[str | None, str | None]:
    """Cherche une version accessible, en testant S3 puis HTTPS.

    Le bucket S3 d'Overture est en mode « requester pays » : sans
    identifiants AWS, DuckDB renvoie « No files found » quelle que soit la
    version. L'accès HTTPS public, lui, ne demande aucune authentification.
    """
    print("\n" + "=" * 68)
    print("OVERTURE MAPS — recherche d'un accès valide")
    print("=" * 68)

    for label, base in (("HTTPS public", OVERTURE_HTTPS), ("S3 direct", OVERTURE_S3)):
        print(f"\nMode {label} :")
        for release in CANDIDATE_RELEASES:
            path = f"{base}/{release}/theme=places/type=place/*"
            try:
                conn.execute(f"SELECT 1 FROM read_parquet('{path}') LIMIT 1").fetchone()
                print(f"  TROUVÉE  {release}")
                return release, base
            except Exception as exc:
                text = str(exc)
                if "No files found" in text:
                    reason = "aucun fichier"
                elif "403" in text or "Access Denied" in text:
                    reason = "accès refusé (identifiants requis)"
                else:
                    reason = text[:42]
                print(f"  absente  {release}  ({reason})")
    return None, None


def inspect_overture_schema(conn, release: str, base: str) -> None:
    print(f"\nSchéma du thème places (version {release}) :")
    path = f"{base}/{release}/theme=places/type=place/*"
    try:
        rows = conn.execute(f"DESCRIBE SELECT * FROM read_parquet('{path}') LIMIT 1").fetchall()
        for row in rows[:14]:
            print(f"  {row[0]:<24} {str(row[1])[:44]}")
    except Exception as exc:
        print(f"  illisible : {exc}")


def main() -> int:
    try:
        conn = connect()
    except ImportError:
        print("duckdb n'est pas installé dans cet environnement.")
        return 1

    inspect_buildings(conn)
    release, base = probe_overture(conn)
    if release:
        inspect_overture_schema(conn, release, base)

    print("\n" + "=" * 68)
    print("CONFIGURATION À APPLIQUER")
    print("=" * 68)
    if release:
        print(f"  PRATISIG_OVERTURE_RELEASE={release}")
        print(f"  PRATISIG_OVERTURE_USE_S3={'true' if base == OVERTURE_S3 else 'false'}")
    else:
        print("  Aucun accès Overture. Les autres modules restent utilisables ;")
        print("  OpenStreetMap couvre des besoins voisins (POI, routes, bâtiments).")
    print("\nEnvoyez cette sortie complète pour que les requêtes soient corrigées.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
