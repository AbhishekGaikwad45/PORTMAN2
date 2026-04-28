from flask import Blueprint

MODULE_INFO = {
    'code': 'FINV01',
    'name': 'Invoicing'
}

bp = Blueprint('FINV01', __name__, template_folder='.')

from . import views
