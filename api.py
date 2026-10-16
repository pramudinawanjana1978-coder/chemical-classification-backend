from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import os
from difflib import SequenceMatcher
from dotenv import load_dotenv
load_dotenv()


# =========================================================
# FLASK APP
# =========================================================

app = Flask(__name__)
CORS(app)
from admin_routes import register_admin
register_admin(app)


# =========================================================
# DATABASE PATH
# =========================================================

BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

DATABASE_PATH = os.path.join(
    BASE_DIR,
    "chemical_waste.db"
)


# =========================================================
# PROJECT CATEGORY MAPPING
# =========================================================
# These are project/simulation categories.
# SIM codes stay internal and are not shown to the frontend.

PROJECT_CATEGORY_MAP = {
    "SIM-P1": "Acidic Chemical",
    "SIM-P2": "Basic Chemical",
    "SIM-P3": "Oxidizing Chemical",
    "SIM-P4": "Flammable / Organic Solvent",
    "SIM-P5": "Halogenated Organic Chemical",
    "SIM-P6": "Metal-Containing Inorganic Chemical",
    "SIM-P7": "Reactive / Special Chemical",
    "SIM-P8": "General Inorganic Chemical",
    "SIM-P9": "General Organic / Biochemical"
}


def get_project_category(virtual_group):

    if virtual_group is None:
        return "Other / Unclassified"

    virtual_group = str(virtual_group).strip()

    return PROJECT_CATEGORY_MAP.get(
        virtual_group,
        "Other / Unclassified"
    )


# =========================================================
# DATABASE CONNECTION
# =========================================================

def get_connection():

    connection = sqlite3.connect(
        DATABASE_PATH
    )

    connection.row_factory = sqlite3.Row

    return connection


# =========================================================
# NORMALIZE CHEMICAL NAME
# =========================================================

def normalize_text(text):

    if text is None:
        return ""

    text = str(text).lower().strip()

    # UK / US spelling variations
    replacements = {
        "sulphate": "sulfate",
        "sulphite": "sulfite",
        "sulphide": "sulfide",
        "sulphur": "sulfur"
    }

    for old, new in replacements.items():

        text = text.replace(
            old,
            new
        )

    # Remove unnecessary extra spaces
    text = " ".join(
        text.split()
    )

    return text


# =========================================================
# GET ALL CHEMICALS
# =========================================================

