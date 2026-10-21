""" Admin control of LabRats accounts.

GET    /api/labrats/users          Admin: list accounts (?q= filters by name or username)
POST   /api/labrats/users          Admin: create an account (name, uid, password, role, email)
PUT    /api/labrats/users/<uid>    Admin: change name, email, role, active, or set a new password
DELETE /api/labrats/users/<uid>    Admin: delete an account and its assignment turn-ins

Accounts an admin creates are active at once (the admin is the verifier). Upstream Flask refuses
inactive accounts at sign-in, so admins can also activate accounts made elsewhere, or deactivate one.
Admins cannot remove their own Admin role, deactivate, or delete their own account, so the console
can never lock out the person using it.
"""
from flask import Blueprint, request, g, current_app
from flask_restful import Api, Resource
from sqlalchemy import or_

from __init__ import db
from api.authorize import token_required
from model.user import User
from model.labrats_accounts import validate_account, public_user
from model.labrats_assignment import delete_turnins_for_user

labrats_users_api = Blueprint("labrats_users_api", __name__, url_prefix="/api/labrats/users")
api = Api(labrats_users_api)


def _json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


class UsersAPI:
    class _Collection(Resource):
        @token_required("Admin")
        def get(self):
            query = User.query
            search = (request.args.get("q") or "").strip()
            if search:
                like = f"%{search}%"
                query = query.filter(or_(User._name.ilike(like), User._uid.ilike(like)))
            return [public_user(user) for user in query.order_by(User._name).all()], 200

        @token_required("Admin")
        def post(self):
            data = _json_body()
            if data is None:
                return {"message": "Send the account as a JSON object."}, 400
            cleaned, errors = validate_account(data, creating=True)
            if errors:
                return {"message": "Some fields need attention.", "errors": errors}, 400
            if User.query.filter_by(_uid=cleaned["uid"]).first():
                return {"message": "That username is taken.", "errors": {"uid": "That username is taken."}}, 409

            user = User(name=cleaned["name"], uid=cleaned["uid"], password=cleaned["password"], role=cleaned["role"])
            if user.create({"email": cleaned["email"]} if cleaned.get("email") else None) is None:
                return {"message": "The account could not be saved."}, 409
            user.activate()
            current_app.logger.info("Admin %s created LabRats account %s (%s)", g.current_user.uid, user.uid, user.role)
            return public_user(user), 201

    class _Item(Resource):
        @token_required("Admin")
        def put(self, uid):
            user = User.query.filter_by(_uid=uid).first()
            if user is None:
                return {"message": f"Account {uid} not found"}, 404
            data = _json_body()
            if data is None:
                return {"message": "Send the changes as a JSON object."}, 400
            cleaned, errors = validate_account(data, creating=False)
            if cleaned.get("role") and user.id == g.current_user.id and cleaned["role"] != "Admin":
                errors["role"] = "You can't remove your own Admin role."
            if cleaned.get("active") is False and user.id == g.current_user.id:
                errors["active"] = "You can't deactivate your own account."
            if errors:
                return {"message": "Some fields need attention.", "errors": errors}, 400

            role = cleaned.pop("role", None)
            active = cleaned.pop("active", None)
            if cleaned:
                user.update(cleaned)
            if role:
                user.role = role
                db.session.commit()
            if active:
                user.activate()
            elif active is False:
                user.active = False
                db.session.commit()
            changed = set(cleaned) | ({"role"} if role else set()) | ({"active"} if active is not None else set())
            current_app.logger.info("Admin %s updated LabRats account %s: %s", g.current_user.uid, uid, sorted(changed))
            return public_user(user), 200

        @token_required("Admin")
        def delete(self, uid):
            user = User.query.filter_by(_uid=uid).first()
            if user is None:
                return {"message": f"Account {uid} not found"}, 404
            if user.id == g.current_user.id:
                return {"message": "You can't delete your own account."}, 400

            delete_turnins_for_user(user.id)
            user.delete()
            if User.query.filter_by(_uid=uid).first() is not None:
                # User.delete swallows integrity errors (records elsewhere still reference the account).
                return {"message": f"Account {uid} is still linked to other records and was not deleted."}, 409
            current_app.logger.info("Admin %s deleted LabRats account %s", g.current_user.uid, uid)
            return {"message": f"Deleted {uid}"}, 200


api.add_resource(UsersAPI._Collection, "", "/")
api.add_resource(UsersAPI._Item, "/<string:uid>")
