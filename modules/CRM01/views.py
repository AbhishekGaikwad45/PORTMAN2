from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from functools import wraps
from . import model
from database import get_user_permissions

bp = Blueprint('CRM01', __name__, template_folder='.')
MODULE_CODE = 'CRM01'
MODULE_INFO = {'code': 'CRM01', 'name': 'Conveyor Route Master'}

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

@bp.route('/module/CRM01/')
@login_required
def view():
    perms = get_perms()
    if not perms.get('can_read'):
        return render_template('no_access.html'), 403
    return render_template('crm01.html', permissions=perms)

@bp.route('/api/module/CRM01/data')
@login_required
def get_data():
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 20, type=int)
    return jsonify(model.get_all(page, size))

@bp.route('/api/module/CRM01/all')
@login_required
def get_all():
    """Get all route names for dropdowns"""
    return jsonify(model.get_all_routes())

@bp.route('/api/module/CRM01/save', methods=['POST'])
@login_required
def save_data():
    perms = get_perms()
    if not perms.get('can_add') and not perms.get('can_edit'):
        return jsonify({'error': 'No permission'}), 403

    data = request.json
    data['created_by'] = session.get('username')
    route_id = model.save(data)
    return jsonify({'id': route_id})

@bp.route('/api/module/CRM01/delete', methods=['POST'])
@login_required
def delete_data():
    perms = get_perms()
    if not perms.get('can_delete'):
        return jsonify({'error': 'No permission'}), 403

    data = request.json
    model.delete(data.get('id'))
    return jsonify({'success': True})
