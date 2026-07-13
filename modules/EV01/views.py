from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from functools import wraps
from . import model
from . import pdf_parser
from database import get_user_permissions

bp = Blueprint('EV01', __name__, template_folder='.')
MODULE_CODE = 'EV01'

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

@bp.route('/module/EV01/')
@login_required
def view():
    perms = get_perms()
    if not perms.get('can_read'):
        return render_template('no_access.html'), 403
    return render_template('ev01.html', permissions=perms)

@bp.route('/api/module/EV01/data')
@login_required
def get_data():
    page = int(request.args.get('page', 1))
    size = int(request.args.get('size', 20))
    data, total = model.get_data(page, size)
    return jsonify({'data': data, 'last_page': (total + size - 1) // size, 'total': total})

@bp.route('/api/module/EV01/save', methods=['POST'])
@login_required
def save():
    perms = get_perms()
    data = request.json or {}
    is_new = not data.get('id')
    if is_new and not perms.get('can_add'):
        return jsonify({'error': 'No permission to add'}), 403
    if not is_new and not perms.get('can_edit'):
        return jsonify({'error': 'No permission to edit'}), 403
    row_id = model.save(data, username=session.get('username'))
    return jsonify({'success': True, 'id': row_id})

@bp.route('/api/module/EV01/delete', methods=['POST'])
@login_required
def delete():
    perms = get_perms()
    if not perms.get('can_delete'):
        return jsonify({'error': 'No permission to delete'}), 403
    model.delete(request.json['id'])
    return jsonify({'success': True})

@bp.route('/api/module/EV01/upload', methods=['POST'])
@login_required
def upload_pdf():
    """Parse the PDF and return a reconciliation preview — no DB writes."""
    perms = get_perms()
    if not perms.get('can_add') and not perms.get('can_edit'):
        return jsonify({'error': 'No permission'}), 403
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    f = request.files['file']
    if not f.filename.lower().endswith('.pdf'):
        return jsonify({'error': 'Only PDF files accepted'}), 400
    file_bytes = f.read()
    rows = pdf_parser.parse_pdf_ev_rows(file_bytes)
    if not rows:
        return jsonify({'error': 'No Expected Vessels table found in PDF. Check the file format.'}), 400
    preview = model.preview_upsert(rows)
    return jsonify({'success': True, 'total': len(rows), **preview})


@bp.route('/api/module/EV01/upload/commit', methods=['POST'])
@login_required
def upload_commit():
    """Apply the actions confirmed in the reconciliation wizard."""
    perms = get_perms()
    decisions = (request.json or {}).get('rows') or []
    if not decisions:
        return jsonify({'error': 'Nothing to import'}), 400
    actions = {d.get('action') for d in decisions}
    if 'insert' in actions and not perms.get('can_add'):
        return jsonify({'error': 'No permission to add records'}), 403
    if 'update' in actions and not perms.get('can_edit'):
        return jsonify({'error': 'No permission to edit records'}), 403
    result = model.apply_upsert(decisions, session.get('username'))
    return jsonify({'success': True, **result})


@bp.route('/api/module/EV01/moved_to_terminal')
@login_required
def moved_to_terminal_list():
    return jsonify(model.get_moved_to_terminal())

@bp.route('/api/module/EV01/move_to_terminal/<int:ev_id>', methods=['POST'])
@login_required
def move_to_terminal(ev_id):
    """Close an expected vessel that will be handled at another terminal —
    no VCN is created; the row is marked Closed."""
    perms = get_perms()
    if not perms.get('can_edit'):
        return jsonify({'error': 'No permission to edit'}), 403
    ev = model.get_by_id(ev_id)
    if not ev:
        return jsonify({'error': 'Record not found'}), 404
    if ev.get('doc_status') != 'Pending':
        return jsonify({'error': 'Only pending vessels can be moved'}), 400
    terminal = (request.json or {}).get('terminal_name')
    if not terminal:
        return jsonify({'error': 'Terminal is required'}), 400
    model.close_to_other_terminal(ev_id, terminal)
    return jsonify({'success': True, 'terminal_name': terminal})


@bp.route('/api/module/EV01/move_to_vcn/<int:ev_id>', methods=['POST'])
@login_required
def move_to_vcn(ev_id):
    ev = model.get_by_id(ev_id)
    if not ev:
        return jsonify({'error': 'Record not found'}), 404
    if ev.get('vcn_id'):
        return jsonify({'error': 'Already moved to VCN'}), 400

    from modules.VCN01 import model as vcn_model
    vcn_data = {
        'doc_status':        'Draft',
        'vessel_master_doc': model.get_vessel_master_doc(ev.get('vessel_name')),
        'vessel_name':       ev.get('vessel_name'),
        'via_number':        ev.get('via_number'),
        'loa':               ev.get('loa'),
        'draft':             ev.get('draft'),
        'vessel_agent_name': ev.get('agents'),
        # cargo_type deliberately NOT seeded from the parsed EV01 PDF — the
        # header syncs from real parcel cargo names once entered in VCN01
        'nor_tendered':      ev.get('nor'),
        'berth_name':        ev.get('berth_name'),
        'doc_date':          str(ev.get('eta').date()) if ev.get('eta') else None,
        'discharge_port':    vcn_model.default_discharge_port(),
    }
    vcn_id, vcn_doc_num = vcn_model.save_header(vcn_data)
    # Per-cargo totals (available-to-allocate) so parcel-quantity validation
    # has a quota to check against. Parcels themselves are NOT created from
    # EV01 — its consignee/qty lists are parsed PDF text and unreliable; the
    # operator enters parcels in VCN01 from the IGM.
    vcn_model.save_cargo_quotas(vcn_id, model.cargo_quotas(ev))
    model.mark_moved_to_vcn(ev_id, vcn_id)
    return jsonify({'vcn_id': vcn_id, 'vcn_doc_num': vcn_doc_num})
