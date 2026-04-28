from flask import Blueprint

MODULE_INFO = {
    'code': 'FCRM01',
    'name': 'Currency Master'
}

bp = Blueprint('FCRM01', __name__, template_folder='.')

from . import views
