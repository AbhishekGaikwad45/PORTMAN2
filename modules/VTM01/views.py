from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from functools import wraps
from . import model

bp = Blueprint('VTM01', __name__, template_folder='.')

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

@bp.route('/module/VTM01/')
@login_required
def view():
    return render_template('vtm01.html', username=session.get('username'))

@bp.route('/api/module/VTM01/data')
@login_required
def get_data():
    page = int(request.args.get('page', 1))
    size = int(request.args.get('size', 20))
    data, total = model.get_data(page, size)
    return jsonify({
        'data': data,
        'last_page': (total + size - 1) // size,
        'total': total
    })

@bp.route('/api/module/VTM01/all')
@login_required
def get_all():
    return jsonify(model.get_all())

@bp.route('/api/module/VTM01/save', methods=['POST'])
@login_required
def save():
    data = request.json
    row_id = model.save_data(data)
    return jsonify({'success': True, 'id': row_id})

@bp.route('/api/module/VTM01/delete', methods=['POST'])
@login_required
def delete():
    row_id = request.json.get('id')
    model.delete_data(row_id)
    return jsonify({'success': True})
