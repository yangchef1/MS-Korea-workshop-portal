"""CSV 파싱 유틸리티."""
import csv
import io
import logging
import re

from fastapi import UploadFile

from app.exceptions import (
    CSVParsingError,
    InvalidFormatError,
    UnsupportedFileTypeError,
)

logger = logging.getLogger(__name__)


def extract_alias_from_email(email: str) -> str:
    """이메일 주소에서 alias를 추출한다.

    Args:
        email: 이메일 주소 (예: johndoe@domain.com)

    Returns:
        alias 부분 (예: johndoe)
    """
    return email.split('@')[0].lower()


def validate_email(email: str) -> bool:
    """이메일 형식을 검증한다.

    Args:
        email: 검증할 이메일 주소

    Returns:
        유효한 이메일 형식이면 True
    """
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(email_pattern, email))


async def parse_participants_csv(file: UploadFile) -> list[dict[str, str]]:
    """업로드된 CSV 파일에서 참가자 목록을 파싱한다.

    이메일만 포함하는 단일 컬럼 CSV를 지원한다.
    헤더가 있는 경우와 없는 경우 모두 처리 가능하다.

    Supported CSV format::

        email
        johndoe@company.com

    Args:
        file: 업로드된 CSV 파일.

    Returns:
        'alias', 'email' 키를 가진 참가자 딕셔너리 리스트.

    Raises:
        UnsupportedFileTypeError: CSV 파일이 아닌 경우.
        InvalidFormatError: 데이터 형식이 유효하지 않은 경우.
        CSVParsingError: CSV 파싱에 실패한 경우.
    """
    if not file.filename.endswith('.csv'):
        raise UnsupportedFileTypeError(
            "File must be a CSV",
            allowed_types=['.csv']
        )

    try:
        content = await file.read()
        decoded_content = content.decode('utf-8')
    except UnicodeDecodeError:
        raise InvalidFormatError(
            "Invalid file encoding. Please use UTF-8",
            field="file",
            expected_format="UTF-8"
        )

    try:
        lines = [
            line.strip()
            for line in decoded_content.strip().splitlines()
            if line.strip()
        ]

        if not lines:
            raise CSVParsingError(
                "CSV file is empty or contains no valid participants"
            )

        # Detect header row
        start_index = _detect_start_index(lines)

        participants = []

        for row_num, line in enumerate(lines[start_index:], start=start_index + 1):
            columns = [c.strip().strip('"').strip("'") for c in line.split(',')]
            email = columns[0]

            if not email:
                raise InvalidFormatError(
                    f"Empty email found at row {row_num}",
                    field="email",
                    expected_format="valid email address"
                )

            if not validate_email(email):
                raise InvalidFormatError(
                    f"Invalid email format '{email}' at row {row_num}",
                    field="email",
                    expected_format="user@domain.com"
                )

            alias = extract_alias_from_email(email)

            if not alias.replace('-', '').replace('_', '').replace('.', '').isalnum():
                raise InvalidFormatError(
                    f"Invalid alias '{alias}' extracted from email at row {row_num}",
                    field="email",
                    expected_format="alphanumeric with dots, hyphens, underscores"
                )

            participants.append({
                'alias': alias,
                'email': email.lower(),
            })

        if not participants:
            raise CSVParsingError(
                "CSV file is empty or contains no valid participants"
            )

        _validate_no_duplicates(participants)

        logger.info("Parsed %d participants from CSV", len(participants))
        return participants

    except (csv.Error, ValueError) as e:
        logger.error("CSV parsing error: %s", e)
        raise CSVParsingError(f"CSV parsing error: {e}")


def _detect_start_index(lines: list[str]) -> int:
    """Detect whether the first line is a header row.

    Returns:
        Start index (1 if header present, 0 otherwise).
    """
    first_line_lower = lines[0].lower().replace('"', '').replace("'", '').strip()
    first_col = first_line_lower.split(',')[0].strip()

    if first_col == 'email':
        return 1

    return 0


def _validate_no_duplicates(participants: list[dict[str, str]]) -> None:
    """Raise CSVParsingError if duplicate aliases or emails are found."""
    aliases = [p['alias'] for p in participants]
    if len(aliases) != len(set(aliases)):
        raise CSVParsingError(
            "Duplicate aliases found in CSV (emails have same prefix)"
        )

    emails = [p['email'] for p in participants]
    if len(emails) != len(set(emails)):
        raise CSVParsingError("Duplicate emails found in CSV")


def generate_passwords_csv(participants: list[dict[str, str]]) -> str:
    """참가자 인증정보 CSV 콘텐츠를 생성한다.

    개인 이메일은 포함하지 않는다 (컴플라이언스).
    UPN(onmicrosoft.com)과 초기 비밀번호만 포함한다.

    Args:
        participants: alias, upn, password, subscription_id를 포함하는
            참가자 딕셔너리 목록.

    Returns:
        CSV 문자열.
    """
    output = io.StringIO()
    fieldnames = ['alias', 'upn', 'password', 'subscription_id', 'resource_group']
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    for participant in participants:
        writer.writerow({
            'alias': participant['alias'],
            'upn': participant['upn'],
            'password': participant['password'],
            'subscription_id': participant.get('subscription_id', ''),
            'resource_group': participant.get('resource_group', ''),
        })

    return output.getvalue()
