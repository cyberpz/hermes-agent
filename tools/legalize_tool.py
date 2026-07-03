"""Legalize.dev integration — Italian law search and retrieval."""

import json
import os
import urllib.request
import urllib.parse
from typing import Optional
import yaml

from tools.registry import registry

API_BASE = "https://legalize.dev/api/v1"


def _load_api_key() -> str:
    """Read the Legalize API key from Hermes config.yaml (legalize.api_key)."""
    config_path = os.path.expanduser("~/.hermes/config.yaml")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
            return config.get("legalize", {}).get("api_key", "")
    except Exception:
        return ""


API_KEY = _load_api_key()


def _api_get(path: str, params: Optional[dict] = None) -> dict:
    """Execute an authenticated GET request to the Legalize API."""
    url = f"{API_BASE}{path}"
    if params:
        query = urllib.parse.urlencode(params, doseq=True)
        url = f"{url}?{query}"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {API_KEY}")
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _check_legalize_available() -> bool:
    """Availability check: API key must be configured."""
    return bool(API_KEY)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

SEARCH_ITALIAN_LAWS_SCHEMA = {
    "name": "search_italian_laws",
    "description": "Cerca leggi italiane nel database Legalize.dev per testo libero, tipo, anno, stato o giurisdizione.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Testo libero da cercare nel titolo/contenuto (es. 'privacy', '679/2016')."},
            "law_type": {"type": "string", "description": "Tipo di atto: legge, decreto_legge, decreto_legislativo, regio_decreto, etc."},
            "year": {"type": "integer", "description": "Anno di pubblicazione (es. 2016)."},
            "from_date": {"type": "string", "description": "Data inizio (YYYY-MM-DD)."},
            "to_date": {"type": "string", "description": "Data fine (YYYY-MM-DD)."},
            "status": {"type": "string", "description": "Stato: in_force, abrogated, repealed."},
            "jurisdiction": {"type": "string", "description": "Giurisdizione, es. 'Sicilia' per leggi regionali."},
            "page": {"type": "integer", "description": "Pagina risultati (default 1)."},
            "per_page": {"type": "integer", "description": "Risultati per pagina, max 100 (default 10)."},
            "sort": {"type": "string", "description": "Ordinamento: date_desc (default), date_asc, title."},
        },
    },
}

GET_ITALIAN_LAW_SCHEMA = {
    "name": "get_italian_law",
    "description": "Recupera testo completo e metadati di una legge italiana per ID Legalize.",
    "parameters": {
        "type": "object",
        "properties": {
            "law_id": {"type": "string", "description": "ID legale, es. '16G00079' per legge 79/2016."},
        },
        "required": ["law_id"],
    },
}

GET_ITALIAN_LAW_META_SCHEMA = {
    "name": "get_italian_law_meta",
    "description": "Recupera solo i metadati di una legge italiana per ID.",
    "parameters": {
        "type": "object",
        "properties": {
            "law_id": {"type": "string", "description": "ID legale, es. '16G00079'."},
        },
        "required": ["law_id"],
    },
}

GET_ITALIAN_LAW_TYPES_SCHEMA = {
    "name": "get_italian_law_types",
    "description": "Elenca i tipi di atto legislativo disponibili per l'Italia.",
    "parameters": {"type": "object", "properties": {}},
}

GET_ITALIAN_LAW_REFORMS_SCHEMA = {
    "name": "get_italian_law_reforms",
    "description": "Recupera le riforme successive di una legge italiana.",
    "parameters": {
        "type": "object",
        "properties": {
            "law_id": {"type": "string", "description": "ID legale."},
            "limit": {"type": "integer", "description": "Numero massimo di riforme (default 10)."},
            "offset": {"type": "integer", "description": "Offset paginazione (default 0)."},
        },
        "required": ["law_id"],
    },
}

GET_ITALIAN_LAW_COMMITS_SCHEMA = {
    "name": "get_italian_law_commits",
    "description": "Recupera la cronologia dei commit (versioni) di una legge italiana.",
    "parameters": {
        "type": "object",
        "properties": {
            "law_id": {"type": "string", "description": "ID legale."},
        },
        "required": ["law_id"],
    },
}


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def _handle_search_italian_laws(args, **kw):
    query = args.get("query", "")
    law_type = args.get("law_type", "")
    year = args.get("year", 0) or 0
    from_date = args.get("from_date", "")
    to_date = args.get("to_date", "")
    status = args.get("status", "")
    jurisdiction = args.get("jurisdiction", "")
    page = args.get("page", 1) or 1
    per_page = args.get("per_page", 10) or 10
    sort = args.get("sort", "")

    params: dict = {"page": page, "per_page": min(per_page, 100)}
    if query:
        params["q"] = query
    if law_type:
        params["law_type"] = law_type
    if year:
        params["year"] = year
    if from_date:
        params["from_date"] = from_date
    if to_date:
        params["to_date"] = to_date
    if status:
        params["status"] = status
    if jurisdiction:
        params["jurisdiction"] = jurisdiction
    if sort:
        params["sort"] = sort

    try:
        data = _api_get("/it/laws", params)
    except Exception as e:
        return f"Errore API Legalize: {e}"

    results = data.get("results", [])
    total = data.get("total", 0)
    count = data.get("count", len(results))

    if not results:
        return f"Nessuna legge trovata (total: {total}, count: {count})."

    lines = [
        "| ID | Titolo | Tipo | Data | Stato |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r.get('id','')} | {r.get('title','')} | {r.get('law_type','')} | {r.get('publication_date','')} | {r.get('status','')} |"
        )
    lines.append(f"\n*Risultati: {count}/{total} — pagina {page}*")
    return "\n".join(lines)


