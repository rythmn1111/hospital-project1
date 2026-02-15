# HospitalOS — System Architecture & Data Relations

## Overview

HospitalOS is a kiosk-based hospital management system. A single Raspberry Pi (7" touchscreen + PN532 NFC reader) runs both the Next.js frontend and a Python NFC server. Every patient carries an NFC card with a unique ID. Tap the card at any section → system identifies the patient and shows the relevant context.

For the first demo: **one device, all sections accessible, full flow demonstrated.**

---

## Hardware & Services

| Component | Runs On | Port | Purpose |
|-----------|---------|------|---------|
| Next.js App | Raspberry Pi | `3000` | UI — all sections |
| Python NFC Server | Raspberry Pi | `5532` (fixed) | Read/write NFC cards via PN532 |
| Supabase | Cloud | — | Shared database |
| WhatsApp Server | VPS | — | Notifications (separate) |

### Python NFC Server API (port 5532)

The Python server is a simple HTTP/REST server. Next.js calls it when a card tap is needed.

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `POST /read` | POST | Wait for card tap, return card data (NFC ID) |
| `POST /write` | POST | Write an ID to a blank/new card |
| `POST /format` | POST | Wipe a card clean before writing |
| `GET /status` | GET | Check if NFC reader is connected |

**Flow:**
1. Next.js calls `POST http://localhost:5532/read`
2. Python waits for card tap (with timeout)
3. Card is tapped → Python reads the stored ID
4. Returns `{ nfc_id: "ABC123" }` or `{ nfc_id: null }` (blank card)
5. Next.js uses the `nfc_id` to look up or register the patient

---

## NFC Card

- Each card stores a single string: the **NFC ID**
- The NFC ID is a unique identifier (e.g., UUID or short alphanumeric)
- NFC ID maps to `patients.nfc_card_id` in Supabase
- Cards can be blank (new) or have an existing ID
- No encryption for now — plain text ID

---

## Registration Flow (Patients Section)

```
Staff clicks "Tap Card to Register"
        │
        ▼
Next.js calls Python → POST /read
        │
        ▼
Patient taps NFC card
        │
        ▼
Python returns { nfc_id }
        │
        ├── nfc_id exists in DB ──► Patient found → Show patient info
        │                           "This card is already registered"
        │
        ├── nfc_id NOT in DB ──► Card has an ID but no patient record
        │                        → Format card, write new ID, show registration form
        │
        └── nfc_id is null ──► Blank card
                              → Generate new ID
                              → Call POST /write { nfc_id: newId }
                              → Show registration form
                              → On form submit: save patient with nfc_card_id = newId
```

---

## Station Flows (What Happens on Card Tap)

### 1. Patients (Registration Desk)
**Tap card →**
- Existing patient: Show patient info, edit option
- New/blank card: Register new patient (name, age, gender, phone, blood group, ABHA, address)

### 2. Clinic (OPD / Doctor's Station)
**Tap card →**
- Show patient name & basic info at top
- Show **medical history** (past consultations with dates)
- Show **pending test results** (ordered but not yet done, or completed results)
- Doctor can:
  - **Add new consultation** (symptoms, diagnosis, notes)
  - **Order tests** (select from test types, gets created as a pending test order)
  - **Write prescription** (medicine name, dosage, duration, instructions)
- All linked to current consultation

### 3. Testing Labs
**Tap card →**
- Show patient name
- Show **pending test orders** (ordered by doctor, not yet done)
- Lab tech can:
  - **Mark sample collected** (timestamp)
  - **Post results** (text field for now, per test)
  - **Mark test as completed**
- Once completed, result is visible to doctor at Clinic station

### 4. Pharmacy
**Tap card →**
- Show patient name
- Show **pending prescriptions** (written by doctor, not yet dispensed)
- Pharmacist can:
  - **Mark as dispensed** (timestamp, partial/full)
  - See prescription details (medicine, dosage, quantity)
- Dispensed prescriptions marked so they don't show again

### 5. Hospital (Inpatient)
**Tap card →**
- Show patient name & current admission status
- If not admitted: option to **admit** (department, doctor, bed, diagnosis)
- If admitted: option to **discharge** (summary, notes)
- Show **admission history**

---

## Data Model & Relations

```
patients
  │
  ├──< consultations (one patient → many consultations)
  │       │
  │       ├──< test_orders (one consultation → many test orders)
  │       │       │
  │       │       └── test_results (one test order → one result)
  │       │
  │       └──< prescriptions (one consultation → many prescriptions)
  │
  └──< admissions (one patient → many admissions)
```

### patients
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | Auto-generated |
| nfc_card_id | TEXT UNIQUE | The NFC card's stored ID |
| name | TEXT NOT NULL | |
| age | INTEGER | |
| gender | TEXT | Male / Female / Other |
| phone | TEXT | |
| address | TEXT | |
| blood_group | TEXT | |
| abha_number | TEXT | |
| registered_at | TIMESTAMPTZ | Default now() |

### consultations
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| patient_id | UUID FK → patients | |
| doctor_id | UUID FK → staff | The doctor who saw the patient |
| symptoms | TEXT | What patient reported |
| diagnosis | TEXT | Doctor's diagnosis |
| notes | TEXT | Additional notes |
| consulted_at | TIMESTAMPTZ | Default now() |

### test_orders
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| consultation_id | UUID FK → consultations | Which consultation ordered this |
| patient_id | UUID FK → patients | Denormalized for easy lookup at lab |
| test_name | TEXT | e.g., "CBC", "Blood Sugar", "X-Ray" |
| status | TEXT | `ordered` → `sample_collected` → `completed` |
| ordered_at | TIMESTAMPTZ | Default now() |
| sample_collected_at | TIMESTAMPTZ | Null until collected |
| completed_at | TIMESTAMPTZ | Null until results posted |

### test_results
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| test_order_id | UUID FK → test_orders | One-to-one |
| result_text | TEXT | Plain text result (for now) |
| posted_by | UUID FK → staff | Lab tech who posted |
| posted_at | TIMESTAMPTZ | Default now() |

### prescriptions
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| consultation_id | UUID FK → consultations | |
| patient_id | UUID FK → patients | Denormalized for pharmacy lookup |
| medicine_name | TEXT | |
| dosage | TEXT | e.g., "500mg" |
| frequency | TEXT | e.g., "Twice daily" |
| duration | TEXT | e.g., "7 days" |
| instructions | TEXT | e.g., "After meals" |
| status | TEXT | `prescribed` → `dispensed` |
| prescribed_at | TIMESTAMPTZ | Default now() |
| dispensed_at | TIMESTAMPTZ | Null until dispensed |

### admissions (already exists)
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| patient_id | UUID FK → patients | |
| department | TEXT | |
| doctor | TEXT | |
| bed_number | TEXT | |
| diagnosis | TEXT | |
| admitted_at | TIMESTAMPTZ | |
| discharged_at | TIMESTAMPTZ | Null if still admitted |
| discharge_summary | TEXT | |
| status | TEXT | `admitted` / `discharged` |

### staff (already exists)
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| name | TEXT | |
| qualification | TEXT | |
| birthdate | DATE | |
| is_doctor | BOOLEAN | |
| phone | TEXT | |
| username | TEXT UNIQUE | |
| password | TEXT | |
| abha_number | TEXT | |

### sections, section_fields, staff_section_access (already exist)
Used for access control — which staff sees which sections.

---

## Cross-Station Data Flow

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  REGISTRATION│     │   CLINIC    │     │  TESTING LAB│     │  PHARMACY   │
│             │     │             │     │             │     │             │
│ Register    │────►│ View patient│     │             │     │             │
│ patient     │     │ history     │     │             │     │             │
│ (NFC card)  │     │             │     │             │     │             │
│             │     │ Add consult │──┬──►│ See ordered │     │             │
│             │     │ Order tests │  │  │ tests       │     │             │
│             │     │ Prescribe   │──┼──┼─────────────┼────►│ See pending │
│             │     │             │  │  │ Collect     │     │ Rx          │
│             │     │             │  │  │ sample      │     │             │
│             │     │ See test    │◄─┼──│ Post results│     │ Dispense    │
│             │     │ results     │  │  │             │     │ medicine    │
│             │     │             │  │  │             │     │             │
└─────────────┘     └─────────────┘  │  └─────────────┘     └─────────────┘
                                     │
                                     │  ┌─────────────┐
                                     └─►│  HOSPITAL   │
                                        │ (Inpatient) │
                                        │             │
                                        │ Admit       │
                                        │ Discharge   │
                                        └─────────────┘
```

### Typical Patient Journey

1. **Registration** → Tap blank card → Card gets ID → Patient registered
2. **Clinic** → Tap card → Doctor sees history → Adds consultation → Orders CBC test → Prescribes paracetamol
3. **Testing Lab** → Tap card → Lab tech sees "CBC — ordered" → Marks sample collected → Later posts result "Hb: 12.5 g/dL"
4. **Clinic (follow-up)** → Tap card → Doctor sees CBC result → Updates diagnosis
5. **Pharmacy** → Tap card → Pharmacist sees "Paracetamol 500mg, twice daily, 7 days" → Marks dispensed
6. **Hospital** → If serious, tap card → Admit to ward → Later discharge with summary

---

## Demo Device Setup

Single Raspberry Pi runs everything:
- Next.js on `:3000`
- Python NFC server on `:5532`
- All sections accessible (admin login sees everything)
- Staff login shows only assigned sections
- Demo flow: walk through full patient journey on one device

---

## What Already Exists vs What Needs Building

### Already Built ✓
- Dashboard with section cards + access control
- Admin login (WhatsApp) + Staff login (Supabase credentials)
- Staff section (CRUD + section/field access management)
- Patients section (register, view, edit, delete — Supabase)
- Hospital section (patient list from Supabase, admissions in-memory)
- Items Editor section (categories + items CRUD — medicines, lab tests, procedures, supplies)
- Supabase tables: staff, sections, section_fields, staff_section_access, patients, item_categories, items

### Needs Building
- [ ] `nfc_card_id` column on patients table
- [ ] Python NFC server (read/write/format/status endpoints on port 5532)
- [ ] NFC tap integration in Patients section (registration flow)
- [ ] NFC tap integration in all other sections
- [ ] `consultations` table + Clinic section UI
- [ ] `test_orders` + `test_results` tables + Testing Labs section UI
- [ ] `prescriptions` table + Pharmacy section UI
- [ ] `admissions` table in Supabase (replace in-memory) + update Hospital section
- [ ] Cross-station data visibility (doctor sees lab results, pharmacy sees prescriptions)
- [ ] 7" screen responsive optimizations (touch-friendly, large tap targets)
