def average(values):
    # A supplied empty list triggers ZeroDivisionError.
    return sum(values) / len(values)
