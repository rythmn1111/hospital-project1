# HospitalOS — Database Schema

> Supabase (PostgreSQL) · All IDs are UUIDs with `gen_random_uuid()` default

---

## Entity Relationship Diagram

```
┌──────────┐       ┌──────────────┐       ┌─────────────┐
│ patients │──1:N──│ admissions   │       │ staff       │
│          │──1:N──│ consultations│──N:1──│             │
│          │──1:N──│ test_orders  │       └──────┬──────┘
│          │──1:N──│ prescriptions│              │1:N
└──────────┘       └──────┬───────┘       ┌──────┴──────────────┐
                          │               │ staff_section_access │
              consultations│1:N           └──────┬──────────────┘
                   ┌──────┴───────┐              │N:1
                   │ test_orders  │──1:N──┐ ┌────┴─────┐
                   │ prescriptions│       │ │ sections │──1:N──┐
                   └──────────────┘       │ └──────────┘       │
                                   ┌──────┴───────┐    ┌───────┴────────┐
                                   │ test_results │    │ section_fields │
                                   └──────────────┘    └────────────────┘

┌─────────────────┐       ┌───────┐
│ item_categories │──1:N──│ items │
└─────────────────┘       └───────┘
```

---

## Tables

### 1. `patients`

Core patient registry. Linked via NFC card for kiosk identification.

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | uuid | NO | `gen_random_uuid()` | PK |
| `nfc_card_id` | text | YES | | Unique NFC card identifier |
| `name` | text | NO | | |
| `age` | int4 | YES | | |
| `gender` | text | YES | | `Male` / `Female` / `Other` |
| `phone` | text | YES | | |
| `address` | text | YES | | |
| `blood_group` | text | YES | | `A+`, `A-`, `B+`, `B-`, `AB+`, `AB-`, `O+`, `O-` |
| `abha_number` | text | YES | | 14-digit ABHA ID |
| `registered_at` | timestamptz | NO | `now()` | |

**Indexes:** unique on `nfc_card_id` (where not null)

---

### 2. `staff`

Doctors, nurses, and other hospital personnel.

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | uuid | NO | `gen_random_uuid()` | PK |
| `name` | text | NO | | |
| `username` | text | YES | | For staff login |
| `password` | text | YES | | Plain text (kiosk-only, no internet exposure) |
| `qualification` | text | YES | | |
| `birthdate` | date | YES | | |
| `is_doctor` | bool | NO | `false` | Determines doctor-specific features |
| `phone` | text | YES | | |
| `abha_number` | text | YES | | |
| `created_at` | timestamptz | NO | `now()` | |

---

### 3. `admissions`

Inpatient admission and discharge records.

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | uuid | NO | `gen_random_uuid()` | PK |
| `patient_id` | uuid | NO | | FK → `patients.id` |
| `department` | text | YES | | e.g. General, ICU, Pediatrics |
| `doctor` | text | YES | | Doctor name (free text) |
| `bed_number` | text | YES | | |
| `diagnosis` | text | YES | | |
| `status` | text | NO | `'admitted'` | `admitted` / `discharged` |
| `admitted_at` | timestamptz | NO | `now()` | |
| `discharged_at` | timestamptz | YES | | Set on discharge |
| `discharge_summary` | text | YES | | |

**FK:** `patient_id` → `patients(id)` ON DELETE CASCADE

---

### 4. `consultations`

OPD / clinic consultation records.

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | uuid | NO | `gen_random_uuid()` | PK |
| `patient_id` | uuid | NO | | FK → `patients.id` |
| `doctor_id` | uuid | YES | | FK → `staff.id` |
| `symptoms` | text | YES | | |
| `diagnosis` | text | YES | | |
| `notes` | text | YES | | |
| `consulted_at` | timestamptz | NO | `now()` | |

**FK:** `patient_id` → `patients(id)` ON DELETE CASCADE
**FK:** `doctor_id` → `staff(id)` ON DELETE SET NULL

---

### 5. `test_orders`

Lab test orders created from consultations.

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | uuid | NO | `gen_random_uuid()` | PK |
| `consultation_id` | uuid | NO | | FK → `consultations.id` |
| `patient_id` | uuid | NO | | FK → `patients.id` |
| `test_name` | text | NO | | Name of the lab test |
| `status` | text | NO | `'ordered'` | `ordered` / `sample_collected` / `completed` |
| `ordered_at` | timestamptz | NO | `now()` | |
| `sample_collected_at` | timestamptz | YES | | Set by lab technician |
| `completed_at` | timestamptz | YES | | Set when result posted |

