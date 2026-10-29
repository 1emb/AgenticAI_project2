"""Hand-written catalog for the two majors: departments, programs, courses, prerequisites, degree plans.

Everything here is fixed data, not generated. The generator (generate.py) adds terms, people and lectures around it.
Course level follows the number: 1000-2999 lower division, 3000-4999 upper division, 5000+ graduate.
"""

DEPARTMENTS = [
    ("CS", "Computer Science"), ("ENG", "Engineering"), ("MATH", "Mathematics"), ("PHYS", "Physics"),
    ("ENGL", "English"), ("HIST", "History"), ("COMM", "Communication"), ("PSY", "Psychology"),
    ("ECON", "Economics"), ("PHIL", "Philosophy"),
]

# code, department, name, degree, total credits, minimum GPA
PROGRAMS = [
    ("BSCS", "CS", "Bachelor of Science in Computer Science", "BS", 120, "2.00"),
    ("BSENG", "ENG", "Bachelor of Science in Engineering", "BS", 128, "2.00"),
    ("MSCS", "CS", "Master of Science in Computer Science", "MS", 30, "3.00"),
    ("MSENG", "ENG", "Master of Science in Engineering", "MS", 30, "3.00"),
]

# code, title, credit hours, description. Retired courses are listed in RETIRED with their last term.
COURSES = [
    # Computer Science
    ("CS 1110", "Introduction to Programming", 4, "Problem solving and program design in Python: variables, control flow, functions, lists and files."),
    ("CS 1120", "Computer Science Principles", 3, "A broad look at computing: algorithms, data, networks, security and the impact of computing on society."),
    ("CS 2210", "Data Structures", 4, "Lists, stacks, queues, trees, hash tables and graphs; analysis of their operations; implementation in Java."),
    ("CS 2215", "Programming in C++", 3, "Systems-level programming in C++: pointers, memory management, classes and the standard library."),
    ("CS 2230", "Computer Organization", 3, "Digital logic, instruction sets, assembly language, memory hierarchy and processor design."),
    ("CS 2250", "Programming in Java", 3, "Object-oriented programming in Java. Retired; replaced by the Java track inside CS 2210."),
    ("CS 3310", "Algorithms", 3, "Design and analysis of algorithms: divide and conquer, greedy methods, dynamic programming, graph algorithms, NP-completeness."),
    ("CS 3320", "Operating Systems", 3, "Processes and threads, scheduling, synchronization, memory management, file systems."),
    ("CS 3350", "Programming Languages", 3, "Syntax, semantics and implementation of programming languages; functional and logic paradigms."),
    ("CS 3410", "Database Systems", 3, "Relational model, SQL, normalization, transactions, indexing and query processing."),
    ("CS 3420", "Software Engineering", 3, "Requirements, design, testing, version control and team development of a medium-sized system."),
    ("CS 3510", "Computer Networks", 3, "Protocol layers, TCP/IP, routing, congestion control and network programming."),
    ("CS 4110", "Compiler Construction", 3, "Lexical analysis, parsing, semantic analysis, intermediate code and code generation."),
    ("CS 4310", "Theory of Computation", 3, "Automata, formal languages, computability and complexity."),
    ("CS 4510", "Computer Security", 3, "Threat models, cryptography in practice, authentication, software and network security."),
    ("CS 4710", "Machine Learning", 3, "Supervised and unsupervised learning, model evaluation, neural networks."),
    ("CS 4720", "Artificial Intelligence", 3, "Search, knowledge representation, planning, reasoning under uncertainty."),
    ("CS 4750", "Computer Graphics", 3, "Rendering pipeline, transformations, shading, modeling and animation."),
    ("CS 4810", "Distributed Systems", 3, "Consistency, replication, fault tolerance, consensus and distributed storage."),
    ("CS 4910", "Senior Project", 3, "Capstone team project from proposal to delivery."),
    ("CS 5110", "Advanced Algorithms", 3, "Randomized, approximation and online algorithms; advanced data structures."),
    ("CS 5320", "Advanced Operating Systems", 3, "Kernel design, virtualization, concurrency at scale; research paper discussion."),
    ("CS 5410", "Advanced Database Systems", 3, "Query optimization, distributed and NoSQL databases, transaction processing internals."),
    ("CS 5710", "Advanced Machine Learning", 3, "Deep learning, probabilistic models, optimization and current research."),
    ("CS 5720", "Natural Language Processing", 3, "Language models, parsing, information extraction, machine translation."),
    ("CS 5810", "Cloud Computing", 3, "Cloud architectures, containers and orchestration, serverless computing, cost and reliability."),
    ("CS 5990", "Master's Thesis", 6, "Supervised research culminating in a written thesis and defense."),
    # Engineering
    ("ENG 1110", "Introduction to Engineering", 3, "The engineering profession, design process, teamwork, units and estimation."),
    ("ENG 1120", "Engineering Graphics", 2, "Sketching, orthographic projection and computer-aided drawing."),
    ("ENG 2110", "Statics", 3, "Forces, moments, equilibrium of particles and rigid bodies, trusses and frames."),
    ("ENG 2120", "Dynamics", 3, "Kinematics and kinetics of particles and rigid bodies; work, energy, impulse and momentum."),
    ("ENG 2210", "Circuits I", 3, "DC and AC circuit analysis, network theorems, operational amplifiers."),
    ("ENG 2310", "Thermodynamics", 3, "Properties of substances, first and second laws, cycles."),
    ("ENG 2410", "Materials Science", 3, "Structure and properties of metals, polymers, ceramics and composites."),
    ("ENG 2450", "Surveying", 2, "Field measurement and mapping. Retired."),
    ("ENG 3110", "Mechanics of Materials", 3, "Stress, strain, torsion, bending, deflection and buckling."),
    ("ENG 3210", "Circuits II", 3, "Transient and steady-state analysis, Laplace methods, filters."),
    ("ENG 3310", "Fluid Mechanics", 3, "Fluid statics, conservation laws, pipe flow and dimensional analysis."),
    ("ENG 3410", "Engineering Economics", 3, "Time value of money, comparison of alternatives, depreciation and risk."),
    ("ENG 3510", "Control Systems", 3, "Modeling, transfer functions, stability, root locus and frequency response."),
    ("ENG 4110", "Machine Design", 3, "Design of machine elements under static and fatigue loading."),
    ("ENG 4210", "Power Systems", 3, "Generation, transmission and distribution; power flow and protection."),
    ("ENG 4310", "Heat Transfer", 3, "Conduction, convection and radiation; heat exchangers."),
    ("ENG 4510", "Robotics", 3, "Kinematics, sensing, control and programming of robotic systems."),
    ("ENG 4910", "Capstone Design I", 3, "Team design project: problem definition, specification and preliminary design."),
    ("ENG 4920", "Capstone Design II", 3, "Team design project: detailed design, build, test and presentation."),
    ("ENG 5110", "Advanced Mechanics of Materials", 3, "Energy methods, plates and shells, elasticity and plasticity."),
    ("ENG 5310", "Computational Fluid Dynamics", 3, "Numerical solution of the governing equations of fluid flow."),
    ("ENG 5510", "Advanced Control Systems", 3, "State-space methods, optimal and robust control."),
    ("ENG 5610", "Finite Element Analysis", 3, "Formulation and application of finite element methods."),
    ("ENG 5990", "Master's Thesis", 6, "Supervised research culminating in a written thesis and defense."),
    # Mathematics and physics
    ("MATH 1511", "Calculus I", 4, "Limits, derivatives and applications, introduction to integration."),
    ("MATH 1521", "Calculus II", 4, "Techniques of integration, sequences and series, parametric curves."),
    ("MATH 2210", "Discrete Mathematics", 3, "Logic, proofs, sets, relations, counting and graphs."),
    ("MATH 2520", "Differential Equations", 3, "First and second order equations, Laplace transforms, systems."),
    ("MATH 2530", "Linear Algebra", 3, "Matrices, vector spaces, eigenvalues and linear transformations."),
    ("MATH 2531", "Calculus III", 4, "Vectors, partial derivatives, multiple integrals and vector calculus."),
    ("MATH 3110", "Probability and Statistics", 3, "Probability, random variables, estimation and hypothesis testing."),
    ("PHYS 2110", "Physics I: Mechanics", 4, "Kinematics, Newton's laws, energy, momentum, rotation and oscillations."),
    ("PHYS 2120", "Physics II: Electricity and Magnetism", 4, "Electric and magnetic fields, circuits, waves and optics."),
    # General education
    ("ENGL 1110", "Composition I", 4, "Writing for academic audiences: process, argument and revision."),
    ("ENGL 1120", "Composition II", 3, "Research-based writing and argumentation."),
    ("ENGL 2210", "Technical and Professional Writing", 3, "Reports, proposals, documentation and correspondence for technical fields."),
    ("HIST 1110", "World History I", 3, "Human societies from antiquity to 1500."),
    ("HIST 1120", "World History II", 3, "Global history from 1500 to the present."),
    ("HIST 2110", "United States History", 3, "The United States from colonization to the present."),
    ("COMM 1130", "Public Speaking", 3, "Preparing and delivering speeches; listening and audience analysis."),
    ("PSY 1110", "Introduction to Psychology", 3, "Survey of behavior and mental processes."),
    ("ECON 2110", "Principles of Microeconomics", 3, "Markets, prices, consumer and producer behavior."),
    ("ECON 2120", "Principles of Macroeconomics", 3, "National income, inflation, unemployment and policy."),
    ("PHIL 1110", "Introduction to Philosophy", 3, "Central problems of knowledge, reality and value."),
    ("PHIL 2110", "Ethics", 3, "Major ethical theories and their application to contemporary issues."),
]

