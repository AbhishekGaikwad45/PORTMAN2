print("LOADED:", __file__)

from flask import Blueprint

MODULE_CODE = "RP01"
MODULE_INFO = {
    "code": MODULE_CODE,
    "name": "Reports"
}

bp = Blueprint(
    "RP01",
    __name__,
    template_folder="."
)

# Import after blueprint creation
from . import views
from .JJLTPL import jjltpl
from .report1 import report1
from .report2 import report2
from .report_06 import views as report_06_views

from .Berth_plan import view as berth_plan_view
from .custom_report import views as custom_report_views

