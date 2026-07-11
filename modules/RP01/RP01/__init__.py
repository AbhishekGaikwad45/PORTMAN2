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
from .report1 import report1
from .report2 import report2