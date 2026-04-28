from flask import Blueprint

MODULE_INFO = {
    'code': 'FCAM01',
    'name': 'Customer Agreement Master'
}

bp = Blueprint('FCAM01', __name__, template_folder='.')

from . import views