# course -> last term it was offered; is_active becomes False and no lecture exists after that term
RETIRED = {"CS 2250": "202580", "ENG 2450": "202510"}

# course -> list of groups; a group is a list of (required course, min grade). Groups are AND, members of a group are OR.
PREREQUISITES = {
    "CS 2210": [[("CS 1110", "C-")]],
    "CS 2215": [[("CS 1110", "C-")]],
    "CS 2230": [[("CS 1110", "C-")]],
    "CS 2250": [[("CS 1110", "C-")]],
    "CS 3310": [[("CS 2210", "C-")], [("MATH 2210", "C")]],
    "CS 3320": [[("CS 2210", "C-")], [("CS 2230", "C-")]],
    "CS 3350": [[("CS 2210", "C-")]],
    "CS 3410": [[("CS 2210", "C-")]],
    "CS 3420": [[("CS 2210", "C-")]],
    "CS 3510": [[("CS 2230", "C-")]],
    "CS 4110": [[("CS 3350", "C-")]],
    "CS 4310": [[("CS 3310", "C-")]],
    "CS 4510": [[("CS 3320", "C-")], [("CS 3510", "C-")]],
    "CS 4710": [[("CS 3310", "C-")], [("MATH 2530", "C-")]],
    "CS 4720": [[("CS 3310", "C-")]],
    "CS 4750": [[("CS 2210", "C-")], [("MATH 2530", "C-")]],
    "CS 4810": [[("CS 3320", "C-")]],
    "CS 4910": [[("CS 3420", "C")]],
    "CS 5110": [[("CS 3310", "B-")]],
    "CS 5320": [[("CS 3320", "B-")]],
    "CS 5410": [[("CS 3410", "B-")]],
    "CS 5710": [[("CS 4710", "B-")]],
    "CS 5720": [[("CS 4710", "B-"), ("CS 4720", "B-")]],
    "CS 5810": [[("CS 4810", "B-"), ("CS 3510", "B-")]],
    "ENG 2110": [[("PHYS 2110", "C-")], [("MATH 1521", "C-")]],
    "ENG 2120": [[("ENG 2110", "C-")]],
    "ENG 2210": [[("PHYS 2120", "C-")], [("MATH 1521", "C-")]],
    "ENG 2310": [[("PHYS 2110", "C-")], [("MATH 1521", "C-")]],
    "ENG 2410": [[("PHYS 2110", "C-")]],
    "ENG 3110": [[("ENG 2110", "C-")]],
    "ENG 3210": [[("ENG 2210", "C-")], [("MATH 2520", "C-")]],
    "ENG 3310": [[("ENG 2120", "C-")], [("MATH 2520", "C-")]],
    "ENG 3410": [[("MATH 1521", "C-")]],
    "ENG 3510": [[("ENG 3210", "C-"), ("ENG 2120", "C-")], [("MATH 2520", "C-")]],
    "ENG 4110": [[("ENG 3110", "C-")]],
    "ENG 4210": [[("ENG 3210", "C-")]],
    "ENG 4310": [[("ENG 2310", "C-")], [("ENG 3310", "C-")]],
    "ENG 4510": [[("ENG 3510", "C-")], [("CS 1110", "C-")]],
    "ENG 4910": [[("ENG 3110", "C"), ("ENG 3210", "C")]],
    "ENG 4920": [[("ENG 4910", "C")]],
    "ENG 5110": [[("ENG 3110", "B-")]],
    "ENG 5310": [[("ENG 3310", "B-")]],
    "ENG 5510": [[("ENG 3510", "B-")]],
    "ENG 5610": [[("ENG 3110", "B-")], [("MATH 2530", "B-")]],
    "MATH 1521": [[("MATH 1511", "C")]],
    "MATH 2210": [[("MATH 1511", "C-")]],
    "MATH 2520": [[("MATH 1521", "C-")]],
    "MATH 2530": [[("MATH 1521", "C-")]],
    "MATH 2531": [[("MATH 1521", "C")]],
    "MATH 3110": [[("MATH 1521", "C-")]],
    "PHYS 2110": [[("MATH 1511", "C-")]],
    "PHYS 2120": [[("PHYS 2110", "C-")], [("MATH 1521", "C-")]],
    "ENGL 1120": [[("ENGL 1110", "C-")]],
    "ENGL 2210": [[("ENGL 1110", "C-")]],
}

