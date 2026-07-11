print("LOADED:", __file__)

from flask import Blueprint

MODULE_CODE = 'RP01'
MODULE_INFO = {
    "code": MODULE_CODE,
    "name": "Reports"
}

bp = Blueprint(
    "RP01",
    __name__,
    template_folder="."
)

# Import each sub-module's views AFTER bp is defined, so their
# `from .. import bp` (or `from . import bp`) finds it already built.
from . import views
from .JJLTPL import jjltpl
from .report1 import report1
from .report2 import report2
from .Berth_plan import view as berth_plan_view

