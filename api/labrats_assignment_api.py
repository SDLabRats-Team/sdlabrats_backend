""" LabRats assignments and turn-ins.

GET    /api/labrats/assignments                    signed in: students see open assignments with
                                                   their own turn-in; admins see every assignment
POST   /api/labrats/assignments                    Admin: create an assignment
PUT    /api/labrats/assignments/<id>               Admin: edit, open, or close an assignment
DELETE /api/labrats/assignments/<id>               Admin: delete an assignment and its turn-ins
PUT    /api/labrats/assignments/<id>/turnin        signed in: turn in (or replace) your work
GET    /api/labrats/assignments/<id>/turnins       Admin: every student's turn-in
PUT    /api/labrats/turnins/<id>                   Admin: leave feedback or mark reviewed
"""
from flask import Blueprint, request, g, current_app
from flask_restful import Api, Resource

from __init__ import db
from api.authorize import token_required
from model.labrats_assignment import (
    LabRatsAssignment, LabRatsTurnIn, validate_assignment, validate_turnin, validate_review,
)

labrats_assignment_api = Blueprint("labrats_assignment_api", __name__, url_prefix="/api/labrats")
api = Api(labrats_assignment_api)


def _json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def _invalid(errors):
    return {"message": "Some fields need attention.", "errors": errors}, 400


class AssignmentAPI:
    class _Collection(Resource):
        @token_required()
        def get(self):
            user = g.current_user
            if user.role == "Admin":
                assignments = LabRatsAssignment.query.order_by(LabRatsAssignment.created_at.desc()).all()
                return [assignment.read() for assignment in assignments], 200

            assignments = (LabRatsAssignment.query.filter_by(is_open=True)
                           .order_by(LabRatsAssignment.due_date.is_(None), LabRatsAssignment.due_date).all())
            mine = {turnin.assignment_id: turnin for turnin in LabRatsTurnIn.query.filter_by(user_id=user.id)}
            result = []
            for assignment in assignments:
                data = assignment.read()
                data.pop("turnin_count")
                data.pop("reviewed_count")
                data["my_turnin"] = mine[assignment.id].read() if assignment.id in mine else None
                result.append(data)
            return result, 200

        @token_required("Admin")
        def post(self):
            data = _json_body()
            if data is None:
                return {"message": "Send the assignment as a JSON object."}, 400
            cleaned, errors = validate_assignment(data)
            if errors:
                return _invalid(errors)
            assignment = LabRatsAssignment(**cleaned).create()
            current_app.logger.info("Admin %s created assignment %s", g.current_user.uid, assignment.id)
            return assignment.read(), 201

    class _Item(Resource):
        @token_required("Admin")
        def put(self, assignment_id):
            assignment = db.session.get(LabRatsAssignment, assignment_id)
            if assignment is None:
                return {"message": f"Assignment {assignment_id} not found"}, 404
            data = _json_body()
            if data is None:
                return {"message": "Send the changes as a JSON object."}, 400
            cleaned, errors = validate_assignment(data, partial=True)
            if errors:
                return _invalid(errors)
            return assignment.update(cleaned).read(), 200

        @token_required("Admin")
        def delete(self, assignment_id):
            assignment = db.session.get(LabRatsAssignment, assignment_id)
            if assignment is None:
                return {"message": f"Assignment {assignment_id} not found"}, 404
            assignment.delete()
            current_app.logger.info("Admin %s deleted assignment %s", g.current_user.uid, assignment_id)
            return {"message": f"Deleted assignment {assignment_id}"}, 200

    class _TurnIn(Resource):
        @token_required()
        def put(self, assignment_id):
            assignment = db.session.get(LabRatsAssignment, assignment_id)
            if assignment is None:
                return {"message": f"Assignment {assignment_id} not found"}, 404
            if not assignment.is_open:
                return {"message": "This assignment is closed and no longer accepts turn-ins."}, 409
            data = _json_body()
            if data is None:
                return {"message": "Send your work as a JSON object."}, 400
            cleaned, errors = validate_turnin(data)
            if errors:
                return _invalid(errors)
            user_id = g.current_user.id
            turnin = (LabRatsTurnIn.query.filter_by(assignment_id=assignment_id, user_id=user_id).first()
                      or LabRatsTurnIn(assignment_id, user_id))
            return turnin.submit(cleaned).read(), 200

    class _TurnIns(Resource):
        @token_required("Admin")
        def get(self, assignment_id):
            assignment = db.session.get(LabRatsAssignment, assignment_id)
            if assignment is None:
                return {"message": f"Assignment {assignment_id} not found"}, 404
            turnins = assignment.turnins.order_by(LabRatsTurnIn.submitted_at.desc()).all()
            return [turnin.read() for turnin in turnins], 200

    class _Review(Resource):
        @token_required("Admin")
        def put(self, turnin_id):
            turnin = db.session.get(LabRatsTurnIn, turnin_id)
            if turnin is None:
                return {"message": f"Turn-in {turnin_id} not found"}, 404
            data = _json_body()
            if data is None:
                return {"message": "Send the review as a JSON object."}, 400
            cleaned, errors = validate_review(data)
            if errors:
                return _invalid(errors)
            return turnin.review(cleaned).read(), 200


api.add_resource(AssignmentAPI._Collection, "/assignments", "/assignments/")
api.add_resource(AssignmentAPI._Item, "/assignments/<int:assignment_id>")
api.add_resource(AssignmentAPI._TurnIn, "/assignments/<int:assignment_id>/turnin")
api.add_resource(AssignmentAPI._TurnIns, "/assignments/<int:assignment_id>/turnins")
api.add_resource(AssignmentAPI._Review, "/turnins/<int:turnin_id>")
