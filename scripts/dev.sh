#!/usr/bin/env bash
#
# PratiSIG — démarrage local en une commande.
#
#   ./scripts/dev.sh          API + interface
#   ./scripts/dev.sh api      API seule
#   ./scripts/dev.sh check    vérifications (tests, lint, build)
#
# Crée l'environnement Python et installe les dépendances au premier appel.

set -euo pipefail

# Sous PowerShell, `./scripts/dev.sh` se termine sans rien faire : Windows ne
# sait pas exécuter un script bash. Cette ligne n'est atteinte que par bash,
# donc si vous êtes sous Windows, utilisez scripts\dev.ps1 à la place.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="$ROOT/apps/api"
WEB_DIR="$ROOT/apps/web"
VENV="$ROOT/.venv"
MODE="${1:-all}"

c_ok()   { printf '\033[0;32m%s\033[0m\n' "$1"; }
c_info() { printf '\033[0;36m%s\033[0m\n' "$1"; }
c_warn() { printf '\033[0;33m%s\033[0m\n' "$1"; }
c_err()  { printf '\033[0;31m%s\033[0m\n' "$1" >&2; }

need() {
  command -v "$1" >/dev/null 2>&1 || { c_err "Commande manquante : $1"; exit 1; }
}

setup_api() {
  need python3
  if [ ! -d "$VENV" ]; then
    c_info "Création de l'environnement Python…"
    python3 -m venv "$VENV"
  fi
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"
  if ! python -c "import fastapi" 2>/dev/null; then
    c_info "Installation des dépendances API (socle léger)…"
    pip install -q --upgrade pip
    pip install -q -r "$API_DIR/requirements.txt"
    pip install -q pytest ruff
    c_ok "Dépendances installées."
    c_warn "Exports SIG, imagerie et agent désactivés."
    c_warn "Pour tout activer : pip install -r apps/api/requirements-full.txt"
  fi
}

setup_web() {
  need node
  if [ ! -d "$WEB_DIR/node_modules" ]; then
    c_info "Installation des dépendances de l'interface…"
    (cd "$WEB_DIR" && npm install --no-audit --no-fund)
  fi
}

case "$MODE" in
  check)
    setup_api
    c_info "── Tests ──"
    (cd "$API_DIR" && python -m pytest tests -q)
    c_info "── Lint ──"
    (cd "$API_DIR" && ruff check pratisig_api tests)
    setup_web
    c_info "── Build interface ──"
    (cd "$WEB_DIR" && npm run build)
    c_ok "Toutes les vérifications passent."
    ;;

  api)
    setup_api
    c_ok "API : http://localhost:8000/docs"
    (cd "$API_DIR" && exec uvicorn pratisig_api.main:app --reload --port 8000)
    ;;

  all)
    setup_api
    setup_web
    (cd "$API_DIR" && uvicorn pratisig_api.main:app --reload --port 8000) &
    API_PID=$!
    trap 'kill $API_PID 2>/dev/null || true' EXIT INT TERM

    c_info "Démarrage de l'API…"
    for _ in $(seq 1 30); do
      if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then break; fi
      sleep 1
    done

    if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
      c_ok "API prête     : http://localhost:8000/docs"
    else
      c_warn "L'API met du temps à répondre — voir les journaux ci-dessus."
    fi
    c_ok "Interface     : http://localhost:5173"
    echo
    c_info "Ctrl+C pour tout arrêter."
    # --host expose aussi sur le réseau local (utile en conteneur, ou pour
    # tester depuis un téléphone connecté au même réseau).
    (cd "$WEB_DIR" && npm run dev -- --host)
    ;;

  *)
    c_err "Usage : ./scripts/dev.sh [all|api|check]"
    exit 1
    ;;
esac
