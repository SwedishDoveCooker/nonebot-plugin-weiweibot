import re

def extract_name(filename, mod=1):
    match = re.match(r"(\d+-)?(.*?)((-\d+)?(_\d+)?)\.(jpg|jpeg|png|gif|bmp)$", filename, re.IGNORECASE)
    if match:
        if mod:
            name = match.group(2)
            return f"{name}"
        else:
            name = match.group(2) + match.group(3)
            return f"{name}"
    return None

