
from flask import Blueprint, jsonify
from model.labrats_programs import all_programs

programs_api = Blueprint(
    "programs_api",
    __name__,
    url_prefix="/api/programs"
)


@programs_api.route("/", methods=["GET"])
def get_programs():
    """San Diego LabRats program catalog (labrats_programs table); inquiry validation uses the same slugs."""
    return jsonify(all_programs())
