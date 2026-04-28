from flask import Blueprint, render_template, request, jsonify, session
from . import model

bp = Blueprint('VHO01', __name__, template_folder='.')

@bp.route('/module/VHO01/')
def index():
    permissions = session.get('permissions', {}).get('VHO01', {})
    return render_template('vho01.html', permissions=permissions)

@bp.route('/api/module/VHO01/data')
def get_data():
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 20, type=int)
    return jsonify(model.get_data(page, size))

@bp.route('/api/module/VHO01/all')
def get_all():
    return jsonify(model.get_all())

@bp.route('/api/module/VHO01/save', methods=['POST'])
def save():
    data = request.json
    result = model.save_data(data)
    return jsonify(result)

@bp.route('/api/module/VHO01/delete', methods=['POST'])
def delete():
    data = request.json
    model.delete_data(data['id'])
    return jsonify({'success': True})
