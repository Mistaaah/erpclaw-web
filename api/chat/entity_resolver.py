"""Entity resolver -- fuzzy search across ERP database for context resolution.

Supports two modes:
1. Dynamic: reads webclaw.entities from SKILL.md and queries skill-specific DBs
2. Fallback: hardcoded ERP entity tables (backward-compatible with existing erpclaw skills)

Adapted for erpclaw-web: uses the authoritative read-only Postgres connection.
"""
from __future__ import annotations

import os
import re
import sqlite3

import yaml

from db import get_erp_pg_db
from skills.executor import SKILLS_DIR

# Fallback entity config for erpclaw skills (backward compatibility)
_DEFAULT_ENTITY_TABLES: dict[str, tuple[str, str, str, list[str]]] = {
    "customer": ("customer", "name", "id", ["email", "customer_group"]),
    "supplier": ("supplier", "name", "id", ["email", "supplier_group"]),
    "item": ("item", "item_name", "id", ["item_code", "item_group_id"]),
    "account": ("account", "name", "id", ["account_number", "account_type"]),
    "employee": ("employee", "employee_name", "id", ["employee_id", "department_id"]),
    "company": ("company", "name", "id", []),
    "warehouse": ("warehouse", "name", "id", ["warehouse_type"]),
    "project": ("project", "project_name", "id", ["status"]),
}

# Cache: skill_name -> entity config dict
_entity_config_cache: dict[str, dict] = {}


def _load_skill_entities(skill_name: str) -> dict[str, tuple[str, str, str, list[str]]]:
    """Load entity config from a skill's SKILL.md webclaw.entities section.

    Returns dict of entity_type -> (table, name_col, id_col, search_cols).
    """
    if skill_name in _entity_config_cache:
        return _entity_config_cache[skill_name]

    entities: dict[str, tuple[str, str, str, list[str]]] = {}
    skill_md = os.path.join(SKILLS_DIR, skill_name, "SKILL.md")

    try:
        with open(skill_md, "r") as f:
            content = f.read()
        if content.startswith("---"):
            end = content.index("---", 3)
            frontmatter = yaml.safe_load(content[3:end])
            if frontmatter:
                webclaw = frontmatter.get("webclaw", {})
                if isinstance(webclaw, dict) and webclaw.get("entities"):
                    for etype, config in webclaw["entities"].items():
                        if isinstance(config, dict):
                            entities[etype] = (
                                config.get("table", etype + "s"),
                                config.get("name_col", "name"),
                                config.get("id_col", "id"),
                                config.get("search_cols", []),
                            )
    except Exception:
        pass

    _entity_config_cache[skill_name] = entities
    return entities


def _get_erp_connection():
    """Get a read-only connection to the authoritative ERP Postgres database."""
    try:
        return get_erp_pg_db()
    except RuntimeError:
        return None


def resolve_entity(
    entity_type: str | None,
    query: str,
    limit: int = 5,
    conn=None,
    skill: str | None = None,
) -> list[dict]:
    """Search for an entity by name, returning ranked matches.

    Args:
        entity_type: Specific type to search (e.g., "customer"), or None for all.
        query: Natural language query string.
        limit: Max results per type.
        conn: Optional DB connection (if None, uses ERPCLAW_DB_URL).
        skill: Optional skill name for per-skill entity resolution.

    Returns:
        List of matches sorted by confidence.
    """
    if not query or not query.strip():
        return []

    q = query.strip().lower()
    results: list[dict] = []
    owns_connection = False

    # Determine which entity configs and DBs to use
    search_targets: list[tuple[dict[str, tuple], object | None]] = []

    if skill:
        # Try skill-specific entities first
        skill_entities = _load_skill_entities(skill)
        if skill_entities:
            skill_conn = conn
            if skill_conn is None:
                skill_conn = _get_erp_connection()
                owns_connection = skill_conn is not None
            if skill_conn:
                search_targets.append((skill_entities, skill_conn))

    # If no skill-specific entities found, use defaults
    if not search_targets:
        if conn is None:
            conn = _get_erp_connection()
            owns_connection = conn is not None
        if conn:
            search_targets.append((_DEFAULT_ENTITY_TABLES, conn))

    try:
        for entity_tables, db_conn in search_targets:
            if db_conn is None:
                continue

            types_to_search = (
                {entity_type: entity_tables[entity_type]}
                if entity_type and entity_type in entity_tables
                else entity_tables
            )

            for etype, (table, name_col, id_col, extras) in types_to_search.items():
                try:
                    if not _safe_identifier(table) or not _safe_identifier(name_col) or not _safe_identifier(id_col):
                        continue
                    if any(not _safe_identifier(column) for column in extras):
                        continue
                    if isinstance(db_conn, sqlite3.Connection):
                        _search_sqlite(db_conn, etype, table, name_col, id_col, extras, q, limit, results)
                    else:
                        _search_postgres(db_conn, etype, table, name_col, id_col, extras, q, limit, results)
                except Exception:
                    continue
    finally:
        if owns_connection:
            for _, db_conn in search_targets:
                if db_conn is not None:
                    db_conn.close()

    # Sort by confidence descending
    results.sort(key=lambda x: x["confidence"], reverse=True)
    return results[:limit]


