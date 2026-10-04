"""Student-style phrasings with answers verified against data/syllabus.json.

Each excluded case is paired, where possible, with a nearby topic that IS
examinable, because the hard part is telling those apart.
"""

PARAPHRASES = [
    # (question as a student would type it, subject, expected verdict)
    ("doubly linked lists", "H2 Computing", "excluded"),               # 9569.1.3.5
    ("linked lists", "H2 Computing", "examinable"),
    ("space complexity of algorithms", "H2 Computing", "excluded"),    # 9569.1.2.5
    ("time complexity and big O", "H2 Computing", "examinable"),
    ("method overloading", "H2 Computing", "excluded"),                # 9569.2.5.4
    ("multiple inheritance", "H2 Computing", "excluded"),
    ("inheritance in OOP", "H2 Computing", "examinable"),
    ("deleting a node from a binary search tree", "H2 Computing", "excluded"),  # 9569.1.3.6
    ("searching a binary search tree", "H2 Computing", "examinable"),
    ("triple product of vectors", "H2 Maths", "excluded"),             # 9758.3.2
    ("scalar product of two vectors", "H2 Maths", "examinable"),
    ("complex numbers in polar form", "H2 Maths", "excluded"),         # 9758.4.1
    ("complex numbers in cartesian form", "H2 Maths", "examinable"),
    ("reduction formulae", "H2 Maths", "excluded"),                    # 9758.5.3
    ("normal approximation to the binomial distribution", "H2 Maths", "excluded"),  # 9758.6.3
    ("normal distribution", "H2 Maths", "examinable"),
    ("cumulative distribution function of a discrete random variable", "H2 Maths", "excluded"),  # 9758.6.2
    ("volume of revolution when the curve is parametric", "H2 Maths", "excluded"),  # 9758.5.4
    ("volume of revolution about the x-axis", "H2 Maths", "examinable"),
    ("trapezium rule", "H1 Maths", "excluded"),                        # 8865.2.2
    ("differentiation from first principles", "H1 Maths", "excluded"), # 8865.2.1
    ("implicit differentiation", "H1 Maths", "excluded"),
    ("implicit differentiation", "H2 Maths", "examinable"),            # 9758.5.1 includes it
    ("change of base of logarithms", "H1 Maths", "excluded"),          # 8865.1.1
    ("area below the x-axis", "H1 Maths", "excluded"),                 # 8865.2.2
    ("definite integrals", "H1 Maths", "examinable"),
]
