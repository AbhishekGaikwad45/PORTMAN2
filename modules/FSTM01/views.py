from flask import render_template, request, redirect, url_for, session, jsonify
from . import bp
from . import model
from database import get_user_permissions
from modules.FGRM01 import model as gst_model

@bp.route('/module/FSTM01/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    perms = get_user_permissions(session['user_id'], 'FSTM01')
    page = int(request.args.get('page', 1))
    data, total = model.get_service_type_data(page)
    gst_rates = gst_model.get_all_gst_rates()

    return render_template('fstm01.html',
                         data=data,
                         page=page,
                         last_page=(total + 19) // 20,
                         gst_rates=gst_rates,
                         perms=perms,
                         is_admin=session.get('is_admin', False),
                         username=session.get('username'))


@bp.route('/api/module/FSTM01/save', methods=['POST'])
def save():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'})

    perms = get_user_permissions(session['user_id'], 'FSTM01')
    data = request.json

    is_admin = session.get('is_admin', False)

    if data.get('id') and not perms['can_edit'] and not is_admin:
        return jsonify({'success': False, 'error': 'No edit permission'})
    if not data.get('id') and not perms['can_add'] and not is_admin:
        return jsonify({'success': False, 'error': 'No add permission'})

    # System rows can only be edited by admins
    if data.get('is_system') and not is_admin:
        return jsonify({'success': False, 'error': 'System rows can only be edited by admins'})

    data['created_by'] = session.get('username')
    try:
        row_id = model.save_service_type(data)
    except ValueError as e:
        # Validation / unique-code errors raised by the model
        return jsonify({'success': False, 'error': str(e)})
    except Exception as e:
        # Return JSON (not an HTML 500 page) so the client can parse it
        return jsonify({'success': False, 'error': 'Save failed: ' + str(e)})
    return jsonify({'success': True, 'id': row_id})


@bp.route('/api/module/FSTM01/delete', methods=['POST'])
def delete():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'})

    perms = get_user_permissions(session['user_id'], 'FSTM01')
    if not perms['can_delete']:
        return jsonify({'success': False, 'error': 'No delete permission'})

    row_id = request.json.get('id')
    model.delete_service_type(row_id)
    return jsonify({'success': True})


# ===== FIELD DEFINITION ENDPOINTS =====

@bp.route('/api/module/FSTM01/fields/<int:service_type_id>')
def get_fields(service_type_id):
    """Get all field definitions for a service type"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    fields = model.get_field_definitions(service_type_id)
    return jsonify({'data': fields})


@bp.route('/api/module/FSTM01/fields/save', methods=['POST'])
def save_field():
    """Save or update a field definition"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'})

    perms = get_user_permissions(session['user_id'], 'FSTM01')
    if not perms['can_add'] and not perms['can_edit']:
        return jsonify({'success': False, 'error': 'No permission'})

    data = request.json
    data['created_by'] = session.get('username')
    row_id = model.save_field_definition(data)
    return jsonify({'success': True, 'id': row_id})


@bp.route('/api/module/FSTM01/fields/usage/<int:field_id>')
def field_usage(field_id):
    """What deleting this field would destroy — drives the confirm dialog."""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'})
    usage = model.field_usage(field_id)
    if usage is None:
        return jsonify({'success': False, 'error': 'Field not found'}), 404
    return jsonify({'success': True, **usage})


@bp.route('/api/module/FSTM01/fields/delete', methods=['POST'])
def delete_field():
    """Delete a field definition and every value recorded against it.

    Destructive and irreversible, so a reason is mandatory and is written to
    approval_log along with what was destroyed."""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'})

    perms = get_user_permissions(session['user_id'], 'FSTM01')
    if not perms['can_delete']:
        return jsonify({'success': False, 'error': 'No delete permission'})

    data = request.json or {}
    field_id = data.get('id')
    reason = (data.get('reason') or '').strip()
    if not reason:
        return jsonify({'success': False, 'error': 'A reason is required to delete a custom field'}), 400

    try:
        usage = model.delete_field_definition(field_id, reason, session.get('username'))
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': f'Delete failed: {e}'}), 500
    return jsonify({'success': True, 'deleted_values': usage['values']})
