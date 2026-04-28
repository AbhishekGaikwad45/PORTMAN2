from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from functools import wraps
from . import model
from database import get_user_permissions

bp = Blueprint('PBM01', __name__, template_folder='.')
MODULE_CODE = 'PBM01'

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

@bp.route('/module/PBM01/')
@login_required
def view():
    perms = get_perms()
    if not perms.get('can_read'):
        return render_template('no_access.html'), 403
    return render_template('pbm01.html', permissions=perms)

@bp.route('/api/module/PBM01/data')
@login_required
def get_data():
    rows = model.get_all()
    return jsonify({'data': rows, 'last_page': 1, 'total': len(rows)})

@bp.route('/api/module/PBM01/all')
@login_required
def get_all():
    rows = model.get_all()
    return jsonify([r['berth_name'] for r in rows])

@bp.route('/api/module/PBM01/save', methods=['POST'])
@login_required
def save():
    perms = get_perms()
    data = request.json
    is_new = not data.get('id')
    if is_new and not perms.get('can_add'):
        return jsonify({'error': 'No permission to add'}), 403
    if not is_new and not perms.get('can_edit'):
        return jsonify({'error': 'No permission to edit'}), 403
    row_id = model.save(data)
    return jsonify({'id': row_id})

@bp.route('/api/module/PBM01/delete', methods=['POST'])
@login_required
def delete():
    perms = get_perms()
    if not perms.get('can_delete'):
        return jsonify({'error': 'No permission to delete'}), 403
    model.delete(request.json['id'])
    return jsonify({'success': True})
