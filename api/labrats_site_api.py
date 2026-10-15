""" San Diego LabRats website content API. The frontend keeps no data; it renders these responses.

GET  /api/labrats/page?path=/camps/     public: site settings, the page, its session, programs, sessions
GET  /api/labrats/sessions              Admin: every registration session, open and closed
PUT  /api/labrats/sessions/<id>         Admin: open or close a session, or change its term, grades,
                                        summary, times, Donorbox campaign, or schedule order
GET  /api/labrats/announcement          Admin: the notice shown above every page
PUT  /api/labrats/announcement          Admin: change or turn off that notice
"""
from flask import Blueprint, request, g, current_app
from flask_restful import Api, Resource

from __init__ import db
from api.authorize import token_required
from model.labrats_site import (
    LabRatsPage, LabRatsSession, page_bundle, all_sessions, get_setting,
    validate_session_update, validate_announcement, save_announcement,
)

labrats_site_api = Blueprint("labrats_site_api", __name__, url_prefix="/api/labrats")
api = Api(labrats_site_api)


def _json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


class SiteAPI:
    class _Page(Resource):
        def get(self):
            bundle = page_bundle(request.args.get("path", ""))
            if bundle is None:
                return {"message": "No LabRats page has that address."}, 404
            return bundle, 200

    class _Sessions(Resource):
        @token_required("Admin")
        def get(self):
            titles = dict(db.session.query(LabRatsPage.path, LabRatsPage.title).all())
            return [{**session, "title": titles.get(session["path"], session["term"])} for session in all_sessions()], 200

    class _Session(Resource):
        @token_required("Admin")
        def put(self, session_id):
            session = db.session.get(LabRatsSession, session_id)
            if session is None:
                return {"message": f"Session {session_id} not found"}, 404
            data = _json_body()
            if data is None:
                return {"message": "Send the changes as a JSON object."}, 400
            cleaned, errors = validate_session_update(data)
            if errors:
                return {"message": "Some fields need attention.", "errors": errors}, 400
            session.update(cleaned)
            current_app.logger.info("Admin %s updated LabRats session %s: %s", g.current_user.uid, session.path, sorted(cleaned))
            return session.read(), 200

    class _Announcement(Resource):
        @token_required("Admin")
        def get(self):
            return get_setting("announcement", {}), 200

        @token_required("Admin")
        def put(self):
            data = _json_body()
            if data is None:
                return {"message": "Send the announcement as a JSON object."}, 400
            cleaned, errors = validate_announcement(data)
            if errors:
                return {"message": "Some fields need attention.", "errors": errors}, 400
            saved = save_announcement(cleaned)
            current_app.logger.info("Admin %s updated the LabRats announcement (shown: %s)", g.current_user.uid, saved["show"])
            return saved, 200


api.add_resource(SiteAPI._Page, "/page")
api.add_resource(SiteAPI._Sessions, "/sessions")
api.add_resource(SiteAPI._Session, "/sessions/<int:session_id>")
api.add_resource(SiteAPI._Announcement, "/announcement")
