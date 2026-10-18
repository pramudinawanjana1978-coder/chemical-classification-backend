
"""
Admin API for the Chemical Classification Assistant.
Uses Supabase PostgreSQL via DATABASE_URL.
"""

import hmac
import logging
import os
import re
import psycopg
from database import get_connection
import threading
import time

from contextlib import contextmanager
from functools import wraps

from flask import Blueprint, jsonify, request
from itsdangerous import (
    BadSignature,
    SignatureExpired,
    URLSafeTimedSerializer,
)
from werkzeug.security import check_password_hash


# Load admin credentials from backend/.env
try:
    from dotenv import load_dotenv

    load_dotenv(
        os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            ".env"
        )
    )
except ImportError:
    pass


log = logging.getLogger("admin_routes")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TABLE = "chemicals"


# Academic project category mapping.
# These labels are not real-world disposal instructions.
SIM_TO_CATEGORY = {
    "SIM-P1": "Acidic Chemical",
    "SIM-P2": "Basic Chemical",
    "SIM-P3": "Oxidizing Chemical",
    "SIM-P4": "Flammable / Organic Solvent",
    "SIM-P5": "Halogenated Organic Chemical",
    "SIM-P6": "Metal-Containing Inorganic Chemical",
    "SIM-P7": "Reactive / Special Chemical",
    "SIM-P8": "General Inorganic Chemical",
    "SIM-P9": "General Organic / Biochemical",
}

CATEGORY_TO_SIM = {
    name: code
    for code, name in SIM_TO_CATEGORY.items()
}

CATEGORIES = list(SIM_TO_CATEGORY.values())

MAX_NAME = 200
MAX_CLASS = 200
MAX_ALIASES_TOTAL = 1500
MAX_ALIAS = 200

admin_bp = Blueprint("admin_api", __name__)
_on_change = None


# ==========================================================
# ADMIN CONFIGURATION
# ==========================================================

def _config():
    username = os.environ.get(
        "ADMIN_USERNAME", ""
    ).strip()

    pw_hash = os.environ.get(
        "ADMIN_PASSWORD_HASH", ""
    ).strip()

    secret = os.environ.get(
        "ADMIN_SECRET_KEY", ""
    ).strip()

    if not (username and pw_hash and len(secret) >= 16):
        return None

    return username, pw_hash, secret


def _token_ttl():
    try:
        return max(
            300,
            int(
                os.environ.get(
                    "ADMIN_TOKEN_TTL_SECONDS",
                    "7200"
                )
            )
        )
    except ValueError:
        return 7200


def _serializer(secret):
    return URLSafeTimedSerializer(
        secret,
        salt="chemical-admin-token"
    )


# ==========================================================
# LOGIN RATE LIMITING
# ==========================================================

_attempts = {}
_attempts_lock = threading.Lock()

MAX_FAILS = 5
WINDOW_SECONDS = 300


def _client_key():
    return request.remote_addr or "unknown"


def _is_locked(key):
    now = time.time()

    with _attempts_lock:
        fails = [
            t for t in _attempts.get(key, [])
            if now - t < WINDOW_SECONDS
        ]

        _attempts[key] = fails

        return len(fails) >= MAX_FAILS


def _record_fail(key):
    with _attempts_lock:
        _attempts.setdefault(
            key, []
        ).append(time.time())


def _clear_fails(key):
    with _attempts_lock:
        _attempts.pop(key, None)


# ==========================================================
# DATABASE CONNECTION - FIXED
# ==========================================================

@contextmanager
def db():
    with get_connection() as conn:
        yield conn


# ==========================================================
# CHEMICAL DATA HELPERS
# ==========================================================

def _category_for(stored):
    if stored in SIM_TO_CATEGORY:
        return SIM_TO_CATEGORY[stored]

    if stored in CATEGORY_TO_SIM:
        return stored

    return None