def _safe_identifier(value: str) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value) is not None


def _search_sqlite(db_conn, etype, table, name_col, id_col, extras, q, limit, results):
    exists = db_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if not exists:
        return
    select = ", ".join(f'"{column}"' for column in [id_col, name_col, *extras])
    for confidence, match_type, predicate, values in (
        (1.0, "exact match", f'LOWER("{name_col}") = ?', (q, limit)),
        (0.85, "starts with", f'LOWER("{name_col}") LIKE ? AND LOWER("{name_col}") != ?', (f"{q}%", q, limit)),
        (0.65, "contains", f'LOWER("{name_col}") LIKE ? AND LOWER("{name_col}") NOT LIKE ?', (f"%{q}%", f"{q}%", limit)),
    ):
        for row in db_conn.execute(f'SELECT {select} FROM "{table}" WHERE {predicate} LIMIT ?', values):
            results.append(_build_match(row, etype, name_col, id_col, extras, confidence, match_type))


def _search_postgres(db_conn, etype, table, name_col, id_col, extras, q, limit, results):
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = %s",
            (table,),
        )
        available = {row["column_name"] for row in cur.fetchall()}
        if name_col not in available or id_col not in available:
            return
        extras = [column for column in extras if column in available]
        select = ", ".join(f'"{column}"' for column in [id_col, name_col, *extras])
        for confidence, match_type, predicate, values in (
            (1.0, "exact match", f'LOWER("{name_col}") = %s', (q, limit)),
            (0.85, "starts with", f'LOWER("{name_col}") LIKE %s AND LOWER("{name_col}") <> %s', (f"{q}%", q, limit)),
            (0.65, "contains", f'LOWER("{name_col}") LIKE %s AND LOWER("{name_col}") NOT LIKE %s', (f"%{q}%", f"{q}%", limit)),
        ):
            cur.execute(f'SELECT {select} FROM "{table}" WHERE {predicate} LIMIT %s', values)
            for row in cur.fetchall():
                results.append(_build_match(row, etype, name_col, id_col, extras, confidence, match_type))


def _build_match(
    row, entity_type: str, name_col: str, id_col: str, extras: list[str],
    confidence: float, match_type: str,
) -> dict:
    """Build a match result dict from a DB row."""
    if hasattr(row, "keys"):
        row_dict = dict(row)
        eid = row_dict.get(id_col, "")
        name = row_dict.get(name_col, "")
        extra = {k: row_dict.get(k) for k in extras if k in row_dict}
    else:
        eid = row[0]
        name = row[1]
        extra = {extras[i]: row[i + 2] for i in range(len(extras)) if i + 2 < len(row)}

    return {
        "id": str(eid),
        "name": str(name),
        "entity_type": entity_type,
        "confidence": confidence,
        "source_detail": f"{match_type}: '{name}'",
        "extra": extra,
    }
