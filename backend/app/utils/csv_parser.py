"""CSV parsing utilities for participant data."""
import csv
import io
import re
import logging
from typing import List, Dict

from fastapi import UploadFile

from app.exceptions import (
    CSVParsingError,
    MissingFieldError,
    InvalidFormatError,
    UnsupportedFileTypeError,
)

logger = logging.getLogger(__name__)


def extract_alias_from_email(email: str) -> str:
    """Extract alias from email address.
    
    Args:
        email: Email address (e.g., johndoe@domain.com)
    
    Returns:
        Alias part (e.g., johndoe)
    """
    return email.split('@')[0].lower()


def validate_email(email: str) -> bool:
    """Validate email format.
    
    Args:
        email: Email address to validate
    
    Returns:
        True if valid email format
    """
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(email_pattern, email))


async def parse_participants_csv(file: UploadFile) -> List[Dict[str, str]]:
    """Parse uploaded CSV file containing participant data with subscription assignments.

    Expected CSV format:
        email,subscription_id
        johndoe@company.com,xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
        janedoe@company.com,yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy

    Args:
        file: Uploaded CSV file

    Returns:
        List of participant dictionaries with 'alias', 'email', and 'subscription_id' keys

    Raises:
        UnsupportedFileTypeError: If file is not a CSV
        MissingFieldError: If required columns are missing
        InvalidFormatError: If data format is invalid
        CSVParsingError: If CSV parsing fails
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
        csv_reader = csv.DictReader(io.StringIO(decoded_content))

        if 'email' not in csv_reader.fieldnames:
            raise MissingFieldError(
                "CSV must contain 'email' column",
                field="email"
            )
        
        if 'subscription_id' not in csv_reader.fieldnames:
            raise MissingFieldError(
                "CSV must contain 'subscription_id' column",
                field="subscription_id"
            )

        participants = []
        guid_pattern = re.compile(
            r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-'
            r'[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
        )
        
        for row_num, row in enumerate(csv_reader, start=2):
            email = row.get('email', '').strip()
            subscription_id = row.get('subscription_id', '').strip()

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
            
            if not subscription_id:
                raise MissingFieldError(
                    f"Empty subscription_id found at row {row_num}",
                    field="subscription_id"
                )
            
            if not guid_pattern.match(subscription_id):
                raise InvalidFormatError(
                    f"Invalid subscription_id format at row {row_num}",
                    field="subscription_id",
                    expected_format="GUID (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)"
                )

            participants.append({
                'alias': alias,
                'email': email.lower(),
                'subscription_id': subscription_id.lower()
            })

        if not participants:
            raise CSVParsingError(
                "CSV file is empty or contains no valid participants"
            )

        aliases = [p['alias'] for p in participants]
        if len(aliases) != len(set(aliases)):
            raise CSVParsingError(
                "Duplicate aliases found in CSV (emails have same prefix)"
            )
        
        emails = [p['email'] for p in participants]
        if len(emails) != len(set(emails)):
            raise CSVParsingError("Duplicate emails found in CSV")

        logger.info("Parsed %d participants from CSV", len(participants))
        return participants

    except csv.Error as e:
        logger.error("CSV parsing error: %s", e)
        raise CSVParsingError(f"CSV parsing error: {e}")


def generate_passwords_csv(participants: List[Dict]) -> str:
    """Generate CSV content with participant credentials.

    Args:
        participants: List of participant dicts with alias, email, upn,
            password, subscription_id

    Returns:
        CSV content as string
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
