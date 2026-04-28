from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from functools import wraps
from . import model

bp = Blueprint('GSTCFG', __name__, template_folder='.')


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if not session.get('is_admin'):
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated


@bp.route('/module/GSTCFG/')
@admin_required
def view():
    configs = model.get_all_configs()
    return render_template('gstcfg.html', configs=configs)


@bp.route('/api/module/GSTCFG/save', methods=['POST'])
@admin_required
def save():
    data = request.json
    row_id = model.save_config(data, session.get('user_id'))
    return jsonify({'success': True, 'id': row_id})


@bp.route('/api/module/GSTCFG/set-active', methods=['POST'])
@admin_required
def set_active():
    env = request.json.get('environment')
    model.set_active_env(env)
    return jsonify({'success': True})