def _split_aliases(value):
    return [
        alias.strip()
        for alias in (value or "").split(";")
        if alias.strip()
    ]


def _row_to_json(row):
    return {
        "id": row["id"],
        "chemical_name": row["chemical_name"],
        "aliases": row["aliases"] or "",
        "alias_list": _split_aliases(
            row["aliases"]
        ),
        "primary_project_class": row[
            "primary_project_class"
        ],
        "project_waste_category": _category_for(
            row["virtual_group"]
        ),
    }


SELECT_COLUMNS = (
    "id, chemical_name, aliases, "
    "primary_project_class, virtual_group"
)


def _notify_changed():
    if _on_change:
        try:
            _on_change()

        except Exception:
            log.exception(
                "on_change callback failed"
            )


# ==========================================================
# ERROR RESPONSE
# ==========================================================

def _error(message, status, fields=None):
    body = {
        "error": message
    }

    if fields:
        body["fields"] = fields

    return jsonify(body), status


# ==========================================================
# ADMIN AUTHENTICATION
# ==========================================================

def require_admin(view):

    @wraps(view)
    def wrapper(*args, **kwargs):

        cfg = _config()

        if cfg is None:
            return _error(
                "Admin login is not configured on the server.",
                503
            )

        header = request.headers.get(
            "Authorization", ""
        )

        if not header.startswith("Bearer "):
            return _error(
                "Unauthorized. Please log in again.",
                401
            )

        try:
            _serializer(cfg[2]).loads(
                header[7:].strip(),
                max_age=_token_ttl()
            )

        except (BadSignature, SignatureExpired):
            return _error(
                "Unauthorized. Please log in again.",
                401
            )

        return view(*args, **kwargs)

    return wrapper


# ==========================================================
# ADMIN LOGIN
# ==========================================================

@admin_bp.post("/api/admin/login")
def admin_login():

    cfg = _config()

    if cfg is None:
        return _error(
            "Admin login is not configured on the server.",
            503
        )

    key = _client_key()

    if _is_locked(key):
        return _error(
            "Too many failed attempts. Please wait "
            "a few minutes and try again.",
            429
        )

    data = request.get_json(silent=True) or {}

    username = str(
        data.get("username", "")
    )

    password = str(
        data.get("password", "")
    )

    user_ok = hmac.compare_digest(
        username.encode("utf-8"),
        cfg[0].encode("utf-8")
    )

    try:
        pass_ok = check_password_hash(
            cfg[1],
            password
        )

    except ValueError:
        log.error(
            "ADMIN_PASSWORD_HASH is invalid."
        )

        return _error(
            "Admin login is not configured correctly.",
            503
        )

    if not (user_ok and pass_ok):
        _record_fail(key)

        return _error(
            "Invalid admin credentials.",
            401
        )

    _clear_fails(key)

    token = _serializer(
        cfg[2]
    ).dumps({
        "role": "admin"
    })

    return jsonify({
        "token": token,
        "expires_in": _token_ttl()
    })


# ==========================================================
# ADMIN LOGOUT
# ==========================================================

@admin_bp.post("/api/admin/logout")
def admin_logout():
    return jsonify({
        "ok": True
    })


# ==========================================================
# INPUT VALIDATION
# ==========================================================

_CONTROL = re.compile(
    r"[\x00-\x08\x0b-\x1f\x7f]"
)


def _clean_text(value):
    return _CONTROL.sub(
        "",
        str(value or "")
    ).strip()


