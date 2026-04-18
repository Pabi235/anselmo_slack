import os
import json
import io
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

GCP_CREDS_JSON = os.environ.get("GCP_SERVICE_ACCOUNT_JSON")
GDRIVE_FOLDER_ID = os.environ.get("GDRIVE_FOLDER_ID")
SCOPES = ['https://www.googleapis.com/auth/drive']

def get_drive_service():
    """Authenticates using the Service Account JSON stored in GitHub Secrets."""
    if not GCP_CREDS_JSON:
        raise ValueError("GCP_SERVICE_ACCOUNT_JSON environment variable is not set.")
    
    creds_dict = json.loads(GCP_CREDS_JSON)
    creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

def get_file_id(service):
    """Finds the ledger.json file specifically inside your shared folder."""
    if not GDRIVE_FOLDER_ID:
         raise ValueError("GDRIVE_FOLDER_ID environment variable is not set.")
         
    query = f"'{GDRIVE_FOLDER_ID}' in parents and name='ledger.json' and trashed=false"
    results = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    items = results.get('files', [])
    return items[0]['id'] if items else None

def load_ledger():
    """Downloads and parses the ledger.json from Google Drive."""
    service = get_drive_service()
    file_id = get_file_id(service)
    
    if not file_id:
        raise Exception("ledger.json not found in the specified Google Drive folder!")
        
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
        
    fh.seek(0)
    return json.loads(fh.read().decode('utf-8'))

def save_ledger(data):
    """Overwrites the existing ledger.json in Google Drive with the updated data."""
    service = get_drive_service()
    file_id = get_file_id(service)
    
    # Convert the Python dictionary back to a JSON string in memory
    media = MediaIoBaseUpload(
        io.StringIO(json.dumps(data, indent=2)), 
        mimetype='application/json',
        resumable=True
    )
    
    if file_id:
        # Update the existing file
        service.files().update(fileId=file_id, media_body=media).execute()
        print("Successfully updated ledger.json in Google Drive.")
    else:
        # Fallback just in case it got deleted
        file_metadata = {'name': 'ledger.json', 'parents': [GDRIVE_FOLDER_ID]}
        service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        print("Created new ledger.json in Google Drive.")