**FK:** `consultation_id` → `consultations(id)` ON DELETE CASCADE
**FK:** `patient_id` → `patients(id)` ON DELETE CASCADE

---

### 6. `test_results`

Results posted for completed lab tests.

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | uuid | NO | `gen_random_uuid()` | PK |
| `test_order_id` | uuid | NO | | FK → `test_orders.id` |
| `result_text` | text | NO | | Free-text result |
| `posted_by` | text | YES | | Name of technician |
| `posted_at` | timestamptz | NO | `now()` | |

**FK:** `test_order_id` → `test_orders(id)` ON DELETE CASCADE

---

### 7. `prescriptions`

Medicines prescribed during consultations, dispensed by pharmacy.

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | uuid | NO | `gen_random_uuid()` | PK |
| `consultation_id` | uuid | NO | | FK → `consultations.id` |
| `patient_id` | uuid | NO | | FK → `patients.id` |
| `medicine_name` | text | NO | | |
| `dosage` | text | YES | | e.g. "500mg" |
| `frequency` | text | YES | | e.g. "3 times a day" |
| `duration` | text | YES | | e.g. "5 days" |
| `instructions` | text | YES | | e.g. "After meals" |
| `status` | text | NO | `'prescribed'` | `prescribed` / `dispensed` |
| `prescribed_at` | timestamptz | NO | `now()` | |
| `dispensed_at` | timestamptz | YES | | Set by pharmacy |

**FK:** `consultation_id` → `consultations(id)` ON DELETE CASCADE
**FK:** `patient_id` → `patients(id)` ON DELETE CASCADE

---

### 8. `item_categories`

Categories for hospital items (medicines, lab tests, procedures, supplies).

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | uuid | NO | `gen_random_uuid()` | PK |
| `name` | text | NO | | Display name |
| `slug` | text | NO | | Unique key, e.g. `lab-test`, `medicine` |
| `description` | text | YES | | |
| `created_at` | timestamptz | NO | `now()` | |

**Indexes:** unique on `slug`

---

### 9. `items`

Individual items within categories.

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | uuid | NO | `gen_random_uuid()` | PK |
| `category_id` | uuid | NO | | FK → `item_categories.id` |
| `name` | text | NO | | |
| `description` | text | YES | | |
| `unit` | text | YES | | e.g. "tablet", "ml", "test" |
| `price` | numeric | YES | | |
| `is_active` | bool | NO | `true` | Soft delete / toggle |
| `created_at` | timestamptz | NO | `now()` | |

**FK:** `category_id` → `item_categories(id)` ON DELETE CASCADE

---

### 10. `sections`

Application sections for role-based access control.

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | uuid | NO | `gen_random_uuid()` | PK |
| `name` | text | NO | | Display name |
| `slug` | text | NO | | Matches app route, e.g. `hospital`, `clinic`, `pharmacy` |

**Known slugs:** `hospital`, `clinic`, `pharmacy`, `testing-labs`, `patients`, `items-editor`, `staff`

---

### 11. `section_fields`

Granular field-level access within sections.

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | uuid | NO | `gen_random_uuid()` | PK |
| `section_id` | uuid | NO | | FK → `sections.id` |
| `name` | text | NO | | Display name |
| `slug` | text | NO | | Field identifier |

**FK:** `section_id` → `sections(id)` ON DELETE CASCADE

---

### 12. `staff_section_access`

Maps staff members to sections they can access, with optional field-level granularity.

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | uuid | NO | `gen_random_uuid()` | PK |
| `staff_id` | uuid | NO | | FK → `staff.id` |
| `section_id` | uuid | NO | | FK → `sections.id` |
| `field_slugs` | text[] | YES | | Array of allowed field slugs |

**FK:** `staff_id` → `staff(id)` ON DELETE CASCADE
**FK:** `section_id` → `sections(id)` ON DELETE CASCADE
**Unique:** `(staff_id, section_id)`

---

## Data Flow by Section

### Clinic (OPD)
```
NFC tap → patients → consultations → test_orders → (lab processes)
                                   → prescriptions → (pharmacy dispenses)
```

### Hospital (Inpatient)
```
NFC tap → patients → admissions (admit / discharge)
```

### Testing Labs
```
NFC tap → patients → test_orders (collect sample / post result) → test_results
```

### Pharmacy
```
NFC tap → patients → prescriptions (dispense)
```

### Items Editor
```
item_categories → items (CRUD)
```

### Staff Management
```
staff → staff_section_access ← sections ← section_fields
```
