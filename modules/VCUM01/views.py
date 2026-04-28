from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from functools import wraps
from . import model
from database import get_user_permissions
import va_utils

bp = Blueprint('VCUM01', __name__, template_folder='.')
MODULE_CODE = 'VCUM01'

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

@bp.route('/module/VCUM01/')
@login_required
def view():
    perms = get_perms()
    if not perms.get('can_read'):
        return render_template('no_access.html'), 403
    return render_template('vcum01.html', permissions=perms)

@bp.route('/api/module/VCUM01/data')
@login_required
def get_data():
    page = int(request.args.get('page', 1))
    size = int(request.args.get('size', 20))
    data, total = model.get_data(page, size)
    return jsonify({'data': data, 'last_page': (total + size - 1) // size, 'total': total})

@bp.route('/api/module/VCUM01/all')
@login_required
def get_all():
    return jsonify(model.get_all())

@bp.route('/api/module/VCUM01/save', methods=['POST'])
@login_required
def save():
    perms = get_perms()
    data = request.json
    is_new = not data.get('id')
    if is_new and not perms.get('can_add'):
        return jsonify({'error': 'No permission to add'}), 403
    if not is_new and not perms.get('can_edit'):
        return jsonify({'error': 'No permission to edit'}), 403
    row_id = model.save_data(data)
    return jsonify({'success': True, 'id': row_id})

@bp.route('/api/module/VCUM01/delete', methods=['POST'])
@login_required
def delete():
    perms = get_perms()
    if not perms.get('can_delete'):
        return jsonify({'error': 'No permission to delete'}), 403
    model.delete_data(request.json.get('id'))
    return jsonify({'success': True})

PARTY_TYPE = 'Customer'

@bp.route('/api/module/VCUM01/virtual-accounts/<int:party_id>')
@login_required
def get_va(party_id):
    return jsonify(va_utils.get_va_list(PARTY_TYPE, party_id))

@bp.route('/api/module/VCUM01/virtual-accounts/save', methods=['POST'])
@login_required
def save_va():
    perms = get_perms()
    if not perms.get('can_edit') and not perms.get('can_add'):
        return jsonify({'error': 'No permission'}), 403
    data = request.json
    data['party_type'] = PARTY_TYPE
    row_id = va_utils.save_va(data, session.get('user_id'))
    return jsonify({'success': True, 'id': row_id})

@bp.route('/api/module/VCUM01/virtual-accounts/delete', methods=['POST'])
@login_required
def delete_va():
    perms = get_perms()
    if not perms.get('can_delete'):
        return jsonify({'error': 'No permission'}), 403
    va_utils.delete_va(request.json.get('id'))
    return jsonify({'success': True})