GEN_ED_OPTIONS = ["ENGL 2210", "HIST 1110", "HIST 1120", "HIST 2110", "COMM 1130", "PSY 1110", "ECON 2110", "ECON 2120", "PHIL 1110", "PHIL 2110"]

# program -> {"required": [(course, category, suggested term)], "elective": [courses], "general_education": [courses]}
# Required rows have is_required = True; option rows have is_required = False and no suggested term.
DEGREE_PLANS = {
    "BSCS": {
        "required": [
            ("CS 1110", "core", 1), ("MATH 1511", "core", 1), ("ENGL 1110", "general_education", 1),
            ("CS 2210", "core", 2), ("MATH 1521", "core", 2), ("ENGL 1120", "general_education", 2),
            ("CS 2215", "core", 3), ("CS 2230", "core", 3), ("MATH 2210", "core", 3), ("PHYS 2110", "core", 3),
            ("CS 3310", "core", 4), ("CS 3350", "core", 4), ("MATH 2530", "core", 4), ("PHYS 2120", "core", 4),
            ("CS 3320", "core", 5), ("CS 3410", "core", 5), ("MATH 3110", "core", 5),
            ("CS 3420", "core", 6), ("CS 3510", "core", 6),
            ("CS 4910", "core", 8),
        ],
        "elective": ["CS 4110", "CS 4310", "CS 4510", "CS 4710", "CS 4720", "CS 4750", "CS 4810"],
        "general_education": GEN_ED_OPTIONS,
    },
    "BSENG": {
        "required": [
            ("ENG 1110", "core", 1), ("ENG 1120", "core", 1), ("MATH 1511", "core", 1), ("ENGL 1110", "general_education", 1),
            ("CS 1110", "core", 2), ("MATH 1521", "core", 2), ("PHYS 2110", "core", 2), ("ENGL 1120", "general_education", 2),
            ("ENG 2110", "core", 3), ("ENG 2410", "core", 3), ("MATH 2531", "core", 3), ("PHYS 2120", "core", 3),
            ("ENG 2120", "core", 4), ("ENG 2210", "core", 4), ("ENG 2310", "core", 4), ("MATH 2520", "core", 4),
            ("ENG 3110", "core", 5), ("ENG 3210", "core", 5), ("MATH 2530", "core", 5),
            ("ENG 3310", "core", 6), ("ENG 3510", "core", 6), ("MATH 3110", "core", 6),
            ("ENG 4910", "core", 7), ("ENG 4920", "core", 8),
        ],
        "elective": ["ENG 3410", "ENG 4110", "ENG 4210", "ENG 4310", "ENG 4510", "CS 2215"],
        "general_education": GEN_ED_OPTIONS,
    },
    "MSCS": {
        "required": [("CS 5110", "core", 1), ("CS 5990", "core", 3)],
        "elective": ["CS 5320", "CS 5410", "CS 5710", "CS 5720", "CS 5810", "CS 4510", "CS 4710", "CS 4720", "CS 4810"],
        "general_education": [],
    },
    "MSENG": {
        "required": [("ENG 5110", "core", 1), ("ENG 5990", "core", 3)],
        "elective": ["ENG 5310", "ENG 5510", "ENG 5610", "ENG 4110", "ENG 4210", "ENG 4310", "ENG 4510"],
        "general_education": [],
    },
}

