# Database schema

PostgreSQL 18, SQLAlchemy 2.0 models in `registrar/models/`. 53 tables. Enums are VARCHAR with CHECK constraints
(see `registrar/models/enums.py`). Every write through the application layer should also land in `audit_log`.

## People and identity (`people.py`)
| Table | Purpose |
|---|---|
| `person` | One row per human: legal and preferred names, DOB, demographics, `ssn_hash` (never raw SSN), email. Students, faculty, staff all share it. |
| `person_name_history` | Prior names and why they changed. |
| `address`, `emergency_contact` | Permanent/mailing/local addresses with effective dates; contacts. |
| `student` | Student profile: level, status (active, leave, withdrawn, suspended, dismissed, graduated), entry type, residency, admit and catalog terms, flags (veteran, athlete, honors), SEVIS id. |
| `student_program` | Declared majors/minors/certificates with catalog term, declared/ended terms; supports double majors and changes. |
| `instructor`, `staff` | Role profiles: department and rank; office and title. |
| `advisor_assignment` | Which advisor is responsible for a student, over time. |

## Academic structure (`academic.py`)
| Table | Purpose |
|---|---|
| `college`, `department` | NMSU's six colleges; departments with chairs. |
| `program` | Majors, minors, certificates with degree type, credit totals, min GPA, CIP code. |
| `program_requirement` | Degree-plan blocks per program per catalog term (gen-ed areas, core, supporting, electives, free electives, residency). |
| `program_requirement_course` | Courses that satisfy a block; `is_required` distinguishes "all of" from "choose from". |
| `academic_term` | Terms with all registrar deadlines: registration opens, add, drop, census, withdraw, grades due. `sequence` orders terms. Fall 2026 is `is_current`. |
| `academic_calendar_event` | Holidays, finals, commencement, deadlines per term. |

## Catalog and schedule (`courses.py`)
| Table | Purpose |
|---|---|
| `subject`, `course` | Catalog: subject code + number, credits, level, gen-ed area, effective/retired terms. |
| `course_prerequisite` | Prereq/coreq rules; rows sharing `group_number` are OR alternatives, groups are AND. |
| `building`, `room` | Rooms with capacity and type. |
| `section` | A course offered in a term: CRN, section number, capacity, waitlist capacity, modality, status (open/closed/cancelled). |
| `section_meeting` | Days, times, room, lecture vs lab. |
| `section_instructor` | Primary instructor, secondary, TA. |

## Registration (`enrollment.py`)
| Table | Purpose |
|---|---|
| `hold` | Holds with placing office, what they block (registration, transcript, graduation), release info. |
| `registration_appointment` | Time tickets per student per term. |
| `enrollment` | Student x section: status (registered, waitlisted, dropped, withdrawn, completed), grading basis, credits, timestamps. |
| `enrollment_event` | Append-only log: register, drop, withdraw, waitlist moves, grade post/change, override applied; actor and channel (self_service, staff, agent, batch). |
| `waitlist_entry` | Position and notification lifecycle. |
| `registration_override` | Prerequisite, capacity, time-conflict, level, overload overrides with grantor. |

## Academic record (`records.py`)
| Table | Purpose |
|---|---|
| `grade` | One per enrollment; letter, quality points, GPA/credit flags, incomplete deadline. |
| `grade_change` | Old/new grade, reason, requester, approver. |
| `student_term_record` | Per student per term: attempted/earned/GPA credits, term and cumulative GPA, standing, classification. |
| `academic_action` | Probation, suspension, dismissal, reinstatement, dean's list, appeals. |
| `transfer_institution`, `articulation_rule`, `transfer_credit` | External schools, standing equivalencies, evaluated credit per student. |
| `test_credit` | AP/IB/CLEP/DSST credit. |
| `graduation_application`, `degree_awarded` | Application lifecycle through conferral; honors, final GPA, diploma status. |
| `degree_audit` | Snapshots of audit runs (actual or what-if) with JSON result. Empty in seed; the system computes these. |

## Documents and compliance (`documents.py`)
| Table | Purpose |
|---|---|
| `transcript_request` | Keyed on `person` (alumni too); type, delivery, recipient, fee, status, hold note. |
| `enrollment_verification` | Purpose, recipient, reported load, status. |
| `ferpa_release` | Named third party, scope, passphrase hash, revocation. |
| `ferpa_directory_optout` | Directory information suppression. |
| `disclosure_log` | FERPA-required record of disclosures: to whom, what, legal basis. |
| `petition` | Policy exceptions: late add/drop, retro withdrawal, overload, residency, standing and grade appeals, waivers. |

## Security (`security.py`)
| Table | Purpose |
|---|---|
| `user_account` | One per person, SSO-style (no password in seed). |
| `role`, `permission`, `role_permission` | 16 roles, 44 permission codes like `enrollment.register.any`, `transcript.issue`. |
| `user_role` | Grants, optionally scoped to a department or college. |
| `audit_log` | Actor (user/agent/system), action, table, record, before/after JSON. |

## Conventions
- Integer surrogate PKs everywhere; natural keys get unique constraints (`university_id`, `email`, `(term, crn)`, `(student, section)`).
- `*_person_id` columns point at `person`, not at role tables, so staff and faculty can act in any workflow.
- Timestamps are `timestamptz`. Dates that are policy deadlines are `date`.
- JSON columns (`enrollment_event.details`, `degree_audit.result`, `audit_log.before/after`) hold structured detail that varies by event.
