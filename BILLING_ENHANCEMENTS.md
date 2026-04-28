# Billing Module Enhancement Implementation Plan

## Features to Implement:

### 1. Service Type Dropdown in EU Lines ✅ (API Ready)
- Added API: `/api/module/FIN01/service-types`
- Returns all active service types from FSTM01
- Each EU line will have a dropdown to select/change service type

### 2. Automatic Rate from Customer Agreements ✅ (API Ready)
- Added API: `/api/module/FIN01/agreement-rate/<customer_id>/<service_type_id>`
- Fetches rate from FCAM01 based on:
  - Customer ID
  - Service Type ID
  - Active, Approved agreement
  - Valid date range (valid_from <= today <= valid_to)
- Rate auto-populates when customer + service type combination is selected

### 3. Already Billed EU Lines Marking
- EU lines with `is_billed = 1` should:
  - Show checkbox as checked and disabled
  - Show a "Already Billed" badge
  - Disable rate input field
  - Include in display but not in new bill generation

### 4. MBC EU Lines Display
- Issue: MBC EU lines not showing
- Check: populate_mock_data.py creates EU lines for both VCN and MBC
- Verify: EU lines API correctly handles source_type='MBC'

### 5. View Bill Detail Page
- Add route: `/module/FIN01/bill/<int:bill_id>`
- Show:
  - Bill header information
  - All bill lines with service details
  - Totals breakdown
  - Status and approval info
- Add "View" button in bills listing page

## Implementation Steps:

### Step 1: Update generate_bill.html JavaScript
```javascript
let serviceTypes = [];

// Load service types on page load
async function loadServiceTypes() {
    const res = await fetch('/api/module/FIN01/service-types');
    const data = await res.json();
    serviceTypes = data.data || [];
}

// Call on page load
document.addEventListener('DOMContentLoaded', loadServiceTypes);

// Modified renderEULines to include service type dropdown
function renderEULines(lines) {
    // ...
    // For each line, add:
    // - Service type dropdown
    // - Auto-fetch rate on service type change
    // - Mark already billed lines
}

// Fetch rate when customer and service type are selected
async function fetchRate(customerId, serviceTypeId, rateInput) {
    const res = await fetch(`/api/module/FIN01/agreement-rate/${customerId}/${serviceTypeId}`);
    const result = await res.json();
    if (result.success) {
        rateInput.value = result.data.rate.toFixed(2);
        calculateTotals();
    } else {
        rateInput.value = '0.00';
        alert('No agreement found for this customer-service combination');
    }
}
```

### Step 2: Add View Bill Page
- Create `bill_view.html` template
- Add route in `views.py`
- Add "View" button in bills listing

### Step 3: Fix MBC EU Lines
- Verify populate_mock_data.py creates MBC EU lines
- Check API endpoint handles MBC correctly

## Files to Modify:

1. ✅ `modules/FIN01/views.py` - Added service types and agreement rate APIs
2. ⏳ `modules/FIN01/generate_bill.html` - Update JavaScript
3. ⏳ `modules/FIN01/bills.html` - Add View button
4. ⏳ `modules/FIN01/bill_view.html` - Create new template
5. ⏳ `modules/FIN01/views.py` - Add view bill route