def _clean_payload(data):

    if not isinstance(data, dict):
        return None, {
            "_": "Request body must be a JSON object."
        }

    errors = {}

    name = " ".join(
        _clean_text(
            data.get("chemical_name")
        ).split()
    )

    primary = _clean_text(
        data.get("primary_project_class")
    )

    category = _clean_text(
        data.get("project_waste_category")
    )

    raw_aliases = data.get(
        "aliases", ""
    )

    if isinstance(raw_aliases, list):
        raw_aliases = ";".join(
            str(alias)
            for alias in raw_aliases
        )

    seen = set()
    aliases = []

    alias_text = _clean_text(
        raw_aliases
    ).replace("\n", ";")

    for alias in _split_aliases(alias_text):

        alias = " ".join(
            alias.split()
        )

        if len(alias) > MAX_ALIAS:
            errors["aliases"] = (
                f"Each alias must be "
                f"{MAX_ALIAS} characters or fewer."
            )

        if (
            alias.lower() not in seen
            and alias.lower() != name.lower()
        ):
            seen.add(alias.lower())
            aliases.append(alias)

    aliases_text = ";".join(
        aliases
    )

    if not name:
        errors["chemical_name"] = (
            "Chemical name is required."
        )

    elif len(name) > MAX_NAME:
        errors["chemical_name"] = (
            "Chemical name is too long."
        )

    if not primary:
        errors["primary_project_class"] = (
            "Primary project class is required."
        )

    elif len(primary) > MAX_CLASS:
        errors["primary_project_class"] = (
            "Primary project class is too long."
        )

    if not category:
        errors["project_waste_category"] = (
            "Project waste category is required."
        )

    elif category not in CATEGORY_TO_SIM:
        errors["project_waste_category"] = (
            "Please choose a listed project category."
        )

    if len(aliases_text) > MAX_ALIASES_TOTAL:
        errors["aliases"] = (
            "Aliases are too long."
        )

    if errors:
        return None, errors

    return {
        "chemical_name": name,
        "aliases": aliases_text,
        "primary_project_class": primary,
        "virtual_group": CATEGORY_TO_SIM[category],
    }, {}


# ==========================================================
# DUPLICATE CHECK
# ==========================================================

def _duplicate_exists(
    conn,
    name,
    exclude_id=None
):

    row = conn.execute(
        f"""
        SELECT id
        FROM {TABLE}
        WHERE lower(chemical_name) = lower(%s)
        AND id != %s
        """,
        (
            name,
            exclude_id
            if exclude_id is not None
            else -1
        )
    ).fetchone()

    return row is not None


# ==========================================================
# DATABASE ERROR HANDLER
# ==========================================================

@admin_bp.errorhandler(psycopg.Error)
def _database_error(exc):

    log.exception(
        "Database error in admin API: %s",
        exc
    )

    return _error(
        "Database error. Please try again.",
        500
    )


# ==========================================================
# GET PROJECT CATEGORIES
# ==========================================================

@admin_bp.get("/api/admin/categories")
@require_admin
def list_categories():

    return jsonify({
        "categories": CATEGORIES
    })


# ==========================================================
# GET ALL CHEMICALS
# ==========================================================

@admin_bp.get("/api/admin/chemicals")
@require_admin
def list_chemicals():

    q = _clean_text(
        request.args.get("q", "")
    )[:200]

    sql = (
        f"SELECT {SELECT_COLUMNS} "
        f"FROM {TABLE}"
    )

    params = []

    if q:
        like = (
            "%"
            + q.replace("\\", "\\\\")
               .replace("%", "\\%")
               .replace("_", "\\_")
            + "%"
        )

        sql += (
            " WHERE chemical_name ILIKE %s ESCAPE '\\' "
            "OR aliases ILIKE %s ESCAPE '\\'"
        )

        params = [like, like]

    sql += (
        " ORDER BY lower(chemical_name), id"
    )

    with db() as conn:
        rows = conn.execute(
            sql,
            params
        ).fetchall()

    return jsonify({
        "chemicals": [
            _row_to_json(row)
            for row in rows
        ],
        "total": len(rows)
    })


# ==========================================================
# ADD CHEMICAL
# ==========================================================

