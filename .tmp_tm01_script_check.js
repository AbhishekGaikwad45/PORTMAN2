addToRecent('TM01', 'Tide Master');

    const permissions = {
        can_edit: 0,
        can_add: 0,
        can_delete: 0
    };

    const canEdit = permissions.can_edit || permissions.can_add;

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

    const table = new Tabulator("#table", {
        height: "calc(100vh - 160px)",
        layout: "fitColumns",
        pagination: true,
        paginationMode: "remote",
        paginationSize: 20,
        ajaxURL: "/api/module/TM01/data",
        ajaxResponse: function(url, params, response) {
            document.getElementById('rowCount').textContent = response.data.length;
            document.getElementById('totalCount').textContent = response.total;
            return response;
        },
        columns: [
            {formatter: "rowSelection", titleFormatter: "rowSelection", hozAlign: "center", headerSort: false, width: 40},
            {title: "ID", field: "id", width: 60},
            {title: "Tide Date Time", field: "tide_datetime", editor: canEdit ? datetimeEditor : false, width: 220,
                formatter: function(cell) { return cell.getValue() ? cell.getValue().replace('T', ' ') : ''; }},
            {title: "Tide (Meters)", field: "tide_meters", editor: canEdit ? "number" : false, width: 150, hozAlign: "right",
                editorParams: {step: 0.01}}
        ],
        selectable: true
    });

    if (localStorage.getItem('theme') === 'dark') {
        document.getElementById('table').classList.add('tabulator-dark');
    }

    function addRow() {
        table.addRow({}, false);
    }

    function deleteSelected() {
        const selected = table.getSelectedRows();
        if (!selected.length) {
            alert('Select rows to delete');
            return;
        }
        if (!confirm(`Delete ${selected.length} row(s)?`)) return;

        selected.forEach(row => {
            const id = row.getData().id;
            if (id) {
                fetch('/api/module/TM01/delete', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({id})
                });
            }
            row.delete();
        });
    }

    function hasValue(v) {
        return v !== null && v !== undefined && String(v).trim() !== '';
    }

    async function saveAll() {
        for (const row of table.getRows()) {
            const data = row.getData();
            if (hasValue(data.tide_datetime) || hasValue(data.tide_meters)) {
                const res = await fetch('/api/module/TM01/save', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(data)
                });
                const result = await res.json();
                if (result.id) row.update({id: result.id});
            }
        }
        table.setData('/api/module/TM01/data');
        alert('Saved');
    }

    document.addEventListener('keydown', function(e) {
        if ((e.ctrlKey || e.metaKey) && e.key === 's') {
            e.preventDefault();
            saveAll();
        }
    });
