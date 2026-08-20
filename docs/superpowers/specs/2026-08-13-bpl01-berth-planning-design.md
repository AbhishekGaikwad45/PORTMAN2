# BPL01 — Berth Planning Canvas — Design

**Date:** 2026-08-13
**Status:** Built. Amended 2026-08-13 after first user review — see *Amendment 1*.
**Scope:** A new draft-planning module. Berth lanes from PBM01, drag vessels
onto a lane, per-parcel mini-Gantt inside each vessel card. No VCN entry is
created. Nothing outside BPL01 changes behaviour.

## Problem

Planners need to decide **which expected vessel goes to which berth, in what
order, and when** — before any VCN exists. Today there is no surface for this.
The closest thing is the RP01 Berth Plan daily report, which is read-only and
only knows about vessels that already have a VCN + LDUD.

The blocker is that an expected end time cannot currently be computed for a
vessel that has not berthed.

## Reference: how expected end time is calculated today

The chain is EV01 → VCN01 → LDUD01 → LUEU01 → RP01.

| Module | Table | Contributes |
|---|---|---|
| EV01 | `expected_vessels` | `eta`, `ata`, `nor`, requested `berth_name`, comma-joined `cargo_name` / `quantity`. **No time estimate.** Row is deleted on move-to-VCN ([EV01/model.py:418](../../../modules/EV01/model.py#L418)) |
| VCN01 | `vcn_header` + `vcn_consigners` / `vcn_export_cargo_declaration` | per-parcel quantity, terminal, equipment, pipeline. **No time estimate.** |
| LDUD01 | `ldud_parcel_ops` | `expected_start`, `expected_flow_rate`, `start_dt`, `end_dt`, `quantity`. Does **not** write start/end — LUEU01 owns them ([LDUD01/model.py:296](../../../modules/LDUD01/model.py#L296)) |
| LUEU01 | `lueu_parcel_log` | the actual logged qty/hours that produce `avg_rate` |
| RP01 | — | rolls per-parcel ETCs into one vessel ETC |

The formula, in [LUEU01/lueu01.html:133-138](../../../modules/LUEU01/lueu01.html#L133-L138):

```
ETC = start + (target_qty / rate) hours
```

Two flavours, one function:

- **Planned ETC** — `expected_start + target_qty / expected_flow_rate`
  ([lueu01.html:96-100](../../../modules/LUEU01/lueu01.html#L96-L100))
- **Actual ETC** — `start_dt + target_qty / avg_rate`, where
  `avg_rate = logged_qty / Σ(log hours)` ([LUEU01/model.py:146](../../../modules/LUEU01/model.py#L146))

Three properties BPL01 must preserve:

1. It is `full target / rate from start`, **not** `remaining / rate from now`.
2. ETC is **per `parcel_op`**, and parcel ops run in **parallel** (separate
   discharge lines). Vessel ETC = `max(parcel ETCs)`
   ([RP01 Berth_plan/view.py:508-513](../../../modules/RP01/RP01/Berth_plan/view.py#L508-L513)).
3. Short-close quantity counts toward completion but not toward `avg_rate`, and
   once cumulative qty reaches target, later log rows stop adding run hours
   ([LUEU01/model.py:99-116](../../../modules/LUEU01/model.py#L99-L116)).

Properties 1 and 2 apply to BPL01. Property 3 is log-driven and has no planning
equivalent — BPL01 has no logs.

**Consequence:** rate is the missing input. A pre-berth vessel has quantity but
no `ldud_parcel_ops` row and therefore no rate. **Decision: the planner types
the rate, every time.** No historical average, no per-berth rate master, and no
prefill — an EV01 vessel is by definition pre-VCN, so it can never have an
`expected_flow_rate` to inherit. The rate field starts blank and the parcel has
no end time until the planner fills it in.

## Constraints

- **Read-only toward existing data.** BPL01 never writes `expected_vessels`,
  `vcn_header`, `ldud_*` or `lueu_*`. It only reads them.
- No VCN is created. That is the entire premise of the module.
- Migrations via Alembic. Current head is `jnpa53_vcg01_cargo_code`.
- Follow the existing module shape: `modules/<CODE>/{__init__,views,model}.py`
  plus one co-located HTML template, blueprint registered in `app.py`.
- Berths are read live from `port_berth_master` — never hardcoded (matching
  [RP01 Berth_plan/view.py:48-58](../../../modules/RP01/RP01/Berth_plan/view.py#L48-L58)).

## Design

### 1. Data model — Alembic migration `jnpa54_bpl01_berth_plan`

One table.

```sql
CREATE TABLE berth_plan (
  id          SERIAL PRIMARY KEY,
  ev_id       INTEGER UNIQUE REFERENCES expected_vessels(id) ON DELETE CASCADE,
  berth_name  TEXT NOT NULL,
  parcels     JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_by  TEXT,
  updated_at  TIMESTAMP DEFAULT now()
);
```

`parcels` element shape:

```json
{"cargo": "HSD", "qty": 9500, "start": "2026-08-14T22:00", "rate": 480}
```

`qty` and `rate` are numbers or `null`; `start` is a `YYYY-MM-DDTHH:MM` string or
`null` (matching how `ldud_parcel_ops.start_dt` is already stored and parsed
throughout RP01 — see `_fmt_dt`).

Three deliberate choices:

- **`ON DELETE CASCADE` is the whole cleanup story.** EV01 deletes the
  `expected_vessels` row the moment a vessel moves to a VCN. The plan row goes
  with it. No sweeper job, no orphan check, no application code.
- **`UNIQUE ev_id`** — a vessel is planned at exactly one berth. Dragging to
  another lane is an `UPDATE berth_name`, not an insert + delete.
- **Parcels as JSONB, not a child table.** The plan is always read and written
  as a whole vessel; nothing queries across parcels. PBM01 already stores
  `image_position` as JSONB, so this is an established pattern here.

`berth_name` is `TEXT` with no FK, matching how `vcn_header.berth_name` and the
RP01 queries already join on the berth name string.

Down-migration drops the table.

### 2. Backend — `modules/BPL01/`

Standard blueprint, mirroring `modules/LUEU01/views.py`: `login_required`
decorator, `get_perms()` reading `get_user_permissions(user_id, 'BPL01')` with
admin bypass, `MODULE_INFO = {'code': 'BPL01', 'name': 'Berth Planning'}`,
registered in `app.py` alongside the other modules.

**Routes**

| Route | Method | Permission | Returns |
|---|---|---|---|
| `/module/BPL01/` | GET | `can_read` | the page |
| `/api/module/BPL01/data` | GET | `can_read` | `{berths, occupied, plans, expected}` |
| `/api/module/BPL01/plan` | POST | `can_add` or `can_edit` | upsert one plan row |
| `/api/module/BPL01/plan/delete` | POST | `can_delete` | remove a plan row |

**`model.get_canvas()`** assembles the four pieces:

- `berths` — `SELECT berth_name FROM port_berth_master ORDER BY berth_name`
- `occupied` — reuse `get_berthed_vessels(window_start, window_end, berths)`
  from `modules.RP01.RP01.Berth_plan.view`, called with `window_end = now` and
  `window_start = now - 24h`. Only `window_end` matters here: `window_start`
  bounds RP01's "last 24 hrs" figure, which BPL01 does not display. This gives
  real vessels with their real `expected_completion` computed by the existing
  math. It issues several queries per vessel, which is acceptable for a
  handful of berths; carry a `ponytail:` comment naming that ceiling and the
  upgrade path (fold into one query if berth count grows). Reusing it is the
  point — the alternative is a second source of truth for ETC.
- `plans` — `SELECT * FROM berth_plan`, joined to `expected_vessels` for vessel
  name / VIA / LOA / draft / ETA.
- `expected` — `expected_vessels` rows with no `berth_plan` row yet, excluding
  `doc_status = 'Closed - Other Terminal'` (the same exclusion EV01's own grid
  applies, `_MOVED` in [EV01/model.py:293](../../../modules/EV01/model.py#L293)).

**`model.save_plan(ev_id, berth_name, parcels, username)`** — one
`INSERT ... ON CONFLICT (ev_id) DO UPDATE`. Validates that `berth_name` exists
in `port_berth_master` and that `parcels` is a list of objects with the four
expected keys, rejecting anything else with a 400. This is a trust boundary
(JSONB written straight from a browser payload), so the shape check is not
optional.

**`model.delete_plan(ev_id)`** — `DELETE FROM berth_plan WHERE ev_id=%s`.

### 3. Frontend — `modules/BPL01/bpl01.html`

Two columns.

**Left: expected vessels.** One card per unplanned `expected_vessels` row —
vessel name, total quantity, ETA. `draggable="true"`.

**Right: berth lanes.** One card per berth from `port_berth_master`, always
expanded, stacked down the page. Each lane is a `drop` target and contains its
queue in this order:

1. **Occupied vessels** (from `occupied`) first — they are physically at the
   berth. Read-only, showing their real ETC.
2. **Planned vessels** after, ordered by earliest parcel `start` (nulls last,
   then `ev_id`). Editable: per parcel a row with cargo, qty, a start datetime
   input, a rate input, and a bar.

Each lane draws one shared time axis spanning `[now, latest end in this lane]`,
so bar positions are comparable within a lane and "what to do ahead of that
vessel" is readable at a glance.

Drag and drop uses native HTML5 `draggable` / `dragover` / `drop`. No library.
On drop, the client builds one parcel per `cargo_name`/`quantity` pair split out
of the EV01 row — the same pairing [`cargo_quotas`](../../../modules/EV01/model.py#L382)
already performs — with `start` defaulting to the vessel's ETA and `rate` blank.
It then POSTs to `/api/module/BPL01/plan`. Editing any field re-POSTs the whole
row.

**Planning math lives in `model.py`, not the page.** `parcel_end`,
`vessel_start`, `vessel_end` and `annotate_lane` are pure functions the API
calls before serialising, so pytest can reach them and there is one source of
truth:

```
parcel_end  = start + (qty / rate) hours   # None unless rate > 0 and start set
vessel_end  = max(parcel_end)              # None if no parcel has both
```

The page re-implements `parcelEnd` only to size the bars it draws; the server's
value is what gets displayed. Edits follow the LUEU01 shape already in use —
`onchange` → POST → refetch → re-render — so the round trip keeps the two in
step without any client-side state to drift.

A parcel with no rate yet renders as a zero-width marker at its start, not as an
error. A vessel with no rated parcel contributes no end time to its lane.

**Conflict flag.** Within a lane, a planned vessel whose earliest parcel start
falls before the end of whatever precedes it (an occupied vessel's ETC, or an
earlier planned vessel's `vesselEnd`) gets a red outline and a tooltip naming
the conflicting vessel. This is the actual product of the module — a plan you
can see is impossible.

**Permissions.** `can_add`/`can_edit` gates dragging and the inputs;
`can_delete` gates removing a planned vessel from a lane. Without them the page
is read-only, matching how every other module behaves.

### 4. Testing

`tests/test_bpl01.py`, following the existing test style:

1. **Duration math** — `start + qty/rate` for a single parcel; `max()` across
   parallel parcels; `null` end when rate is missing or zero.
2. **Conflict detection** — a planned start before the preceding vessel's end
   flags; one after it does not; a boundary-equal start does not flag.
3. **Cascade** — deleting an `expected_vessels` row removes its `berth_plan`
   row. This is the one behaviour that is pure schema, and the one most likely
   to be broken by a future migration.
4. **Payload validation** — `save_plan` rejects a non-list `parcels`, an unknown
   `berth_name`, and an element missing required keys.

## Amendment 1 — VCN vessels, hours, and delay lines (2026-08-13)

After seeing the first build, the user asked for three changes. Sections above
describe the original design; where they conflict, this section wins.

**1. VCN vessels are planned too.** `berth_plan` gains
`vcn_id INTEGER UNIQUE REFERENCES vcn_header(id) ON DELETE CASCADE`, and a
CHECK constraint `berth_plan_one_source` enforces that exactly one of
`ev_id` / `vcn_id` is set — a plan row is one vessel, never two or none. Both
sources cascade, so the cleanup story is unchanged.

The API identifies a plan by `(source, source_id)` with `source` in
`SOURCES = {'EV': 'ev_id', 'VCN': 'vcn_id'}`. That dict is the whitelist that
makes the column name safe to interpolate into the `ON CONFLICT` target.

The drag panel lists EV01 expected vessels plus VCNs with no LDUD
`alongside_datetime` — the same "not berthed yet" test RP01 applies. A
**show berthed** checkbox (`?show_all=1`) reveals the rest, for re-planning a
vessel already at a berth. VCN quantity is summed from the parcel tables
(`vcn_consigners` ∪ `vcn_export_cargo_declaration`); `vcn_header` has no
quantity column.

**2. Parcels are scheduled in hours, not a flow rate.** The planner states how
long a parcel takes; a rate is then redundant. `qty` remains as a reference
field, editable or blank.

**3. Delay line items, per parcel.** Each parcel carries
`delays: [{name, hours}]`, `name` drawn from `port_delay_types` — the same
master LUEU01's Delay column reads. Per-parcel rather than per-vessel, matching
LUEU01 where `delay_name` sits on the log row, so one discharge line can be
held up while another keeps running.

The parcel shape becomes:

```json
{"cargo": "HSD", "qty": 9600, "start": "2026-08-15T18:00", "hours": 20,
 "delays": [{"name": "Rain", "hours": 2}]}
```

and the math becomes:

```
parcel_end = start + hours + Σ(delay hours)
vessel_end = max(parcel_end)          # unchanged: parcels run in parallel
```

Delay alone is not a schedule: a parcel with delay lines but no working hours
has no end. Delay lines named but not yet costed contribute nothing.

**Parcels are now fully editable** — add, edit and remove parcels and delay
lines on the page. Seeding on drop still happens, as a starting point rather
than a fixed list: EV01 vessels seed from their comma-joined cargo/quantity
text, VCNs from their actual declared parcels. Hours always seed blank.

Migration `jnpa55_bpl01_vcn_and_hours` converts existing draft rows
(`hours = qty / rate`) rather than wiping them, and is reversible. Revision IDs
must stay ≤ 32 characters — `alembic_version.version_num` is `varchar(32)`.

## Out of scope

Deliberately excluded, with the trigger for adding each:

- **LOA / draft vs berth capacity validation** — add when a planner actually
  drops a vessel that does not physically fit. `port_berth_master` has no length
  or depth column today, so this needs a master change first.
- **Auto-promote a plan into a VCN** — add if planners start double-entering.
  The plan is a draft by design.
- **Historical or per-berth default rates** — explicitly rejected; the planner
  types the rate.
- **Jetty image view** — `port_berth_master.image_position` and
  `static/img/jjltpljetty.png` already exist and are currently consumed only by
  PBM01. A spatial view can be added later as an alternate rendering of the same
  `/api/module/BPL01/data` payload, with no change to the planning model.
- **Multi-day / date-range navigation** — the canvas shows from now forward.
- **Plan versioning or audit history** — `updated_at` and `created_by` only.
