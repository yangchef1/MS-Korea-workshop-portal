"""
Password generation utilities
"""
import secrets
import string


def generate_password(length: int = 16) -> str:
    """
    Generate a secure random password

    Args:
        length: Length of password (default 16)

    Returns:
        Random password with mixed case, numbers, and symbols
    """
    lowercase = string.ascii_lowercase
    uppercase = string.ascii_uppercase
    digits = string.digits
    symbols = "!@#$%^&*()_+-=[]{}|;:,.<>?"

    password = [
        secrets.choice(lowercase),
        secrets.choice(uppercase),
        secrets.choice(digits),
        secrets.choice(symbols)
    ]

    all_chars = lowercase + uppercase + digits + symbols
    password.extend(secrets.choice(all_chars) for _ in range(length - 4))

    secrets.SystemRandom().shuffle(password)

    return ''.join(password)
