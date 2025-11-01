"""
Google Sheets integration utility for Studio forms.
"""
import logging
from datetime import datetime
from typing import List, Optional

from django.conf import settings
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

log = logging.getLogger(__name__)


class GoogleSheetsClient:
    """
    Client for writing form submissions to Google Sheets.
    """
    
    def __init__(self):
        self.credentials = None
        self.service = None
        self._initialize_client()
    
    def _initialize_client(self):
        """Initialize the Google Sheets API client."""
        try:
            credentials_file = getattr(settings, 'GOOGLE_SHEETS_CREDENTIALS_FILE', None)
            if not credentials_file:
                log.error("GOOGLE_SHEETS_CREDENTIALS_FILE not configured")
                return
            
            self.credentials = service_account.Credentials.from_service_account_file(
                credentials_file,
                scopes=['https://www.googleapis.com/auth/spreadsheets']
            )
            
            self.service = build('sheets', 'v4', credentials=self.credentials)
            log.info("Google Sheets client initialized successfully")
            
        except Exception as e:
            log.error(f"Failed to initialize Google Sheets client: {e}")
            self.service = None
    
    def append_form_submission(self, form_data: dict) -> bool:
        """
        Append a form submission to the configured Google Sheet.
        
        Args:
            form_data: Dictionary containing form field values
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.service:
            log.error("Google Sheets service not available")
            return False
        
        spreadsheet_id = getattr(settings, 'GOOGLE_SHEETS_SPREADSHEET_ID', None)
        if not spreadsheet_id:
            log.error("GOOGLE_SHEETS_SPREADSHEET_ID not configured")
            return False
        
        try:
            # Prepare row data
            timestamp = datetime.now().isoformat()
            row_values = [
                timestamp,
                form_data.get('name', ''),
                form_data.get('email', ''),
                form_data.get('organization', ''),
                form_data.get('organization_description', ''),
            ]
            
            # Append to sheet
            range_name = 'Form responses 1!A:E'  # Adjust to match your sheet tab name
            body = {
                'values': [row_values]
            }
            
            result = self.service.spreadsheets().values().append(
                spreadsheetId=spreadsheet_id,
                range=range_name,
                valueInputOption='USER_ENTERED',
                body=body
            ).execute()
            
            log.info(f"Successfully added form submission to Google Sheets: {result.get('updates', {}).get('updatedRows', 0)} rows")
            return True
            
        except HttpError as e:
            log.error(f"Google Sheets API error: {e}")
            return False
        except Exception as e:
            log.error(f"Unexpected error writing to Google Sheets: {e}")
            return False


# Global instance
_sheets_client = None


def get_sheets_client() -> Optional[GoogleSheetsClient]:
    """Get or create the global Google Sheets client instance."""
    global _sheets_client
    if _sheets_client is None or _sheets_client.service is None:
        _sheets_client = GoogleSheetsClient()
    return _sheets_client


def submit_to_google_sheets(form_data: dict) -> bool:
    """
    Convenience function to submit form data to Google Sheets.
    
    Args:
        form_data: Dictionary containing form field values
        
    Returns:
        bool: True if successful, False otherwise
    """
    client = get_sheets_client()
    if client:
        return client.append_form_submission(form_data)
    return False
