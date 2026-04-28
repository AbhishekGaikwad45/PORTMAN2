from flask import Blueprint

MODULE_INFO = {
    'code': 'FGRM01',
    'name': 'GST Rate Master'
}

bp = Blueprint('FGRM01', __name__, template_folder='.')

from . import views
