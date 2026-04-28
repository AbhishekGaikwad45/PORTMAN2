
addToRecent('FIN01', 'Billing & Invoicing');

let sellerConfig = {};

// Load seller config from FIN01 module config
(async function() {
    try {
        const res = await fetch('/api/module/FIN01/port-config');
        sellerConfig = await res.json();
    } catch(e) { console.error('Error loading seller config:', e); }

    // Populate filing year dropdown (current year + 1 back)
    const yearSel = document.getElementById('gstr1Year');
    const now = new Date();
    const curYear = now.getFullYear();
    for (let y = curYear; y >= curYear - 2; y--) {
        const opt = document.createElement('option');
        opt.value = String(y);
        opt.textContent = String(y);
        yearSel.appendChild(opt);
    }
    // Default to current month/year
    document.getElementById('gstr1Month').value = String(now.getMonth() + 1).padStart(2, '0');
    document.getElementById('gstr1Year').value = String(curYear);
})();

function toggleSelectAll() {
    const checked = document.getElementById('selectAll').checked;
    document.querySelectorAll('.inv-select').forEach(cb => cb.checked = checked);
}

function getSelectedIds() {
    return Array.from(document.querySelectorAll('.inv-select:checked')).map(cb => parseInt(cb.value));
}

function showExportModal(type) {
    const ids = getSelectedIds();
    if (ids.length === 0) {
        alert('Please select at least one invoice to export.');
        return;
    }
    if (type === 'gstr1') {
        document.getElementById('gstr1Gstin').value = sellerConfig.seller_gstin || '';
        document.getElementById('gstr1Count').value = ids.length + ' invoice(s) selected';
        document.getElementById('gstr1Modal').style.display = 'block';
    } else {
        document.getElementById('einvGstin').value = sellerConfig.seller_gstin || '';
        document.getElementById('einvLegalName').value = sellerConfig.seller_legal_name || '';
        document.getElementById('einvAddress').value = sellerConfig.seller_address || '';
        document.getElementById('einvLocation').value = sellerConfig.seller_location || '';
        document.getElementById('einvPincode').value = sellerConfig.seller_pincode || '';
        document.getElementById('einvStateCode').value = sellerConfig.port_gst_state_code || '';
        document.getElementById('einvPhone').value = sellerConfig.seller_phone || '';
        document.getElementById('einvEmail').value = sellerConfig.seller_email || '';
        document.getElementById('einvCount').value = ids.length + ' invoice(s) selected';
        document.getElementById('einvoiceModal').style.display = 'block';
    }
}

function closeModal(id) {
    document.getElementById(id).style.display = 'none';
}

function downloadJson(data, filename) {
    const blob = new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

async function exportGSTR1() {
    const ids = getSelectedIds();
    const gstin = document.getElementById('gstr1Gstin').value.trim();
    const month = document.getElementById('gstr1Month').value;
    const year = document.getElementById('gstr1Year').value;
    const period = month + year;

    if (!gstin) { alert('Please enter Supplier GSTIN'); return; }

    const res = await fetch('/api/module/FIN01/export/gstr1-b2b', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            invoice_ids: ids,
            supplier_gstin: gstin,
            filing_period: period
        })
    });
    const json = await res.json();

    if (json.error) {
        alert('Error: ' + json.error);
        return;
    }

    downloadJson(json, `GSTR1_B2B_${period}.json`);
    closeModal('gstr1Modal');
    alert(`GSTR-1 B2B JSON exported for ${ids.length} invoice(s). Upload this file to the GST portal via Returns > GSTR-1 > Prepare Offline > Upload.`);
}

async function exportEInvoice() {
    const ids = getSelectedIds();
    const gstin = document.getElementById('einvGstin').value.trim();
    const legalName = document.getElementById('einvLegalName').value.trim();
    const address = document.getElementById('einvAddress').value.trim();
    const location = document.getElementById('einvLocation').value.trim();
    const pincode = document.getElementById('einvPincode').value.trim();
    const stateCode = document.getElementById('einvStateCode').value.trim();

    if (!gstin || !legalName || !address || !location || !pincode || !stateCode) {
        alert('Please fill all required seller details (GSTIN, Legal Name, Address, Location, Pincode, State Code)');
        return;
    }

    const res = await fetch('/api/module/FIN01/export/einvoice', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            invoice_ids: ids,
            seller_details: {
                gstin: gstin,
                legal_name: legalName,
                address1: address,
                location: location,
                pincode: pincode,
                state_code: stateCode,
                phone: document.getElementById('einvPhone').value.trim(),
                email: document.getElementById('einvEmail').value.trim()
            }
        })
    });
    const json = await res.json();

    if (json.error) {
        alert('Error: ' + json.error);
        return;
    }

    // If single invoice, download as single object; if multiple, download array
    const einvoices = json.einvoices || [];
    if (einvoices.length === 1) {
        downloadJson(einvoices[0], `EInvoice_${einvoices[0].DocDtls.No}.json`);
    } else {
        downloadJson(einvoices, `EInvoices_Batch_${ids.length}.json`);
    }
    closeModal('einvoiceModal');
    alert(`e-Invoice JSON exported for ${einvoices.length} invoice(s). Upload to e-Invoice portal (einvoice1.gst.gov.in) for IRN generation.`);
}

function printInvoice(id) {
    window.open(`/module/FIN01/invoice/print/${id}`, '_blank');
}

async function postToGST(id) {
    if (!confirm('Post this invoice to GST portal?')) return;
    alert('GST API integration pending. Will generate IRN and QR code.');
}

async function postToSAP(id) {
    if (!confirm('Export this invoice to SAP?')) return;
    alert('SAP export pending. Will generate CSV/XML file.');
}

