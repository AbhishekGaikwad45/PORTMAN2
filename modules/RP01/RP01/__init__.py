# from flask import Blueprint

# MODULE_INFO = {
#     'code': 'RP01',
#     'name': 'Reports'
# }

# bp = Blueprint('RP01', __name__, template_folder='.')

# from . import views

print("LOADED:", __file__)
from flask import Blueprint

MODULE_INFO = {
    "code": "RP01",
    "name": "Reports"
}

bp = Blueprint(
    "RP01",
    __name__,
    template_folder="."
)

from . import views
from .JJLTPL import jjltpl