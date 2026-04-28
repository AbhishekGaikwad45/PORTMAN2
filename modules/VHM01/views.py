from flask import Blueprint, render_template, request, jsonify, session
from . import model

bp = Blueprint('VHM01', __name__, template_folder='.')

@bp.route('/module/VHM01/')
def index():
    permissions = session.get('permissions', {}).get('VHM01', {})
    return render_template('vhm01.html', permissions=permissions)

@bp.route('/api/module/VHM01/data')
def get_data():
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 20, type=int)
    return jsonify(model.get_data(page, size))

@bp.route('/api/module/VHM01/all')
def get_all():
    return jsonify(model.get_all())

@bp.route('/api/module/VHM01/save', methods=['POST'])
def save():
    data = request.json
    result = model.save_data(data)
    return jsonify(result)

@bp.route('/api/module/VHM01/delete', methods=['POST'])
def delete():
    data = request.json
    model.delete_data(data['id'])
    return jsonify({'success': True})
