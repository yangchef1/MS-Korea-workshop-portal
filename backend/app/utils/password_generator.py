"""비밀번호 생성 유틸리티."""
import secrets
import string

_SYMBOLS = "!@#$%^&*()_+-=[]{}|;:,.<>?"


def generate_password(length: int = 16) -> str:
    """안전한 랜덤 비밀번호를 생성한다.

    대소문자, 숫자, 특수문자를 각각 최소 1개씩 포함한다.

    Args:
        length: 비밀번호 길이. 기본값 16.

    Returns:
        랜덤 생성된 비밀번호 문자열.
    """
    lowercase = string.ascii_lowercase
    uppercase = string.ascii_uppercase
    digits = string.digits

    password = [
        secrets.choice(lowercase),
        secrets.choice(uppercase),
        secrets.choice(digits),
        secrets.choice(_SYMBOLS),
    ]

    all_chars = lowercase + uppercase + digits + _SYMBOLS
    password.extend(secrets.choice(all_chars) for _ in range(length - 4))

    secrets.SystemRandom().shuffle(password)

    return ''.join(password)
