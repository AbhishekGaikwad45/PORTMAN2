from flask import Blueprint

MODULE_INFO = {
    'code': 'RP01',
    'name': 'Reports'
}

bp = Blueprint('RP01', __name__, template_folder='.')

from . import views