def _handle_get_italian_law(args, **kw):
    law_id = args.get("law_id", "")
    try:
        data = _api_get(f"/it/laws/{law_id}")
    except Exception as e:
        return f"Errore API Legalize: {e}"

    if isinstance(data, dict) and "error" in data:
        return f"Errore: {data.get('message', data['error'])}"

    lines = [
        f"# {data.get('title', 'Legge senza titolo')}",
        "",
        f"- **ID**: `{data.get('id', '')}`",
        f"- **Tipo**: {data.get('law_type', '')}",
        f"- **Data pubblicazione**: {data.get('publication_date', '')}",
        f"- **Stato**: {data.get('status', '')}",
    ]
    if data.get("short_title"):
        lines.append(f"- **Titolo breve**: {data['short_title']}")
    if data.get("jurisdiction"):
        lines.append(f"- **Giurisdizione**: {data['jurisdiction']}")
    if data.get("department"):
        lines.append(f"- **Dipartimento**: {data['department']}")
    lines.append("")

    content = data.get("content_md", "")
    if content:
        lines.append(content)
    else:
        lines.append("*Nessun contenuto testuale disponibile per questa legge.*")

    return "\n".join(lines)


def _handle_get_italian_law_meta(args, **kw):
    law_id = args.get("law_id", "")
    try:
        data = _api_get(f"/it/laws/{law_id}/meta")
    except Exception as e:
        return f"Errore API Legalize: {e}"

    if "error" in data:
        return f"Errore: {data.get('message', data['error'])}"

    lines = ["| Campo | Valore |", "|---|---|"]
    for k, v in data.items():
        if v is None:
            v = "—"
        elif isinstance(v, dict):
            v = json.dumps(v, ensure_ascii=False)
        lines.append(f"| {k} | {v} |")
    return "\n".join(lines)


def _handle_get_italian_law_types(args, **kw):
    try:
        data = _api_get("/it/law-types")
    except Exception as e:
        return f"Errore API Legalize: {e}"

    if isinstance(data, list):
        return "\n".join(f"- `{t}`" for t in data)
    return f"Risposta API: {json.dumps(data, ensure_ascii=False, indent=2)}"


def _handle_get_italian_law_reforms(args, **kw):
    law_id = args.get("law_id", "")
    limit = args.get("limit", 10) or 10
    offset = args.get("offset", 0) or 0
    try:
        data = _api_get(f"/it/laws/{law_id}/reforms", {"limit": limit, "offset": offset})
    except Exception as e:
        return f"Errore API Legalize: {e}"

    if isinstance(data, dict) and "error" in data:
        return f"Errore: {data.get('message', data['error'])}"

    if not isinstance(data, list) or not data:
        return "Nessuna riforma trovata per questa legge."

    lines = ["| Data | Tipo | Descrizione |", "|---|---|---|"]
    for r in data:
        lines.append(
            f"| {r.get('date','')} | {r.get('type','')} | {r.get('description','')} |"
        )
    return "\n".join(lines)


def _handle_get_italian_law_commits(args, **kw):
    law_id = args.get("law_id", "")
    try:
        data = _api_get(f"/it/laws/{law_id}/commits")
    except Exception as e:
        return f"Errore API Legalize: {e}"

    if isinstance(data, dict) and "error" in data:
        return f"Errore: {data.get('message', data['error'])}"

    if not isinstance(data, list) or not data:
        return "Nessun commit trovato per questa legge."

    lines = ["| SHA | Data | Messaggio |", "|---|---|---|"]
    for c in data:
        sha = c.get("sha", "")[:12]
        lines.append(
            f"| `{sha}` | {c.get('date','')} | {c.get('message','')} |"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

registry.register(
    name="search_italian_laws",
    toolset="legalize",
    schema=SEARCH_ITALIAN_LAWS_SCHEMA,
    handler=_handle_search_italian_laws,
    check_fn=_check_legalize_available,
    emoji="⚖️",
    max_result_size_chars=100_000,
)

registry.register(
    name="get_italian_law",
    toolset="legalize",
    schema=GET_ITALIAN_LAW_SCHEMA,
    handler=_handle_get_italian_law,
    check_fn=_check_legalize_available,
    emoji="⚖️",
    max_result_size_chars=100_000,
)

registry.register(
    name="get_italian_law_meta",
    toolset="legalize",
    schema=GET_ITALIAN_LAW_META_SCHEMA,
    handler=_handle_get_italian_law_meta,
    check_fn=_check_legalize_available,
    emoji="⚖️",
    max_result_size_chars=100_000,
)

registry.register(
    name="get_italian_law_types",
    toolset="legalize",
    schema=GET_ITALIAN_LAW_TYPES_SCHEMA,
    handler=_handle_get_italian_law_types,
    check_fn=_check_legalize_available,
    emoji="⚖️",
    max_result_size_chars=50_000,
)

registry.register(
    name="get_italian_law_reforms",
    toolset="legalize",
    schema=GET_ITALIAN_LAW_REFORMS_SCHEMA,
    handler=_handle_get_italian_law_reforms,
    check_fn=_check_legalize_available,
    emoji="⚖️",
    max_result_size_chars=50_000,
)

registry.register(
    name="get_italian_law_commits",
    toolset="legalize",
    schema=GET_ITALIAN_LAW_COMMITS_SCHEMA,
    handler=_handle_get_italian_law_commits,
    check_fn=_check_legalize_available,
    emoji="⚖️",
    max_result_size_chars=50_000,
)
