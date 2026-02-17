"""CSV 파싱 유틸리티."""
import csv
import io
import logging
import re

from fastapi import UploadFile

from app.config import settings
from app.exceptions import (
    CSVParsingError,
    InvalidFormatError,
    InvalidSubscriptionError,
    UnsupportedFileTypeError,
)

logger = logging.getLogger(__name__)

UUID_PATTERN = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)


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

    단일 컬럼(이메일만) 또는 2컬럼(이메일, subscription_id) CSV를 지원한다.
    헤더가 있는 경우와 없는 경우 모두 처리 가능하다.

    Supported CSV formats::

        # 1-column (email only) — uses default subscription
        email
        johndoe@company.com

        # 2-column (email, subscription_id) — per-participant subscription
        email,subscription_id
        johndoe@company.com,00000000-0000-0000-0000-000000000000

    Args:
        file: 업로드된 CSV 파일.

    Returns:
        'alias', 'email', 'subscription_id' 키를 가진 참가자 딕셔너리 리스트.

    Raises:
        UnsupportedFileTypeError: CSV 파일이 아닌 경우.
        InvalidFormatError: 데이터 형식이 유효하지 않은 경우.
        InvalidSubscriptionError: subscription_id가 허용 목록에 없는 경우.
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

        # Detect column format from header or first data row
        has_two_columns, start_index = _detect_csv_format(lines)

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

            subscription_id = _extract_subscription_id(
                columns, has_two_columns, row_num
            )

            participants.append({
                'alias': alias,
                'email': email.lower(),
                'subscription_id': subscription_id,
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


def _detect_csv_format(lines: list[str]) -> tuple[bool, int]:
    """Detect whether the CSV has 1 or 2 columns and whether a header row is present.

    Returns:
        Tuple of (has_two_columns, start_index).
    """
    first_line_lower = lines[0].lower().replace('"', '').replace("'", '').strip()
    columns = [c.strip() for c in first_line_lower.split(',')]

    # Check for known header patterns
    if columns[0] == 'email':
        has_two_columns = len(columns) >= 2 and columns[1] == 'subscription_id'
        return has_two_columns, 1

    # No header — detect from first data row
    has_two_columns = len(columns) >= 2 and bool(UUID_PATTERN.match(columns[1]))
    return has_two_columns, 0


def _extract_subscription_id(
    columns: list[str], has_two_columns: bool, row_num: int
) -> str:
    """Extract and validate subscription_id from a CSV row.

    Args:
        columns: Split CSV columns for the row.
        has_two_columns: Whether the CSV has a subscription_id column.
        row_num: Row number for error messages.

    Returns:
        Validated subscription_id string.

    Raises:
        InvalidFormatError: If the UUID format is invalid.
        InvalidSubscriptionError: If the subscription is not in the allowed list.
    """
    if not has_two_columns or len(columns) < 2 or not columns[1]:
        return settings.azure_sp_subscription_id

    sub_id = columns[1]

    if not UUID_PATTERN.match(sub_id):
        raise InvalidFormatError(
            f"Invalid subscription ID format '{sub_id}' at row {row_num}",
            field="subscription_id",
            expected_format="UUID (e.g., 00000000-0000-0000-0000-000000000000)",
        )

    if not settings.is_valid_subscription(sub_id):
        raise InvalidSubscriptionError(
            f"Subscription '{sub_id}' at row {row_num} is not in the allowed list",
            subscription_id=sub_id,
        )

    return sub_id


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

    Args:
        participants: alias, email, upn, password, subscription_id를 포함하는
            참가자 딕셔너리 목록.

    Returns:
        CSV 문자열.
    """
    output = io.StringIO()
    fieldnames = ['email', 'alias', 'upn', 'password', 'subscription_id', 'resource_group']
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    for participant in participants:
        writer.writerow({
            'email': participant.get('email', ''),
            'alias': participant['alias'],
            'upn': participant['upn'],
            'password': participant['password'],
            'subscription_id': participant.get('subscription_id', ''),
            'resource_group': participant.get('resource_group', '')
        })

    return output.getvalue()