@admin_bp.post("/api/admin/chemicals")
@require_admin
def create_chemical():

    clean, errors = _clean_payload(
        request.get_json(silent=True)
    )

    if errors:
        return _error(
            "Please correct the highlighted fields.",
            400,
            errors
        )

    with db() as conn:

        if _duplicate_exists(
            conn,
            clean["chemical_name"]
        ):
            return _error(
                "A chemical with this name already exists.",
                409,
                {
                    "chemical_name":
                    "A chemical with this name already exists."
                }
            )

        try:
            cur = conn.execute(
                f"""
                INSERT INTO {TABLE}
                (
                    chemical_name,
                    aliases,
                    primary_project_class,
                    virtual_group
                )
               VALUES (%s, %s, %s, %s)
               RETURNING id
                """,
                (
                    clean["chemical_name"],
                    clean["aliases"],
                    clean["primary_project_class"],
                    clean["virtual_group"]
                )
            )

        except psycopg.IntegrityError as exc:
            log.warning(
                "Insert rejected: %s",
                exc
            )

            return _error(
                "The database rejected this chemical.",
                409
            )

        new_id = cur.fetchone()["id"]
        row = conn.execute(
            f"SELECT {SELECT_COLUMNS} FROM {TABLE} WHERE id = %s",
            (new_id,)
        ).fetchone()

    _notify_changed()

    return jsonify({
        "chemical": _row_to_json(row)
    }), 201


# ==========================================================
# EDIT CHEMICAL
# ==========================================================

@admin_bp.put(
    "/api/admin/chemicals/<int:chemical_id>"
)
@require_admin
def update_chemical(chemical_id):

    clean, errors = _clean_payload(
        request.get_json(silent=True)
    )

    if errors:
        return _error(
            "Please correct the highlighted fields.",
            400,
            errors
        )

    with db() as conn:

        existing = conn.execute(
            f"""
            SELECT 1
            FROM {TABLE}
            WHERE id = %s
            """,
            (chemical_id,)
        ).fetchone()

        if existing is None:
            return _error(
                "Chemical not found.",
                404
            )

        if _duplicate_exists(
            conn,
            clean["chemical_name"],
            chemical_id
        ):
            return _error(
                "A chemical with this name already exists.",
                409
            )

        try:
            conn.execute(
                f"""
                UPDATE {TABLE}
                SET
                    chemical_name = %s,
                    aliases = %s,
                    primary_project_class = %s,
                    virtual_group = %s
                WHERE id = %s
                """,
                (
                    clean["chemical_name"],
                    clean["aliases"],
                    clean["primary_project_class"],
                    clean["virtual_group"],
                    chemical_id
                )
            )

        except psycopg.IntegrityError as exc:
            log.warning(
                "Update rejected: %s",
                exc
            )

            return _error(
                "The database rejected this change.",
                409
            )

        row = conn.execute(
            f"""
            SELECT {SELECT_COLUMNS}
            FROM {TABLE}
            WHERE id = %s
            """,
            (chemical_id,)
        ).fetchone()

    _notify_changed()

    return jsonify({
        "chemical": _row_to_json(row)
    })


# ==========================================================
# DELETE CHEMICAL
# ==========================================================

@admin_bp.delete(
    "/api/admin/chemicals/<int:chemical_id>"
)
@require_admin
def delete_chemical(chemical_id):

    with db() as conn:

        cur = conn.execute(
            f"""
            DELETE FROM {TABLE}
            WHERE id = %s
            """,
            (chemical_id,)
        )

        if cur.rowcount == 0:
            return _error(
                "Chemical not found.",
                404
            )

    _notify_changed()

    return jsonify({
        "deleted": chemical_id
    })


# ==========================================================
# REGISTER ADMIN ROUTES
# ==========================================================

def register_admin(app, on_change=None):

    global _on_change

    _on_change = on_change

    app.register_blueprint(
        admin_bp
    )

    if _config() is None:
        log.warning(
            "Admin API registered but admin "
            "credentials are not configured."
        )
