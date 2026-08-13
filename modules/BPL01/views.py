from functools import wraps

from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for

from . import model
from database import get_user_permissions

bp = Blueprint('BPL01', __name__, template_folder='.')
MODULE_CODE = 'BPL01'
MODULE_INFO = {'code': 'BPL01', 'name': 'Berth Planning'}


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


def _can_write(perms):
    return perms.get('can_add') or perms.get('can_edit')


@bp.route('/module/BPL01/')
@login_required
def view():
    perms = get_perms()
    if not perms.get('can_read'):
        return render_template('no_access.html'), 403
    return render_template('bpl01.html', permissions=perms)


@bp.route('/api/module/BPL01/data')
@login_required
def data():
    if not get_perms().get('can_read'):
        return jsonify({'error': 'No permission'}), 403
    show_all = request.args.get('show_all') in ('1', 'true', 'yes')
    return jsonify(model.get_canvas(show_all=show_all))


@bp.route('/api/module/BPL01/plan', methods=['POST'])
@login_required
def save_plan():
    if not _can_write(get_perms()):
        return jsonify({'error': 'No permission'}), 403
    d = request.json or {}
    source, source_id = d.get('source'), d.get('source_id')
    if not source or not source_id:
        return jsonify({'error': 'Missing source / source_id'}), 400

    parcels = d.get('parcels')
    try:
        if parcels is None:
            # first drop: seed from what the vessel already declares, queued
            # behind whatever occupies the berth
            parcels = model.seed_parcels(source, source_id, d.get('berth_name'))
        model.save_plan(source, source_id, d.get('berth_name'), parcels,
                        session.get('username'))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify({'success': True})


@bp.route('/api/module/BPL01/plan/delete', methods=['POST'])
@login_required
def delete_plan():
    if not get_perms().get('can_delete'):
        return jsonify({'error': 'No permission to delete'}), 403
    d = request.json or {}
    source, source_id = d.get('source'), d.get('source_id')
    if not source or not source_id:
        return jsonify({'error': 'Missing source / source_id'}), 400
    try:
        model.delete_plan(source, source_id)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify({'success': True})
