# Registrar domain definition

Agreed 2026-10-19. This is the scope the database and, later, the agents are built against.

## What the registrar office does

**Academic record (system of record)**
- Maintains the official student record: enrollment status, program, major/minor, grades, GPA, credits, academic standing, degrees awarded.
- Posts grades submitted by instructors; processes grade changes and incompletes.
- Applies academic policy: probation, suspension, dean's list, repeat-course rules, residency requirements.

**Registration and enrollment**
- Builds the academic calendar: term dates, add/drop deadlines, withdrawal deadline, census date.
- Runs course registration: time tickets, prerequisites/corequisites, holds, seat caps, waitlists, overrides.
- Processes add/drop, withdrawal, leave of absence, readmission, change of major.
- Issues enrollment verifications (lenders, insurers, employers, National Student Clearinghouse).

**Course and curriculum**
- Maintains the course catalog: codes, descriptions, credits, prerequisites, gen-ed designation.
- Builds the schedule of classes each term: sections, instructors, times, rooms, modality.
- Assigns classrooms. Records curriculum changes approved by faculty governance.

**Transfer and articulation**
- Evaluates external transcripts and AP/IB/CLEP scores against equivalency rules.
- Maintains the articulation database.

**Degree audit and graduation**
- Runs degree audits against program requirements (by catalog year).
- Processes graduation applications, certifies completion, confers degrees, prints diplomas.

**Transcripts and documents**
- Issues official/unofficial transcripts and diplomas; verifies degrees for third parties.

**Compliance and reporting**
- FERPA: directory opt-outs, release authorizations, disclosure log.
- Federal/state reporting (IPEDS, Clearinghouse, Title IV enrollment status), VA certification, NCAA eligibility, SEVIS.

**Identity and student status**
- Name changes, preferred names, pronouns, residency classification, ID assignment.

## Data the registrar touches

| Domain | Owner |
|---|---|
| Student biographic (name, DOB, SSN hash, citizenship, addresses) | Registrar, shared with Admissions |
| Academic record (grades, GPA, standing, degrees) | Registrar |
| Enrollment (registrations, drops, withdrawals, waitlists) | Registrar |
| Course catalog, schedule of classes, academic calendar | Registrar (content from departments / governance) |
| Program requirements by catalog year | Registrar (content from faculty governance) |
| Transfer and articulation | Registrar |
| Holds | Placed by Bursar, Advising, Dean of Students, Health; enforced by Registrar |
| FERPA preferences and disclosure log | Registrar |
| Admissions decisions, bursar balance, financial aid status, facilities, conduct, SEVIS | Other offices; registrar reads or exchanges |

Sensitivity tiers: SSN, immigration, conduct, and grades are highest. Directory information is public unless opted out. Everything else is a FERPA-protected education record.

## Users

- **Students**: register, drop, view grades, request transcripts, apply to graduate, run audits, update identity, file FERPA releases.
- **Instructors**: rosters, grade entry, prerequisite/capacity overrides, grade-change requests.
- **Advisors**: advisee records, advising holds, what-if audits, program-change approval.
- **Department chairs / schedulers**: propose sections, assign instructors, request rooms, curriculum changes.
- **Deans / provost**: policy exceptions, standing appeals, curriculum approval.
- **Registrar staff / admin**: everything above plus adjudication, overrides, transfer evaluation, record corrections, reporting.
- **Other offices**: Admissions, Bursar, Financial Aid, Dean of Students, International Office, Institutional Research.
- **External**: alumni, employers, verification firms, other universities, Clearinghouse, agencies, lenders.
- **Auditors**: read-only with full audit trail.
- **Agent**: the automated registrar system itself, acting under a service account with its own role.

## Open scope questions

- Full office vs. first slice. Decided 2026-10-19: model the full office in the database; agents can be built slice by slice.
- "Replace" literally vs. agentic front office that escalates exceptions. Not yet decided.
