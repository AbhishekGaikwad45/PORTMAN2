from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, Response
from functools import wraps
import csv, io
from . import model
from database import get_user_permissions

bp = Blueprint('VDM01', __name__, template_folder='.')
MODULE_CODE = 'VDM01'

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

@bp.route('/module/VDM01/')
@login_required
def view():
    perms = get_perms()
    if not perms.get('can_read'):
        return render_template('no_access.html'), 403
    return render_template('vdm01.html', permissions=perms)

@bp.route('/api/module/VDM01/data')
@login_required
def get_data():
    page = int(request.args.get('page', 1))
    size = int(request.args.get('size', 20))
    data, total = model.get_data(page, size)
    return jsonify({'data': data, 'last_page': (total + size - 1) // size, 'total': total})

@bp.route('/api/module/VDM01/all')
@login_required
def get_all():
    return jsonify(model.get_all())

@bp.route('/api/module/VDM01/save', methods=['POST'])
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

@bp.route('/api/module/VDM01/delete', methods=['POST'])
@login_required
def delete():
    perms = get_perms()
    if not perms.get('can_delete'):
        return jsonify({'error': 'No permission to delete'}), 403
    model.delete_data(request.json.get('id'))
    return jsonify({'success': True})

@bp.route('/api/module/VDM01/template')
@login_required
def download_template():
    si = io.StringIO()
    writer = csv.writer(si)
    writer.writerow(['Delay Name', 'To SOF', 'Type'])
    return Response(si.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment; filename=VDM01_Template.csv'})

@bp.route('/api/module/VDM01/bulk_upload', methods=['POST'])
@login_required
def bulk_upload():
    perms = get_perms()
    if not perms.get('can_add'):
        return jsonify({'error': 'No permission to add'}), 403
    file = request.files.get('file')
    if not file:
        return jsonify({'error': 'No file uploaded'}), 400
    stream = io.StringIO(file.stream.read().decode('utf-8-sig'))
    reader = csv.DictReader(stream)
    rows = []
    field_map = {'Delay Name': 'name', 'To SOF': 'to_sof', 'Type': 'type'}
    for r in reader:
        row = {}
        for csv_col, db_col in field_map.items():
            row[db_col] = (r.get(csv_col) or '').strip()
        rows.append(row)
    inserted = model.bulk_insert(rows)
    return jsonify({'success': True, 'inserted': inserted})
