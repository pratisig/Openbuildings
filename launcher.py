"""Lanceur pour la distribution Windows portable de l'application Streamlit."""
import sys
from pathlib import Path


def resource_path(filename: str) -> Path:
    """Retourne un fichier embarqué par PyInstaller ou un fichier du projet."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / filename
    return Path(__file__).resolve().parent / filename


if __name__ == "__main__":
    app_path = resource_path("app.py")
    sys.argv = [
        "streamlit",
        "run",
        str(app_path),
        "--server.headless=true",
        "--browser.gatherUsageStats=false",
    ]
    from streamlit.web import cli as streamlit_cli

    sys.exit(streamlit_cli.main())
