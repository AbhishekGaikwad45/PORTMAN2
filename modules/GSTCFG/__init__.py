from flask import Blueprint

MODULE_INFO = {
    'code': 'GSTCFG',
    'name': 'GST API Configuration'
}

bp = Blueprint('GSTCFG', __name__, template_folder='.')
from . import views
