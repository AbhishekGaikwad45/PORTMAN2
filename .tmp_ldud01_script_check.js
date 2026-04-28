addToRecent('LDUD01', 'Loading Unloading');

    let table;
    let vcnList = [];
    let delayTypes = [];
    let bargeList = [];
    let contractorList = [];
    let cargoNames = [];
    let anchorageNames = [];
    let payloaderList = [];
    let subTables = {};
    let stowagePlanData = {}; // Store stowage plan data per LDUD ID
    let stowageHoldMeta = {}; // Hold metadata per LDUD ID
    let vesselOpsHoldFields = {}; // Dynamic vessel ops hold columns per LDUD ID
    let currentLdudId = null;

    const currentUser = '0';
    const permissions = {
        can_read: 0,
        can_add: 0,
        can_edit: 0,
        can_delete: 0
    };

    function getTodayDate() {
        return new Date().toISOString().split('T')[0];
    }

    function showStatus(message, type) {
        const status = document.getElementById('saveStatus');
        status.textContent = message;
        status.className = 'save-status ' + type;
        if (type === 'saved') {
            setTimeout(() => { status.textContent = ''; status.className = 'save-status'; }, 2000);
        }
    }

    async function loadMasterData() {
        const [vcnRes, delayRes, bargeRes, contractorRes, cargoRes, ancRes, pplRes] = await Promise.all([
            fetch('/api/module/LDUD01/vcn_list'),
            fetch('/api/module/VDM01/all'),
            fetch('/api/module/VBM01/all'),
            fetch('/api/module/VCTM01/all'),
            fetch('/api/module/VCG01/names'),
            fetch('/api/module/VANM01/all'),
            fetch('/api/module/PPL01/all')
        ]);
        vcnList = await vcnRes.json();
        delayTypes = await delayRes.json();
        bargeList = await bargeRes.json();
        contractorList = await contractorRes.json();
        cargoNames = await cargoRes.json();
        anchorageNames = await ancRes.json();
        payloaderList = await pplRes.json();
        initTable();
    }

    // Custom datetime editor
    var datetimeEditor = function(cell, onRendered, success, cancel) {
        var cellValue = cell.getValue() || '';
        var input = document.createElement("input");
        input.type = "datetime-local";
        input.value = cellValue;
        input.style.width = "100%";
        input.style.boxSizing = "border-box";
        input.style.padding = "4px";

        onRendered(function() {
            input.focus();
            input.style.height = "100%";
        });

        input.addEventListener("change", function() { success(input.value); });
        input.addEventListener("blur", function() { success(input.value); });
        input.addEventListener("keydown", function(e) {
            if (e.key === "Enter") success(input.value);
            if (e.key === "Escape") cancel();
        });
        return input;
    };

    // Custom date editor
    var dateEditor = function(cell, onRendered, success, cancel) {
        var cellValue = cell.getValue() || '';
        var input = document.createElement("input");
        input.type = "date";
        input.value = cellValue;
        input.style.width = "100%";
        input.style.boxSizing = "border-box";
        input.style.padding = "4px";

        onRendered(function() {
            input.focus();
            input.style.height = "100%";
        });

        input.addEventListener("change", function() { success(input.value); });
        input.addEventListener("blur", function() { success(input.value); });
        input.addEventListener("keydown", function(e) {
            if (e.key === "Enter") success(input.value);
            if (e.key === "Escape") cancel();
        });
        return input;
    };

    function normalizeDate(value) {
        if (!value) return '';
        const str = String(value).trim();
        if (!str) return '';
        if (str.length >= 10) return str.slice(0, 10);
        return str;
    }

    function sortHoldNames(a, b) {
        const aNumMatch = String(a).match(/\d+/);
        const bNumMatch = String(b).match(/\d+/);
        const aNum = aNumMatch ? parseInt(aNumMatch[0], 10) : NaN;
        const bNum = bNumMatch ? parseInt(bNumMatch[0], 10) : NaN;

        if (!Number.isNaN(aNum) && !Number.isNaN(bNum) && aNum !== bNum) {
            return aNum - bNum;
        }
        return String(a).localeCompare(String(b));
    }

    function getHoldDefs(ldudId) {
        return vesselOpsHoldFields[ldudId] || [];
    }

    function buildVesselOpsRowsFromApi(ldudId, apiRows) {
        const holdDefs = getHoldDefs(ldudId);
        const holdByName = {};
        holdDefs.forEach(def => { holdByName[def.hold_name] = def; });

        const grouped = {};
        (apiRows || []).forEach(r => {
            const def = holdByName[r.hold_name];
            if (!def) return;

            const opDate = normalizeDate(r.start_time || r.end_time);
            const key = opDate || '__NO_DATE__';
            if (!grouped[key]) {
                const row = {op_date: opDate, __cellIds: {}};
                holdDefs.forEach(d => {
                    row[d.field] = '';
                    row.__cellIds[d.field] = [];
                });
                grouped[key] = row;
            }

            const row = grouped[key];
            const qty = parseFloat(r.quantity || 0);
            const current = parseFloat(row[def.field] || 0);
            row[def.field] = (current + (Number.isFinite(qty) ? qty : 0));
            row.__cellIds[def.field].push(r.id);
        });

        return Object.values(grouped).sort((a, b) => (a.op_date || '').localeCompare(b.op_date || ''));
    }

    function getVesselOpsDischargedByHold(ldudId) {
        const dischargedByHold = {};
        const holdDefs = getHoldDefs(ldudId);
        const tableRef = subTables[ldudId] && subTables[ldudId].vessel_ops;
        if (!tableRef) return dischargedByHold;

        tableRef.getRows().forEach(row => {
            const data = row.getData();
            holdDefs.forEach(def => {
                const qty = parseFloat(data[def.field] || 0);
                if (!Number.isFinite(qty) || qty <= 0) return;
                if (!dischargedByHold[def.hold_name]) dischargedByHold[def.hold_name] = 0;
                dischargedByHold[def.hold_name] += qty;
            });
        });

        return dischargedByHold;
    }

    async function saveVesselOpsCell(payload) {
        const res = await fetch('/api/module/LDUD01/vessel_ops/save', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });
        const result = await res.json();
        if (!res.ok || !result.success || !result.id) {
            throw new Error(result.error || 'Failed to save vessel operation cell');
        }
        return result.id;
    }

    async function deleteVesselOpsCell(id) {
        const res = await fetch('/api/module/LDUD01/vessel_ops/delete', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({id})
        });
        const result = await res.json();
        if (!res.ok || !result.success) {
            throw new Error(result.error || 'Failed to delete vessel operation cell');
        }
    }

    function addVesselOpsDateRow(ldudId) {
        const tableRef = subTables[ldudId] && subTables[ldudId].vessel_ops;
        if (!tableRef) return;
        const holdDefs = getHoldDefs(ldudId);
        const newRow = {op_date: getTodayDate(), __cellIds: {}};
        holdDefs.forEach(def => {
            newRow[def.field] = '';
            newRow.__cellIds[def.field] = [];
        });
        tableRef.addRow(newRow, true);
        updateHoldSummary(ldudId);
    }

    async function deleteVesselOpsDateRow(ldudId, row) {
        if (!confirm('Delete this date row?')) return;

        const data = row.getData();
        const holdDefs = getHoldDefs(ldudId);
        try {
            for (const def of holdDefs) {
                const ids = (data.__cellIds && Array.isArray(data.__cellIds[def.field])) ? data.__cellIds[def.field] : [];
                for (const id of ids) {
                    await deleteVesselOpsCell(id);
                }
            }
            row.delete();
            updateHoldSummary(ldudId);
        } catch (err) {
            alert(`Error deleting vessel operation row: ${err.message}`);
        }
    }

    async function saveVesselOpsTable(ldudId) {
        const tableRef = subTables[ldudId] && subTables[ldudId].vessel_ops;
        if (!tableRef) return;

        const holdDefs = getHoldDefs(ldudId);
        const rows = tableRef.getRows();

        for (const row of rows) {
            const data = row.getData();
            const opDate = normalizeDate(data.op_date);
            const hasQty = holdDefs.some(def => {
                const qty = parseFloat(data[def.field]);
                return Number.isFinite(qty) && qty > 0;
            });

            if (hasQty && !opDate) {
                alert('Date is required for rows where discharge quantity is entered.');
                return;
            }
        }

        let savedCount = 0;
        let deletedCount = 0;

        try {
            for (const row of rows) {
                const data = row.getData();
                const opDate = normalizeDate(data.op_date);
                if (!data.__cellIds || typeof data.__cellIds !== 'object') {
                    data.__cellIds = {};
                }

                for (const def of holdDefs) {
                    const rawQty = data[def.field];
                    const parsedQty = parseFloat(rawQty);
                    const hasQty = Number.isFinite(parsedQty) && parsedQty > 0;
                    const ids = Array.isArray(data.__cellIds[def.field]) ? [...data.__cellIds[def.field]] : [];

                    if (hasQty) {
                        const payload = {
                            ldud_id: ldudId,
                            hold_name: def.hold_name,
                            start_time: opDate,
                            end_time: null,
                            cargo_name: def.cargo_name || null,
                            quantity: parsedQty
                        };

                        if (ids.length > 0) {
                            payload.id = ids[0];
                        }

                        const savedId = await saveVesselOpsCell(payload);
                        savedCount++;

                        const keepIds = [savedId];
                        const staleIds = ids.filter(x => x !== savedId);
                        for (const staleId of staleIds) {
                            await deleteVesselOpsCell(staleId);
                            deletedCount++;
                        }
                        data.__cellIds[def.field] = keepIds;
                    } else {
                        for (const id of ids) {
                            await deleteVesselOpsCell(id);
                            deletedCount++;
                        }
                        data.__cellIds[def.field] = [];
                    }
                }

                row.update({op_date: opDate, __cellIds: data.__cellIds});
            }

            await tableRef.setData(`/api/module/LDUD01/vessel_ops/${ldudId}`);
            updateHoldSummary(ldudId);
            alert(`Saved ${savedCount} cell(s)${deletedCount ? `, removed ${deletedCount} empty cell(s)` : ''}`);
        } catch (err) {
            alert(`Error saving vessel operations: ${err.message}`);
        }
    }

    function initTable() {
        const canEdit = permissions.can_edit || permissions.can_add;
        const vcnOptions = {};
        vcnList.forEach(v => { vcnOptions[v.value] = v.value; });

        const columns = [
            {formatter: "rowSelection", titleFormatter: "rowSelection", hozAlign: "center", headerSort: false, width: 40},
            {
                title: "Details",
                formatter: function(cell) {
                    const data = cell.getRow().getData();
                    if (!data.id) return '';
                    return '<button class="btn-open-details">+</button>';
                },
                width: 70,
                hozAlign: "center",
                headerSort: false,
                cellClick: function(e, cell) {
                    const row = cell.getRow();
                    const data = row.getData();
                    if (!data.id) return;
                    openDetailsModal(data);
                }
            },
            {title: "Doc Num", field: "doc_num", width: 80},
            {title: "VCN / Vessel / Anchored", field: "vcn_display", editor: canEdit ? "list" : false,
                editorParams: {values: vcnOptions, autocomplete: true, allowEmpty: true}, width: 250,
                cellEdited: function(cell) {
                    const val = cell.getValue();
                    const vcn = vcnList.find(v => v.value === val);
                    if (vcn) {
                        cell.getRow().update({
                            vcn_id: vcn.vcn_id,
                            vcn_doc_num: vcn.vcn_doc_num,
                            vessel_name: vcn.vessel_name,
                            anchored_datetime: vcn.anchored_datetime
                        });
                    }
                }
            },
            {title: "Arrival Inner Anch", field: "arrival_inner_anchorage", editor: canEdit ? datetimeEditor : false, width: 140,
                formatter: function(cell) { return cell.getValue() ? cell.getValue().replace('T', ' ') : ''; }},
            {title: "Arrival Outer Anch", field: "arrival_outer_anchorage", editor: canEdit ? datetimeEditor : false, width: 140,
                formatter: function(cell) { return cell.getValue() ? cell.getValue().replace('T', ' ') : ''; }},
            {title: "Arrived MBPT", field: "arrived_mbpt", editor: canEdit ? datetimeEditor : false, width: 140,
                formatter: function(cell) { return cell.getValue() ? cell.getValue().replace('T', ' ') : ''; }},
            {title: "Arrived MFL", field: "arrived_mfl", editor: canEdit ? datetimeEditor : false, width: 140,
                formatter: function(cell) { return cell.getValue() ? cell.getValue().replace('T', ' ') : ''; }},
            {title: "Free Pratique", field: "free_pratique_granted", editor: canEdit ? datetimeEditor : false, width: 140,
                formatter: function(cell) { return cell.getValue() ? cell.getValue().replace('T', ' ') : ''; }},
            {title: "NOR Tendered", field: "nor_tendered", editor: canEdit ? datetimeEditor : false, width: 140,
                formatter: function(cell) { return cell.getValue() ? cell.getValue().replace('T', ' ') : ''; }},
            {title: "NOR Accepted", field: "nor_accepted", editor: canEdit ? datetimeEditor : false, width: 140,
                formatter: function(cell) { return cell.getValue() ? cell.getValue().replace('T', ' ') : ''; }},
            {title: "Discharge Start", field: "discharge_commenced", editor: canEdit ? datetimeEditor : false, width: 140,
                formatter: function(cell) { return cell.getValue() ? cell.getValue().replace('T', ' ') : ''; }},
            {title: "Discharge End", field: "discharge_completed", editor: canEdit ? datetimeEditor : false, width: 140,
                formatter: function(cell) { return cell.getValue() ? cell.getValue().replace('T', ' ') : ''; }},
            {title: "Init Survey From", field: "initial_draft_survey_from", editor: canEdit ? datetimeEditor : false, width: 140,
                formatter: function(cell) { return cell.getValue() ? cell.getValue().replace('T', ' ') : ''; }},
            {title: "Init Survey To", field: "initial_draft_survey_to", editor: canEdit ? datetimeEditor : false, width: 140,
                formatter: function(cell) { return cell.getValue() ? cell.getValue().replace('T', ' ') : ''; }},
            {title: "Init Survey Qty", field: "initial_draft_survey_quantity", editor: canEdit ? "number" : false, width: 100, hozAlign: "right"},
            {title: "Final Survey From", field: "final_draft_survey_from", editor: canEdit ? datetimeEditor : false, width: 140,
                formatter: function(cell) { return cell.getValue() ? cell.getValue().replace('T', ' ') : ''; }},
            {title: "Final Survey To", field: "final_draft_survey_to", editor: canEdit ? datetimeEditor : false, width: 140,
                formatter: function(cell) { return cell.getValue() ? cell.getValue().replace('T', ' ') : ''; }},
            {title: "Custom Clearance", field: "custom_clearance", editor: canEdit ? datetimeEditor : false, width: 140,
                formatter: function(cell) { return cell.getValue() ? cell.getValue().replace('T', ' ') : ''; }},
            {title: "Agent/Custom/Stevedore On Board", field: "agent_stevedore_onboard", editor: canEdit ? datetimeEditor : false, width: 200,
                formatter: function(cell) { return cell.getValue() ? cell.getValue().replace('T', ' ') : ''; }},
            {title: "Status", field: "doc_status", width: 80,
                formatter: function(cell) {
                    const val = cell.getValue();
                    let color = '#718096';
                    if (val === 'Approved') color = '#38a169';
                    else if (val === 'Rejected') color = '#e53e3e';
                    else if (val === 'Pending') color = '#d69e2e';
                    return `<span style="color:${color};font-weight:500">${val || ''}</span>`;
                }
            },
            {title: "Created By", field: "created_by", width: 90}
        ];

        table = new Tabulator("#table", {
            height: "calc(100vh - 160px)",
            layout: "fitDataFill",
            columns: columns,
            pagination: true,
            paginationMode: "remote",
            paginationSize: 20,
            ajaxURL: "/api/module/LDUD01/data",
            ajaxResponse: function(url, params, response) {
                // Build display field
                response.data.forEach(r => {
                    r.vcn_display = r.vcn_doc_num ? `${r.vcn_doc_num} / ${r.vessel_name || ''}` : '';
                    if (r.anchored_datetime) r.vcn_display += ` / ${r.anchored_datetime.replace('T', ' ')}`;
                });
                document.getElementById('rowCount').textContent = response.data.length;
                document.getElementById('totalCount').textContent = response.total;
                return response;
            },
            selectable: true
        });

        if (localStorage.getItem('theme') === 'dark') {
            document.getElementById('table').classList.add('tabulator-dark');
        }
    }

    async function openDetailsModal(data) {
        const ldudId = data.id;
        currentLdudId = ldudId;

        // Set modal title
        document.getElementById('modalTitle').textContent = `Details for ${data.doc_num || 'LDUD'}`;

        // Clear previous content
        const modalBody = document.getElementById('modalSubTables');
        modalBody.innerHTML = '';

        // Create the sub-table container
        const subContainer = document.createElement('div');
        subContainer.className = 'sub-table-container';
        subContainer.innerHTML = `
            <div class="sub-section">
                <div class="sub-section-header">
                    <span>Delays</span>
                    <div class="sub-section-actions">
                        ${(permissions.can_edit || permissions.can_add) ? `<button class="btn-sub-add" onclick="addSubRow('delays', ${ldudId})">+ Add</button>` : ''}
                        ${(permissions.can_edit || permissions.can_add) ? `<button class="btn-sub-save" onclick="saveSubTable('delays', ${ldudId})">Save</button>` : ''}
                    </div>
                </div>
                <div class="sub-section-content"><div id="delays-table-${ldudId}" class="sub-tabulator"></div></div>
            </div>
            <div class="sub-section">
                <div class="sub-section-header">
                    <span>Anchorage Recording</span>
                    <div class="sub-section-actions">
                        ${(permissions.can_edit || permissions.can_add) ? `<button class="btn-sub-add" onclick="addSubRow('anchorage', ${ldudId})">+ Add</button>` : ''}
                        ${(permissions.can_edit || permissions.can_add) ? `<button class="btn-sub-save" onclick="saveSubTable('anchorage', ${ldudId})">Save</button>` : ''}
                    </div>
                </div>
                <div class="sub-section-content"><div id="anchorage-table-${ldudId}" class="sub-tabulator"></div></div>
            </div>
            <div class="sub-section">
                <div class="sub-section-header">
                    <span>Vessel Operations</span>
                    <div class="sub-section-actions">
                        ${(permissions.can_edit || permissions.can_add) ? `<button class="btn-sub-add" onclick="addVesselOpsDateRow(${ldudId})">+ Add</button>` : ''}
                        ${(permissions.can_edit || permissions.can_add) ? `<button class="btn-sub-save" onclick="saveVesselOpsTable(${ldudId})">Save</button>` : ''}
                    </div>
                </div>
                <div class="sub-section-content">
                    <div id="hold-summary-${ldudId}" style="padding: 10px; background: #f1f5f9; border-bottom: 1px solid #cbd5e0; font-size: 12px;"></div>
                    <div id="vessel_ops-table-${ldudId}" class="sub-tabulator"></div>
                </div>
            </div>
            <div class="sub-section">
                <div class="sub-section-header">
                    <span>Barge Lines</span>
                    <div class="sub-section-actions">
                        ${(permissions.can_edit || permissions.can_add) ? `<button class="btn-sub-add" onclick="addSubRow('barge_lines', ${ldudId})">+ Add</button>` : ''}
                        ${(permissions.can_edit || permissions.can_add) ? `<button class="btn-sub-save" onclick="saveSubTable('barge_lines', ${ldudId})">Save</button>` : ''}
                    </div>
                </div>
                <div class="sub-section-content">
                    <div id="barge_lines-table-${ldudId}" class="sub-tabulator"></div>
                </div>
            </div>
            <div class="sub-section">
                <div class="sub-section-header">
                    <span>Barge Cleaning Lines</span>
                    <div class="sub-section-actions">
                        ${(permissions.can_edit || permissions.can_add) ? `<button class="btn-sub-add" onclick="addSubRow('barge_cleaning', ${ldudId})">+ Add</button>` : ''}
                        ${(permissions.can_edit || permissions.can_add) ? `<button class="btn-sub-save" onclick="saveSubTable('barge_cleaning', ${ldudId})">Save</button>` : ''}
                    </div>
                </div>
                <div class="sub-section-content"><div id="barge_cleaning-table-${ldudId}" class="sub-tabulator"></div></div>
            </div>`;

        // Append to modal body
        modalBody.appendChild(subContainer);

        // Show the modal
        document.getElementById('detailsModal').classList.add('active');

        // Initialize sub-tables
        subTables[ldudId] = {};
        await initSubTables(ldudId);
    }

    function closeDetailsModal() {
        const modal = document.getElementById('detailsModal');
        modal.classList.remove('active');

        // Clean up sub-tables
        if (currentLdudId && subTables[currentLdudId]) {
            Object.values(subTables[currentLdudId]).forEach(t => {
                if (t && typeof t.destroy === 'function') {
                    t.destroy();
                }
            });
            delete subTables[currentLdudId];
        }

        // Clear modal content
        document.getElementById('modalSubTables').innerHTML = '';
        currentLdudId = null;
    }

    // Close modal when clicking outside
    document.addEventListener('DOMContentLoaded', function() {
        const modal = document.getElementById('detailsModal');
        modal.addEventListener('click', function(e) {
            if (e.target === modal) {
                closeDetailsModal();
            }
        });

        // Close on escape key
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape' && modal.classList.contains('active')) {
                closeDetailsModal();
            }
        });
    });

    async function initSubTables(ldudId) {
        const canEdit = permissions.can_edit || permissions.can_add;
        const isDark = localStorage.getItem('theme') === 'dark';

        // Get VCN ID from main table row
        const mainRow = table.getRows().find(r => r.getData().id === ldudId);
        const vcnId = mainRow ? mainRow.getData().vcn_id : null;

        // Fetch stowage plan for this VCN
        let holdOptions = {};
        stowageHoldMeta[ldudId] = {};
        vesselOpsHoldFields[ldudId] = [];
        if (vcnId) {
            const stowageRes = await fetch(`/api/module/VCN01/stowage/${vcnId}`);
            const stowageData = await stowageRes.json();
            stowagePlanData[ldudId] = stowageData;

            // Build unique holds with their total quantities
            const holdMap = {};
            const cargoMap = {};
            stowageData.forEach(s => {
                if (s.hold_name) {
                    if (!holdMap[s.hold_name]) {
                        holdMap[s.hold_name] = 0;
                    }
                    holdMap[s.hold_name] += parseFloat(s.hatchwise_quantity || 0);

                    if (!cargoMap[s.hold_name]) {
                        cargoMap[s.hold_name] = new Set();
                    }
                    if (s.cargo_name) {
                        cargoMap[s.hold_name].add(s.cargo_name);
                    }
                }
            });

            const holdNames = Object.keys(holdMap).sort(sortHoldNames);
            holdNames.forEach(h => {
                holdOptions[h] = h;
                const cargoNamesForHold = cargoMap[h] ? Array.from(cargoMap[h]).join(', ') : '';
                stowageHoldMeta[ldudId][h] = {
                    stowage_qty: holdMap[h] || 0,
                    cargo_name: cargoNamesForHold
                };
            });

            vesselOpsHoldFields[ldudId] = holdNames.map((holdName, idx) => ({
                hold_name: holdName,
                field: `hold_${idx + 1}`,
                stowage_qty: stowageHoldMeta[ldudId][holdName] ? stowageHoldMeta[ldudId][holdName].stowage_qty : 0,
                cargo_name: stowageHoldMeta[ldudId][holdName] ? stowageHoldMeta[ldudId][holdName].cargo_name : ''
            }));
        } else {
            stowagePlanData[ldudId] = [];
        }

        const delayOptions = {};
        delayTypes.forEach(d => { delayOptions[d] = d; });

        const bargeOptions = {};
        bargeList.forEach(b => { bargeOptions[b] = b; });

        const contractorOptions = {};
        contractorList.forEach(c => { contractorOptions[c] = c; });

        const cargoOptions = {};
        cargoNames.forEach(c => { cargoOptions[c] = c; });

        const yesNoOptions = {'Yes': 'Yes', 'No': 'No'};
        const bptBflOptions = {'BPT': 'BPT', 'BFL': 'BFL'};

        // Crane Number multiselect dropdown editor
        var craneMultiSelectEditor = function(cell, onRendered, success, cancel) {
            var currentVal = cell.getValue() || '';
            var selected = currentVal ? currentVal.split(',').map(s => s.trim()) : [];

            var wrapper = document.createElement('div');
            wrapper.style.cssText = 'width:100%;height:100%;padding:4px;box-sizing:border-box;font-size:11px;cursor:pointer;';
            wrapper.textContent = currentVal || 'Select...';

            // Dropdown appended to body to avoid Tabulator overflow clipping
            var dropdown = document.createElement('div');
            dropdown.style.cssText = 'position:fixed;z-index:99999;background:white;border:1px solid #cbd5e0;border-radius:6px;box-shadow:0 4px 12px rgba(0,0,0,0.15);padding:8px;min-width:140px;display:none;';

            ['1','2','3','4','5','6'].forEach(function(num) {
                var label = document.createElement('label');
                label.style.cssText = 'display:flex;align-items:center;gap:8px;padding:4px 6px;font-size:12px;cursor:pointer;border-radius:4px;';
                label.addEventListener('mouseenter', function() { label.style.background = '#f1f5f9'; });
                label.addEventListener('mouseleave', function() { label.style.background = 'none'; });
                var cb = document.createElement('input');
                cb.type = 'checkbox';
                cb.value = num;
                cb.checked = selected.includes(num);
                cb.style.cssText = 'margin:0;cursor:pointer;width:14px;height:14px;';
                label.appendChild(cb);
                label.appendChild(document.createTextNode('Crane ' + num));
                dropdown.appendChild(label);
            });

            var btnRow = document.createElement('div');
            btnRow.style.cssText = 'display:flex;gap:6px;margin-top:8px;padding-top:8px;border-top:1px solid #e2e8f0;';

            var confirmBtn = document.createElement('button');
            confirmBtn.textContent = 'Apply';
            confirmBtn.style.cssText = 'flex:1;padding:4px 8px;font-size:11px;background:#3182ce;color:white;border:none;border-radius:4px;cursor:pointer;font-weight:500;';
            confirmBtn.addEventListener('click', function(e) {
                e.stopPropagation();
                var checks = dropdown.querySelectorAll('input[type=checkbox]:checked');
                var vals = Array.from(checks).map(c => c.value);
                cleanup();
                success(vals.join(', '));
            });

            var cancelBtn = document.createElement('button');
            cancelBtn.textContent = 'Cancel';
            cancelBtn.style.cssText = 'flex:1;padding:4px 8px;font-size:11px;background:#e2e8f0;color:#374151;border:none;border-radius:4px;cursor:pointer;font-weight:500;';
            cancelBtn.addEventListener('click', function(e) {
                e.stopPropagation();
                cleanup();
                cancel();
            });

            btnRow.appendChild(confirmBtn);
            btnRow.appendChild(cancelBtn);
            dropdown.appendChild(btnRow);
            document.body.appendChild(dropdown);

            function cleanup() {
                if (dropdown.parentNode) dropdown.parentNode.removeChild(dropdown);
                document.removeEventListener('mousedown', outsideClick);
            }

            function outsideClick(e) {
                if (!dropdown.contains(e.target) && !wrapper.contains(e.target)) {
                    cleanup();
                    cancel();
                }
            }

            onRendered(function() {
                var rect = cell.getElement().getBoundingClientRect();
                dropdown.style.left = rect.left + 'px';
                dropdown.style.top = (rect.bottom + 2) + 'px';
                dropdown.style.display = 'block';
                setTimeout(function() { document.addEventListener('mousedown', outsideClick); }, 10);
            });

            wrapper.addEventListener('keydown', function(e) {
                if (e.key === 'Escape') { cleanup(); cancel(); }
                if (e.key === 'Enter') {
                    var checks = dropdown.querySelectorAll('input[type=checkbox]:checked');
                    var vals = Array.from(checks).map(c => c.value);
                    cleanup();
                    success(vals.join(', '));
                }
            });

            return wrapper;
        };

        // Delays table
        subTables[ldudId].delays = new Tabulator(`#delays-table-${ldudId}`, {
            layout: "fitDataFill",
            height: 200,
            ajaxURL: `/api/module/LDUD01/delays/${ldudId}`,
            columns: [
                {title: "Crane No", field: "crane_number", width: 110, editor: canEdit ? craneMultiSelectEditor : false,
                    formatter: function(cell) {
                        var val = cell.getValue();
                        if (!val) return '';
                        return val.split(',').map(function(v) {
                            return '<span style="background:#3182ce;color:white;padding:1px 6px;border-radius:3px;font-size:10px;margin-right:2px;">' + v.trim() + '</span>';
                        }).join('');
                    }
                },
                {title: "Delay Name", field: "delay_name", width: 120, editor: canEdit ? "list" : false,
                    editorParams: {values: delayOptions, autocomplete: true, allowEmpty: true}},
                {title: "Start", field: "start_datetime", width: 140, editor: canEdit ? datetimeEditor : false,
                    formatter: function(cell) { return cell.getValue() ? cell.getValue().replace('T', ' ') : ''; }},
                {title: "End", field: "end_datetime", width: 140, editor: canEdit ? datetimeEditor : false,
                    formatter: function(cell) { return cell.getValue() ? cell.getValue().replace('T', ' ') : ''; }},
                {title: "Mins", field: "total_time_mins", width: 60, hozAlign: "right"},
                {title: "Hrs", field: "total_time_hrs", width: 60, hozAlign: "right"},
                {title: "Minus Hrs", field: "minus_delay_hours", width: 70, editor: canEdit ? "list" : false,
                    editorParams: {values: yesNoOptions}},
                canEdit ? {title: "", field: "actions", formatter: deleteButtonFormatter, width: 50, hozAlign: "center", headerSort: false,
                    cellClick: function(e, cell) { deleteSubRow('delays', cell.getRow().getData().id, ldudId); }
                } : null
            ].filter(Boolean)
        });
        if (isDark) document.querySelector(`#delays-table-${ldudId}`).classList.add('tabulator-dark');

        // Anchorage Recording table
        const anchorageOptions = {};
        anchorageNames.forEach(a => { anchorageOptions[a] = a; });

        subTables[ldudId].anchorage = new Tabulator(`#anchorage-table-${ldudId}`, {
            layout: "fitColumns",
            height: 200,
            ajaxURL: `/api/module/LDUD01/anchorage/${ldudId}`,
            columns: [
                {title: "Anchorage Name", field: "anchorage_name", widthGrow: 1, editor: canEdit ? "list" : false,
                    editorParams: {values: anchorageOptions, autocomplete: true, allowEmpty: true}},
                {title: "Anchored", field: "anchored", widthGrow: 1, editor: canEdit ? datetimeEditor : false,
                    formatter: function(cell) { return cell.getValue() ? cell.getValue().replace('T', ' ') : ''; }},
                {title: "Discharge Started", field: "discharge_started", widthGrow: 1, editor: canEdit ? datetimeEditor : false,
                    formatter: function(cell) { return cell.getValue() ? cell.getValue().replace('T', ' ') : ''; }},
                {title: "Discharge Commenced", field: "discharge_commenced", widthGrow: 1, editor: canEdit ? datetimeEditor : false,
                    formatter: function(cell) { return cell.getValue() ? cell.getValue().replace('T', ' ') : ''; }},
                {title: "Anchor Aweigh", field: "anchor_aweigh", widthGrow: 1, editor: canEdit ? datetimeEditor : false,
                    formatter: function(cell) { return cell.getValue() ? cell.getValue().replace('T', ' ') : ''; }},
                {title: "Cargo Quantity", field: "cargo_quantity", widthGrow: 1, editor: canEdit ? "number" : false, hozAlign: "right",
                    editorParams: {min: 0, step: 0.01}},
                canEdit ? {title: "", field: "actions", formatter: deleteButtonFormatter, width: 50, widthGrow: 0, hozAlign: "center", headerSort: false,
                    cellClick: function(e, cell) { deleteSubRow('anchorage', cell.getRow().getData().id, ldudId); }
                } : null
            ].filter(Boolean)
        });
        if (isDark) document.querySelector(`#anchorage-table-${ldudId}`).classList.add('tabulator-dark');

        // Barge Lines table
        subTables[ldudId].barge_lines = new Tabulator(`#barge_lines-table-${ldudId}`, {
            layout: "fitDataFill",
            height: 250,
            ajaxURL: `/api/module/LDUD01/barge_lines/${ldudId}`,
            ajaxResponse: function(url, params, response) {
                return response;
            },
            columns: [
                {title: "Trip#", field: "trip_number", width: 50, hozAlign: "center"},
                {title: "Hold", field: "hold_name", width: 80, editor: canEdit ? "list" : false,
                    editorParams: {values: holdOptions, autocomplete: true, allowEmpty: true}
                },
                {title: "Barge", field: "barge_name", width: 100, editor: canEdit ? "list" : false,
                    editorParams: {values: bargeOptions, autocomplete: true, allowEmpty: true}},
                {title: "Contractor", field: "contractor_name", width: 120, editor: canEdit ? "list" : false,
                    editorParams: {values: contractorOptions, autocomplete: true, allowEmpty: true}},
                {title: "Cargo", field: "cargo_name", width: 100, editor: canEdit ? "list" : false,
                    editorParams: {values: cargoOptions, autocomplete: true, allowEmpty: true}},
                {title: "BPT/BFL", field: "bpt_bfl", width: 70, editor: canEdit ? "list" : false,
                    editorParams: {values: bptBflOptions}},
                {title: "Alongside Vessel", field: "along_side_vessel", width: 130, editor: canEdit ? datetimeEditor : false,
                    formatter: function(cell) { return cell.getValue() ? cell.getValue().replace('T', ' ') : ''; }},
                {title: "Loading Start", field: "commenced_loading", width: 130, editor: canEdit ? datetimeEditor : false,
                    formatter: function(cell) { return cell.getValue() ? cell.getValue().replace('T', ' ') : ''; }},
                {title: "Loading End", field: "completed_loading", width: 130, editor: canEdit ? datetimeEditor : false,
                    formatter: function(cell) { return cell.getValue() ? cell.getValue().replace('T', ' ') : ''; }},
                {title: "Cast Off MV", field: "cast_off_mv", width: 130, editor: canEdit ? datetimeEditor : false,
                    formatter: function(cell) { return cell.getValue() ? cell.getValue().replace('T', ' ') : ''; }},
                {title: "Anch Gull Island", field: "anchored_gull_island", width: 130, editor: canEdit ? datetimeEditor : false,
                    formatter: function(cell) { return cell.getValue() ? cell.getValue().replace('T', ' ') : ''; }},
                {title: "Aweigh Gull Island", field: "aweigh_gull_island", width: 130, editor: canEdit ? datetimeEditor : false,
                    formatter: function(cell) { return cell.getValue() ? cell.getValue().replace('T', ' ') : ''; }},
                {title: "Alongside Berth", field: "along_side_berth", width: 130, editor: canEdit ? datetimeEditor : false,
                    formatter: function(cell) { return cell.getValue() ? cell.getValue().replace('T', ' ') : ''; }},
                {title: "Discharge Start", field: "commence_discharge_berth", width: 130, editor: canEdit ? datetimeEditor : false,
                    formatter: function(cell) { return cell.getValue() ? cell.getValue().replace('T', ' ') : ''; }},
                {title: "Discharge End", field: "completed_discharge_berth", width: 130, editor: canEdit ? datetimeEditor : false,
                    formatter: function(cell) { return cell.getValue() ? cell.getValue().replace('T', ' ') : ''; }},
                {title: "Cast Off Berth", field: "cast_off_berth", width: 130, editor: canEdit ? datetimeEditor : false,
                    formatter: function(cell) { return cell.getValue() ? cell.getValue().replace('T', ' ') : ''; }},
                {title: "Cast Off NT", field: "cast_off_berth_nt", width: 130, editor: canEdit ? datetimeEditor : false,
                    formatter: function(cell) { return cell.getValue() ? cell.getValue().replace('T', ' ') : ''; }},
                {title: "Qty", field: "discharge_quantity", width: 80, editor: canEdit ? "number" : false, hozAlign: "right",
                    editorParams: {min: 0, step: 0.01}
                },
                canEdit ? {title: "", field: "actions", formatter: deleteButtonFormatter, width: 50, hozAlign: "center", headerSort: false,
                    cellClick: function(e, cell) { deleteSubRow('barge_lines', cell.getRow().getData().id, ldudId); }
                } : null
            ].filter(Boolean)
        });
        if (isDark) document.querySelector(`#barge_lines-table-${ldudId}`).classList.add('tabulator-dark');

        // Vessel Operations table
        const vesselOpsHoldColumns = getHoldDefs(ldudId).map(def => ({
            title: def.hold_name,
            field: def.field,
            width: 120,
            hozAlign: "right",
            editor: canEdit ? "number" : false,
            editorParams: {min: 0, step: 0.01},
            headerTooltip: `Stowage Qty: ${parseFloat(def.stowage_qty || 0).toFixed(2)}${def.cargo_name ? ` | Cargo: ${def.cargo_name}` : ''}`,
            cellEdited: function() { updateHoldSummary(ldudId); }
        }));

        subTables[ldudId].vessel_ops = new Tabulator(`#vessel_ops-table-${ldudId}`, {
            layout: "fitDataFill",
            height: 200,
            ajaxURL: `/api/module/LDUD01/vessel_ops/${ldudId}`,
            ajaxResponse: function(url, params, response) {
                const pivotRows = buildVesselOpsRowsFromApi(ldudId, response);
                setTimeout(() => updateHoldSummary(ldudId), 50);
                return pivotRows;
            },
            columns: [
                {title: "Date", field: "op_date", width: 130, editor: canEdit ? dateEditor : false},
                ...vesselOpsHoldColumns,
                canEdit ? {title: "", field: "actions", formatter: deleteButtonFormatter, width: 50, hozAlign: "center", headerSort: false,
                    cellClick: function(e, cell) { deleteVesselOpsDateRow(ldudId, cell.getRow()); }
                } : null
            ].filter(Boolean)
        });
        if (isDark) document.querySelector(`#vessel_ops-table-${ldudId}`).classList.add('tabulator-dark');

        updateHoldSummary(ldudId);

        // Barge Cleaning Lines table
        const pplOptions = {};
        payloaderList.forEach(p => { pplOptions[p] = p; });

        // Build barge options from current barge lines data (only barges used in this LDUD)
        function getBargeCleaningOptions() {
            const opts = {};
            if (subTables[ldudId] && subTables[ldudId].barge_lines) {
                subTables[ldudId].barge_lines.getRows().forEach(row => {
                    const bn = row.getData().barge_name;
                    if (bn) opts[bn] = bn;
                });
            }
            return opts;
        }

        subTables[ldudId].barge_cleaning = new Tabulator(`#barge_cleaning-table-${ldudId}`, {
            layout: "fitDataFill",
            height: 200,
            ajaxURL: `/api/module/LDUD01/barge_cleaning/${ldudId}`,
            columns: [
                {title: "Barge", field: "barge_name", width: 130, editor: canEdit ? "list" : false,
                    editorParams: function() { return {values: getBargeCleaningOptions(), autocomplete: true, allowEmpty: true}; }},
                {title: "Payloader", field: "payloader_name", width: 130, editor: canEdit ? "list" : false,
                    editorParams: {values: pplOptions, autocomplete: true, allowEmpty: true}},
                {title: "HMR Start", field: "hmr_start", width: 100, editor: canEdit ? "number" : false, hozAlign: "right",
                    editorParams: {min: 0, step: 0.01}},
                {title: "HMR End", field: "hmr_end", width: 100, editor: canEdit ? "number" : false, hozAlign: "right",
                    editorParams: {min: 0, step: 0.01}},
                {title: "Diesel Start", field: "diesel_start", width: 140, editor: canEdit ? datetimeEditor : false,
                    formatter: function(cell) { return cell.getValue() ? cell.getValue().replace('T', ' ') : ''; }},
                {title: "Diesel End", field: "diesel_end", width: 140, editor: canEdit ? datetimeEditor : false,
                    formatter: function(cell) { return cell.getValue() ? cell.getValue().replace('T', ' ') : ''; }},
                {title: "Start Time", field: "start_time", width: 140, editor: canEdit ? datetimeEditor : false,
                    formatter: function(cell) { return cell.getValue() ? cell.getValue().replace('T', ' ') : ''; }},
                {title: "End Time", field: "end_time", width: 140, editor: canEdit ? datetimeEditor : false,
                    formatter: function(cell) { return cell.getValue() ? cell.getValue().replace('T', ' ') : ''; }},
                canEdit ? {title: "", field: "actions", formatter: deleteButtonFormatter, width: 50, hozAlign: "center", headerSort: false,
                    cellClick: function(e, cell) { deleteSubRow('barge_cleaning', cell.getRow().getData().id, ldudId); }
                } : null
            ].filter(Boolean)
        });
        if (isDark) document.querySelector(`#barge_cleaning-table-${ldudId}`).classList.add('tabulator-dark');
    }

    function deleteButtonFormatter(cell) {
        return '<button class="btn-sub-delete">X</button>';
    }

    function updateHoldSummary(ldudId) {
        const summaryEl = document.getElementById(`hold-summary-${ldudId}`);
        if (!summaryEl) return;

        // Calculate stowage quantities per hold
        const stowageByHold = {};
        const holdMeta = stowageHoldMeta[ldudId] || {};
        Object.keys(holdMeta).forEach(hold => {
            stowageByHold[hold] = parseFloat(holdMeta[hold].stowage_qty || 0);
        });

        // Calculate discharged quantities per hold from Vessel Operations grid
        const dischargedByHold = getVesselOpsDischargedByHold(ldudId);

        // Build summary HTML
        const holds = Object.keys(stowageByHold).sort(sortHoldNames);
        if (holds.length === 0) {
            summaryEl.innerHTML = '<span style="color: #718096;">No stowage plan data available for selected VCN</span>';
            return;
        }

        let summaryHTML = '<strong>Holdwise Qty / Balance:</strong> ';
        holds.forEach((hold) => {
            const stowage = stowageByHold[hold] || 0;
            const discharged = dischargedByHold[hold] || 0;
            const remaining = stowage - discharged;
            const percentage = stowage > 0 ? ((discharged / stowage) * 100).toFixed(1) : 0;

            let color = '#38a169'; // green
            if (discharged > stowage) {
                color = '#e53e3e'; // red - over discharged
            } else if (remaining > 0) {
                color = '#d69e2e'; // yellow - incomplete
            }

            summaryHTML += `<span style="margin-right: 20px;">
                <strong>${hold}:</strong>
                <span style="color: ${color};">${discharged.toFixed(2)} / ${stowage.toFixed(2)}</span>
                <span style="color: #1f2937; font-size: 11px;"> (Bal: ${remaining.toFixed(2)})</span>
                <span style="color: #718096; font-size: 11px;">(${percentage}%)</span>
            </span>`;
        });

        summaryEl.innerHTML = summaryHTML;
    }

    async function addSubRow(type, ldudId) {
        if (type === 'vessel_ops') {
            addVesselOpsDateRow(ldudId);
            return;
        }

        const res = await fetch(`/api/module/LDUD01/${type}/save`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ldud_id: ldudId})
        });
        const data = await res.json();
        if (data.id && subTables[ldudId] && subTables[ldudId][type]) {
            const newRow = {id: data.id, ldud_id: ldudId};
            if (type === 'barge_lines' && data.trip_number) {
                newRow.trip_number = data.trip_number;
            }
            subTables[ldudId][type].addRow(newRow, true);
        }
    }

    async function saveSubTable(type, ldudId) {
        if (type === 'vessel_ops') {
            await saveVesselOpsTable(ldudId);
            return;
        }

        if (!subTables[ldudId] || !subTables[ldudId][type]) return;

        const rows = subTables[ldudId][type].getRows();
        let savedCount = 0;

        for (const row of rows) {
            const data = row.getData();
            if (data.id) {
                const res = await fetch(`/api/module/LDUD01/${type}/save`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({...data, ldud_id: ldudId})
                });
                const result = await res.json();
                if (result.success) {
                    savedCount++;
                    // Update calculated fields for delays
                    if (type === 'delays' && result.total_time_mins !== undefined) {
                        row.update({total_time_mins: result.total_time_mins, total_time_hrs: result.total_time_hrs});
                    }
                    // Update trip number for barge lines
                    if (type === 'barge_lines' && result.trip_number !== undefined) {
                        row.update({trip_number: result.trip_number});
                    }
                }
            }
        }

        alert(`Saved ${savedCount} row(s)`);
    }

    async function deleteSubRow(type, id, ldudId) {
        if (!confirm('Delete this row?')) return;
        await fetch(`/api/module/LDUD01/${type}/delete`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({id: id})
        });
        if (subTables[ldudId] && subTables[ldudId][type]) {
            const row = subTables[ldudId][type].getRows().find(r => r.getData().id === id);
            if (row) row.delete();

        }
    }

    function addRow() {
        table.addRow({
            created_by: currentUser,
            created_date: getTodayDate(),
            doc_status: 'Pending'
        }, true);
    }

    function deleteSelected() {
        const selected = table.getSelectedRows();
        if (selected.length === 0) { alert('Select rows to delete'); return; }
        if (!confirm(`Delete ${selected.length} row(s)?`)) return;
        selected.forEach(row => {
            const id = row.getData().id;
            if (id) {
                // Close modal if this LDUD is open
                if (currentLdudId === id) {
                    closeDetailsModal();
                }

                // Clean up sub-tables if they exist
                if (subTables[id]) {
                    Object.values(subTables[id]).forEach(t => {
                        if (t && typeof t.destroy === 'function') {
                            t.destroy();
                        }
                    });
                    delete subTables[id];
                }

                fetch("/api/module/LDUD01/delete", {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({id: id})
                });
            }
            row.delete();
        });
    }

    async function saveAll() {
        showStatus('Saving...', 'saving');
        const rows = table.getRows();
        let savedCount = 0;
        for (const row of rows) {
            const data = row.getData();
            const res = await fetch("/api/module/LDUD01/save", {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(data)
            });
            const result = await res.json();
            if (result.id) {
                row.update({id: result.id, doc_num: result.doc_num, doc_status: result.doc_status});
                savedCount++;
            }
        }
        showStatus(`Saved ${savedCount} row(s)`, 'saved');
        table.setData("/api/module/LDUD01/data");
    }

    document.addEventListener('keydown', function(e) {
        if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); saveAll(); }
    });

    loadMasterData();
