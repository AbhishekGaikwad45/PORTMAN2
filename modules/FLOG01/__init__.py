from flask import Blueprint

MODULE_INFO = {
    'code': 'FLOG01',
    'name': 'Integration Logs'
}

bp = Blueprint('FLOG01', __name__, template_folder='.')
from . import views
