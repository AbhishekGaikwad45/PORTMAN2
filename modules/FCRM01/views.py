from flask import render_template, request, redirect, url_for, session, jsonify
from . import bp
from . import model
from database import get_user_permissions

@bp.route('/module/FCRM01/')
def index():
    """Main FCRM01 index"""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    perms = get_user_permissions(session['user_id'], 'FCRM01')
    page = int(request.args.get('page', 1))
    data, total = model.get_currency_data(page)

    return render_template('fcrm01.html',
                         data=data,
                         page=page,
                         last_page=(total + 19) // 20,
                         perms=perms,
                         username=session.get('username'))

@bp.route('/module/FCRM01/currencies')
def currencies():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    perms = get_user_permissions(session['user_id'], 'FCRM01')
    page = int(request.args.get('page', 1))
    data, total = model.get_currency_data(page)

    return render_template('fcrm01.html',
                         data=data,
                         page=page,
                         last_page=(total + 19) // 20,
                         perms=perms,
                         username=session.get('username'))


@bp.route('/api/module/FCRM01/currency/save', methods=['POST'])
def save_currency():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'})

    perms = get_user_permissions(session['user_id'], 'FCRM01')
    data = request.json

    if data.get('id') and not perms['can_edit']:
        return jsonify({'success': False, 'error': 'No edit permission'})
    if not data.get('id') and not perms['can_add']:
        return jsonify({'success': False, 'error': 'No add permission'})

    data['created_by'] = session.get('username')
    row_id = model.save_currency(data)
    return jsonify({'success': True, 'id': row_id})


@bp.route('/api/module/FCRM01/currency/delete', methods=['POST'])
def delete_currency():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'})

    perms = get_user_permissions(session['user_id'], 'FCRM01')
    if not perms['can_delete']:
        return jsonify({'success': False, 'error': 'No delete permission'})

    row_id = request.json.get('id')
    model.delete_currency(row_id)
    return jsonify({'success': True})


@bp.route('/module/FCRM01/exchange-rates')
def exchange_rates():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    perms = get_user_permissions(session['user_id'], 'FCRM01')
    page = int(request.args.get('page', 1))
    data, total = model.get_exchange_rates(page)
    currencies = model.get_all_currencies()

    return render_template('fcrm01/exchange_rates.html',
                         data=data,
                         page=page,
                         last_page=(total + 19) // 20,
                         currencies=currencies,
                         perms=perms,
                         username=session.get('username'))


@bp.route('/api/module/FCRM01/exchange-rate/save', methods=['POST'])
def save_exchange_rate():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'})

    perms = get_user_permissions(session['user_id'], 'FCRM01')
    data = request.json

    if data.get('id') and not perms['can_edit']:
        return jsonify({'success': False, 'error': 'No edit permission'})
    if not data.get('id') and not perms['can_add']:
        return jsonify({'success': False, 'error': 'No add permission'})

    data['created_by'] = session.get('username')
    row_id = model.save_exchange_rate(data)
    return jsonify({'success': True, 'id': row_id})


@bp.route('/api/module/FCRM01/exchange-rate/delete', methods=['POST'])
def delete_exchange_rate():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'})

    perms = get_user_permissions(session['user_id'], 'FCRM01')
    if not perms['can_delete']:
        return jsonify({'success': False, 'error': 'No delete permission'})

    row_id = request.json.get('id')
    model.delete_exchange_rate(row_id)
    return jsonify({'success': True})
