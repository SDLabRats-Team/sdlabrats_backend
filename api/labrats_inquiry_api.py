""" San Diego LabRats website form submissions.

POST /api/labrats/inquiries          public: store a contact, scholarship, partnership,
                                     video-topic, or newsletter submission, then email staff
                                     if SMTP is configured
GET  /api/labrats/inquiries          Admin: list submissions (?form=contact&status=new)
PUT  /api/labrats/inquiries/<id>     Admin: set status to "new" or "handled"
"""
from flask import Blueprint, request, current_app
from flask_restful import Api, Resource

from api.authorize import token_required
from model.labrats_inquiry import LabRatsInquiry, validate_inquiry, FORM_RULES, STATUSES
from model.labrats_notify import notify_staff

labrats_inquiry_api = Blueprint("labrats_inquiry_api", __name__, url_prefix="/api/labrats/inquiries")
api = Api(labrats_inquiry_api)


class InquiryAPI:
    class _Collection(Resource):
        def post(self):
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                return {"message": "Send the form as a JSON object."}, 400

            # Bots fill the hidden "website" field; accept quietly so they don't retry, but store nothing.
            if data.get("website"):
                current_app.logger.info("LabRats inquiry dropped: honeypot field was filled")
                return {"message": "Received"}, 201

            try:
                cleaned, errors = validate_inquiry(data)
            except ValueError as error:
                return {"message": str(error)}, 400
            if errors:
                return {"message": "Some fields need attention.", "errors": errors}, 400

            inquiry = LabRatsInquiry.from_cleaned(cleaned).create()
            current_app.logger.info("LabRats %s inquiry %s stored", inquiry.form, inquiry.id)
            notify_staff(inquiry.read(), current_app.config, current_app.logger)
            return {"message": "Received", "id": inquiry.id}, 201

        @token_required("Admin")
        def get(self):
            query = LabRatsInquiry.query
            form = request.args.get("form")
            status = request.args.get("status")
            if form:
                if form not in FORM_RULES:
                    return {"message": f"Unknown form '{form}'"}, 400
                query = query.filter_by(form=form)
            if status:
                if status not in STATUSES:
                    return {"message": f"Unknown status '{status}'"}, 400
                query = query.filter_by(status=status)
            inquiries = query.order_by(LabRatsInquiry.created_at.desc()).all()
            return [inquiry.read() for inquiry in inquiries], 200

    class _Item(Resource):
        @token_required("Admin")
        def put(self, inquiry_id):
            inquiry = LabRatsInquiry.query.get(inquiry_id)
            if inquiry is None:
                return {"message": f"Inquiry {inquiry_id} not found"}, 404
            status = (request.get_json(silent=True) or {}).get("status")
            if status not in STATUSES:
                return {"message": f"Status must be one of: {', '.join(STATUSES)}"}, 400
            return inquiry.update_status(status).read(), 200


api.add_resource(InquiryAPI._Collection, "", "/")
api.add_resource(InquiryAPI._Item, "/<int:inquiry_id>")
