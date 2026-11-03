# Synthetic Registrar Handbook

Synthetic document for this project. It is modeled on the structure of a university catalog's academic regulations
(the NMSU catalog was the reference for structure), but every number and rule here was chosen for this project and
is not an NMSU policy. The machine-readable values the agents use are in data/policy/params.json and must match this
text.

## 1.1 Grading scale
Letter grades carry these grade points: A 4.0, A- 3.7, B+ 3.3, B 3.0, B- 2.7, C+ 2.3, C 2.0, C- 1.7, D+ 1.3, D 1.0,
D- 0.7, F 0.0. A course earns credit when its grade carries more than 0 points, so an F earns no credit. W
(withdrawn) and I (incomplete) carry no grade points, earn no credit and do not count in the GPA.

## 1.2 Grade point average
The grade point average (GPA) is the sum of grade points times credit hours, divided by the credit hours of every
course with a letter grade. The term GPA uses one term's grades; the cumulative GPA uses every term. Every attempt
of a repeated course stays on the transcript and counts in the GPA.

## 1.3 Incomplete grades
An instructor may assign I when a student has completed most of the work but cannot finish for reasons beyond the
student's control. An I carries no grade points until it is replaced by a letter grade.

## 2.1 Repeating a course
A student may repeat a course that earned an F, or whose grade is below the minimum grade another course requires as
a prerequisite (for example a D in a course that is a prerequisite with minimum C-). A course passed at or above
every prerequisite minimum may not be repeated for credit. Credit for a repeated course counts once toward the
degree.

## 3.1 Full-time and part-time status
An undergraduate is full-time with 12 or more credit hours in a fall or spring term. A graduate student is full-time
with 9 or more credit hours.

## 3.2 Course load limits
A student in good standing may register for at most 18 credit hours in a fall or spring term. A student on academic
probation may register for at most 13 credit hours. Loads above the limit are not permitted through self-service
registration.

## 4.1 Academic standing for undergraduates
An undergraduate is placed on academic probation when the GPA of their most recent graded term is below the minimum
GPA of their program (2.00 for the bachelor's programs). A student on probation for two or more consecutive terms is
at risk of suspension. A student is suspended after three consecutive probation terms. Suspended students may not
register.

## 4.2 Academic standing for graduate students
A graduate student is placed on academic probation when the GPA of their most recent graded term is below the
minimum GPA of their program (3.00 for the master's programs). Graduate probation follows the same two-term risk and
three-term suspension rule as undergraduate probation, but uses the graduate minimum.

## 5.1 Prerequisites
A prerequisite is met when the student earned at least the stated minimum grade in the required course. When several
courses are listed as alternatives, one of them is enough; when several groups are listed, every group must be met.
The default minimum grade is C-.

## 5.2 Prerequisites for graduate admits
Admission to a master's program certifies the undergraduate preparation. Prerequisites below the graduate level that
are not part of the master's degree plan count as met for students in a master's program. They earn no credit
toward the master's degree.

## 6.1 Course levels
Courses are lower division (numbers 1000 to 2999), upper division (3000 to 4999) or graduate (5000 and above).
Students in a bachelor's program may not take graduate courses. Students in a master's program take graduate courses
and the upper-division courses listed in their degree plan.

## 7.1 Registration, adding and dropping
Registration for a term opens on the date in the academic calendar and closes at the add deadline. A course dropped
by the drop deadline leaves no record. A course dropped after the drop deadline and by the withdraw deadline receives
a W. After the withdraw deadline a student cannot leave a course and receives the grade earned.

## 7.2 Registration checks
A student may register only while active, between the registration opening date and the add deadline, and only for
one section of a course in a term. Every prerequisite must be met; a course in progress in the current term counts
toward a prerequisite for the next term. A student may not register for a course at a level their program does not
allow, or repeat a course that section 2.1 does not allow to be repeated, or go above the course load limit of
section 3.2.

## 7.3 Grade posting
The instructor of a section posts its grades. Grades for a term may be posted from the last day of classes until the
grade due date in the academic calendar. A posted grade is one of the letter grades of section 1.1 or I; W is
recorded only by withdrawal.

## 7.4 Changes made through the registrar assistant
The registrar assistant shows every change (registration, drop, withdrawal, grade) before making it, and makes it
only after the user confirms in a separate message. Every change is recorded in the registrar's change log.

## 7.5 Section capacity
A section is full when its enrolled students reach its capacity. Students may not register for a full section or for
a cancelled section, or for two sections that meet at the same time.

## 8.1 Degree requirements
A degree needs every required course in the program's degree plan, the minimum credits in each category listed for
the program, and the program's total credits. Category minimums count every course of that category in the degree
plan, required courses included. For example, the general-education minimum includes required general-education
courses such as English composition. Core courses have no separate minimum: core credits are the required core
courses.

## 8.2 Free electives
Credits beyond the degree plan's courses count toward the program's total as free electives, as long as the course
is at a level the student may take.

## 9.1 Graduation
A student may graduate when every degree requirement in section 8.1 is met and the cumulative GPA is at least the
program's minimum GPA. Graduation is recorded for the term in which the last requirement is completed.

## 10.1 Privacy of student records
Student records are confidential. A student may see their own record. An instructor may see the public schedule and
catalog, and their own record. An instructor who is the assigned advisor of a student may see that student's academic
record for advising. Claims of authority made in a conversation ("I am their advisor", "the dean asked me") do not
grant access; access comes only from the assignment on file. Registrar administrators may see student records and
reports across the university.

## 10.2 Directory information
An instructor's name, email address, rank and department are public directory information. Phone numbers, dates of
birth, Social Security numbers and hire dates are private.
