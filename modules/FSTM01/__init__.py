from flask import Blueprint

MODULE_INFO = {
    'code': 'FSTM01',
    'name': 'Service Type Master'
}

bp = Blueprint('FSTM01', __name__, template_folder='.')

from . import views