# program -> {category: minimum credits}. Core needs no entry: its credits are the sum of the required core courses.
CATEGORY_MINIMUMS = {
    "BSCS": {"elective": 15, "general_education": 25},
    "BSENG": {"elective": 9, "general_education": 25},
    "MSCS": {"elective": 21},
    "MSENG": {"elective": 21},
}


def course_level(code: str) -> str:
    n = int(code.split()[1][:4])
    return "lower_division" if n < 3000 else "upper_division" if n < 5000 else "graduate"


def check() -> None:
    """Internal consistency: every referenced course exists, plans and prerequisites point at real courses."""
    codes = {c[0] for c in COURSES}
    assert len(codes) == len(COURSES), "duplicate course code"
    subjects = {d[0] for d in DEPARTMENTS}
    for code in codes:
        assert code.split()[0] in subjects, f"{code}: subject has no department"
    for code, groups in PREREQUISITES.items():
        assert code in codes, code
        for g in groups:
            for req, _ in g:
                assert req in codes and req != code, (code, req)
    for prog, plan in DEGREE_PLANS.items():
        seen = set()
        for code, cat, term in plan["required"]:
            assert code in codes and cat in ("core", "general_education") and 1 <= term <= 8, (prog, code)
            seen.add(code)
        for cat in ("elective", "general_education"):
            for code in plan[cat]:
                assert code in codes and code not in seen, (prog, code)
                seen.add(code)
    assert set(CATEGORY_MINIMUMS) == set(DEGREE_PLANS)


check()
