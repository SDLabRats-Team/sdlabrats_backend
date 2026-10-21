""" San Diego LabRats program catalog.

Stored in the labrats_programs table (seeded from model/labrats_seed/programs.json) and served to the
website by GET /api/labrats/page and GET /api/programs/. The `slug` values are what contact forms
send as an inquiry's `interest`, so inquiry validation reads them from here.
"""
from __init__ import db


class LabRatsProgram(db.Model):
    __tablename__ = "labrats_programs"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(64), unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    short = db.Column(db.String(80), nullable=False)
    path = db.Column(db.String(255), nullable=False)
    audience = db.Column(db.String(20), nullable=False)  # "families" or "schools"
    grades = db.Column(db.String(80), nullable=False)
    when_text = db.Column(db.String(200), nullable=False)
    summary = db.Column(db.Text, nullable=False)
    image = db.Column(db.String(255), nullable=True)
    image_alt = db.Column(db.String(300), nullable=True)
    position = db.Column(db.Integer, nullable=False, default=0)

    def __init__(self, slug, name, short, path, audience, grades, when, summary, image=None, image_alt=None, position=0):
        self.slug = slug
        self.name = name
        self.short = short
        self.path = path
        self.audience = audience
        self.grades = grades
        self.when_text = when
        self.summary = summary
        self.image = image
        self.image_alt = image_alt
        self.position = position

    def read(self):
        return {
            "slug": self.slug,
            "name": self.name,
            "short": self.short,
            "path": self.path,
            "audience": self.audience,
            "grades": self.grades,
            "when": self.when_text,
            "summary": self.summary,
            "image": self.image,
            "image_alt": self.image_alt,
        }


def all_programs():
    """Programs in catalog order, as dictionaries."""
    return [program.read() for program in LabRatsProgram.query.order_by(LabRatsProgram.position).all()]


def program_slugs():
    return {slug for (slug,) in db.session.query(LabRatsProgram.slug).all()}
