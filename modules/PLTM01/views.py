from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from functools import wraps
from . import model
from database import get_user_permissions

bp = Blueprint('PLTM01', __name__, template_folder='.')
MODULE_CODE = 'PLTM01'

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

@bp.route('/module/PLTM01/')
@login_required
def view():
    perms = get_perms()
    if not perms.get('can_read'):
        return render_template('no_access.html'), 403
    return render_template('pltm01.html', permissions=perms)

@bp.route('/api/module/PLTM01/data')
@login_required
def get_data():
    page = int(request.args.get('page', 1))
    size = int(request.args.get('size', 20))
    data, total = model.get_data(page, size)
    return jsonify({'data': data, 'last_page': (total + size - 1) // size, 'total': total})

@bp.route('/api/module/PLTM01/save', methods=['POST'])
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
    return jsonify({'success': True, 'id': row_id})

@bp.route('/api/module/PLTM01/delete', methods=['POST'])
@login_required
def delete():
    perms = get_perms()
    if not perms.get('can_delete'):
        return jsonify({'error': 'No permission to delete'}), 403
    model.delete(request.json['id'])
    return jsonify({'success': True})

@bp.route('/api/module/PLTM01/pipelines')
@login_required
def get_pipelines():
    return jsonify(model.get_pipelines())

@bp.route('/api/module/PLTM01/terminals')
@login_required
def get_terminals():
    return jsonify(model.get_terminals())

@bp.route('/api/module/PLTM01/matrix')
@login_required
def get_matrix():
    pipelines, terminals, mappings = model.get_matrix_data()
    return jsonify({'pipelines': pipelines, 'terminals': terminals, 'mappings': mappings})

@bp.route('/api/module/PLTM01/toggle', methods=['POST'])
@login_required
def toggle():
    perms = get_perms()
    if not perms.get('can_add') and not perms.get('can_delete'):
        return jsonify({'error': 'No permission'}), 403
    data = request.json or {}
    action = model.toggle_mapping(data['pipeline_id'], data['terminal_id'])
    return jsonify({'success': True, 'action': action})