def get_all_chemicals():

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            id,
            chemical_name,
            aliases,
            primary_project_class,
            virtual_group
        FROM chemicals
    """)

    chemicals = cursor.fetchall()

    connection.close()

    return chemicals


# =========================================================
# CHEMICAL MATCHING
# =========================================================

def find_matches(search_text):

    search_text = normalize_text(
        search_text
    )

    chemicals = get_all_chemicals()

    matches = []

    for chemical in chemicals:

        chemical_name = (
            chemical["chemical_name"] or ""
        )

        aliases = (
            chemical["aliases"] or ""
        )

        # Names that can be compared
        names_to_check = [
            normalize_text(
                chemical_name
            )
        ]

        # Add aliases
        for alias in aliases.split(";"):

            alias = alias.strip()

            if alias:

                names_to_check.append(
                    normalize_text(alias)
                )

        best_score = 0


        # =================================================
        # CHECK ALL POSSIBLE NAMES
        # =================================================

        for name in names_to_check:

            # ---------------------------------------------
            # EXACT MATCH
            # ---------------------------------------------

            if search_text == name:

                best_score = 1.0

                break


            # ---------------------------------------------
            # PARTIAL MATCH
            # Example:
            # "oxalate"
            # ---------------------------------------------

            if (
                len(search_text) >= 4
                and search_text in name
            ):

                best_score = max(
                    best_score,
                    0.85
                )


            # ---------------------------------------------
            # FUZZY MATCH
            # ---------------------------------------------

            similarity = SequenceMatcher(
                None,
                search_text,
                name
            ).ratio()

            best_score = max(
                best_score,
                similarity
            )


        # =================================================
        # ADD USEFUL MATCH
        # =================================================

        if best_score >= 0.55:

            project_category = get_project_category(
                chemical["virtual_group"]
            )

            matches.append({

                "id":
                    chemical["id"],

                "chemical_name":
                    chemical["chemical_name"],

                "match_score":
                    round(
                        best_score * 100,
                        1
                    ),

                "primary_project_class":
                    chemical["primary_project_class"],

                "project_waste_category":
                    project_category

            })


    # =====================================================
    # SORT BEST MATCH FIRST
    # =====================================================

    matches.sort(
        key=lambda item:
            item["match_score"],
        reverse=True
    )


    # Return only top 3
    return matches[:3]


# =========================================================
# HOME
# =========================================================

@app.route(
    "/",
    methods=["GET"]
)
def home():

    return jsonify({

        "message":
            "Chemical Classification API is running",

        "status":
            "OK"

    })


# =========================================================
# API STATUS
# =========================================================

@app.route(
    "/api/status",
    methods=["GET"]
)
def status():

    try:

        connection = get_connection()

        cursor = connection.cursor()

        cursor.execute("""
            SELECT COUNT(*)
            FROM chemicals
        """)

        total = cursor.fetchone()[0]

        connection.close()

        return jsonify({

            "status":
                "OK",

            "backend":
                "Online",

            "database":
                "Connected",

            "total_chemicals":
                total

        })

    except Exception as error:

        return jsonify({

            "status":
                "Error",

            "backend":
                "Online",

            "database":
                "Disconnected",

            "message":
                str(error)

        }), 500


# =========================================================
# SEARCH CHEMICAL
# =========================================================

@app.route(
    "/api/search",
    methods=["POST"]
)
def search_chemical():

    # Get JSON from React frontend
    data = request.get_json(
        silent=True
    )


    # -----------------------------------------------------
    # JSON VALIDATION
    # -----------------------------------------------------

    if not data:

        return jsonify({

            "found":
                False,

            "error":
                "JSON data is required",

            "matches":
                []

        }), 400


    chemical_name = data.get(
        "chemical_name",
        ""
    )


    chemical_name = str(
        chemical_name
    ).strip()


    # -----------------------------------------------------
    # EMPTY SEARCH
    # -----------------------------------------------------

    if not chemical_name:

        return jsonify({

            "found":
                False,

            "error":
                "Chemical name is required",

            "matches":
                []

        }), 400


    # -----------------------------------------------------
    # SEARCH
    # -----------------------------------------------------

    try:

        matches = find_matches(
            chemical_name
        )

    except Exception as error:

        return jsonify({

            "found":
                False,

            "error":
                "Database search failed",

            "message":
                str(error),

            "matches":
                []

        }), 500


    # -----------------------------------------------------
    # NO MATCH
    # -----------------------------------------------------

    if not matches:

        return jsonify({

            "query":
                chemical_name,

            "found":
                False,

            "message":
                "No matching chemical found.",

            "matches":
                []

        }), 200


    # -----------------------------------------------------
    # SUCCESS
    # -----------------------------------------------------

    return jsonify({

        "query":
            chemical_name,

        "found":
            True,

        "matches":
            matches

    }), 200


# =========================================================
# GET CHEMICAL BY ID
# =========================================================

@app.route(
    "/api/chemical/<int:chemical_id>",
    methods=["GET"]
)
def get_chemical(chemical_id):

    try:

        connection = get_connection()

        cursor = connection.cursor()

        cursor.execute("""
            SELECT
                id,
                chemical_name,
                primary_project_class,
                virtual_group
            FROM chemicals
            WHERE id = ?
        """, (
            chemical_id,
        ))

        chemical = cursor.fetchone()

        connection.close()


        # -------------------------------------------------
        # NOT FOUND
        # -------------------------------------------------

        if chemical is None:

            return jsonify({

                "error":
                    "Chemical not found"

            }), 404


        # -------------------------------------------------
        # CONVERT SIM CODE TO READABLE CATEGORY
        # -------------------------------------------------

        project_category = get_project_category(
            chemical["virtual_group"]
        )


        # -------------------------------------------------
        # RETURN RESULT
        # -------------------------------------------------

        return jsonify({

            "id":
                chemical["id"],

            "chemical_name":
                chemical["chemical_name"],

            "primary_project_class":
                chemical["primary_project_class"],

            "project_waste_category":
                project_category

        }), 200


    except Exception as error:

        return jsonify({

            "error":
                "Could not load chemical",

            "message":
                str(error)

        }), 500


# =========================================================
# START FLASK SERVER
# =========================================================

if __name__ == "__main__":

    print()
    print("-----------------------------------------")
    print("Chemical Classification API")
    print("-----------------------------------------")
    print("Database:", DATABASE_PATH)
    print("Server: http://127.0.0.1:5000")
    print("-----------------------------------------")
    print()

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )