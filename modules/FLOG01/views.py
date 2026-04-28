from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from functools import wraps
from . import model
from database import get_user_permissions

bp = Blueprint('FLOG01', __name__, template_folder='.')
MODULE_CODE = 'FLOG01'


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def get_perms():
    if session.get('is_admin'):
        return {'can_read': 1, 'can_add': 1, 'can_edit': 1, 'can_delete': 1}
    return get_user_permissions(session.get('user_id'), MODULE_CODE)


@bp.route('/module/FLOG01/')
@login_required
def view():
    perms = get_perms()
    if not perms.get('can_read'):
        return render_template('no_access.html'), 403
    return render_template('flog01.html', permissions=perms)


@bp.route('/api/module/FLOG01/data')
@login_required
def get_data():
    page = int(request.args.get('page', 1))
    size = int(request.args.get('size', 50))
    filters = {
        'integration_type': request.args.get('integration_type'),
        'status': request.args.get('status'),
        'date_from': request.args.get('date_from'),
        'date_to': request.args.get('date_to')
    }
    data, total = model.get_logs(page, size, filters)
    return jsonify({'data': data, 'last_page': (total + size - 1) // size, 'total': total})


@bp.route('/api/module/FLOG01/detail/<int:log_id>')
@login_required
def get_detail(log_id):
    log = model.get_log_detail(log_id)
    if not log:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(log)
