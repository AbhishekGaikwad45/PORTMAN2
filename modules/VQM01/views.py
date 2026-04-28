from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from functools import wraps
from . import model
from database import get_user_permissions

bp = Blueprint('VQM01', __name__, template_folder='.')
MODULE_CODE = 'VQM01'

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

@bp.route('/module/VQM01/')
@login_required
def index():
    permissions = get_perms()
    return render_template('vqm01.html', permissions=permissions)

@bp.route('/api/module/VQM01/data')
def get_data():
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 20, type=int)
    return jsonify(model.get_data(page, size))

@bp.route('/api/module/VQM01/all')
def get_all():
    return jsonify(model.get_all())

@bp.route('/api/module/VQM01/default')
def get_default():
    return jsonify({'default': model.get_default()})

@bp.route('/api/module/VQM01/set-default', methods=['POST'])
def set_default():
    data = request.json
    model.set_default(data['id'])
    return jsonify({'success': True})

@bp.route('/api/module/VQM01/save', methods=['POST'])
def save():
    data = request.json
    result = model.save_data(data)
    return jsonify(result)

@bp.route('/api/module/VQM01/delete', methods=['POST'])
def delete():
    data = request.json
    model.delete_data(data['id'])
    return jsonify({'success': True})
