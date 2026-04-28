from flask import render_template, request, redirect, url_for, session, jsonify
from . import bp
from . import model
from database import get_user_permissions

@bp.route('/module/FGRM01/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    perms = get_user_permissions(session['user_id'], 'FGRM01')
    page = int(request.args.get('page', 1))
    data, total = model.get_gst_rate_data(page)

    return render_template('fgrm01.html',
                         data=data,
                         page=page,
                         last_page=(total + 19) // 20,
                         perms=perms,
                         username=session.get('username'))


@bp.route('/api/module/FGRM01/save', methods=['POST'])
def save():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'})

    perms = get_user_permissions(session['user_id'], 'FGRM01')
    data = request.json

    if data.get('id') and not perms['can_edit']:
        return jsonify({'success': False, 'error': 'No edit permission'})
    if not data.get('id') and not perms['can_add']:
        return jsonify({'success': False, 'error': 'No add permission'})

    data['created_by'] = session.get('username')
    row_id = model.save_gst_rate(data)
    return jsonify({'success': True, 'id': row_id})


@bp.route('/api/module/FGRM01/delete', methods=['POST'])
def delete():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'})

    perms = get_user_permissions(session['user_id'], 'FGRM01')
    if not perms['can_delete']:
        return jsonify({'success': False, 'error': 'No delete permission'})

    row_id = request.json.get('id')
    model.delete_gst_rate(row_id)
    return jsonify({'success': True})
