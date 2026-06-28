def calculate_bill(reading):
    rate_per_unit = 0.12
    return round(int(reading) * rate_per_unit, 2)
