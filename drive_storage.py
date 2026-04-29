import os
import json
import io
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

SCOPES = ['https://www.googleapis.com/auth/drive']

def get_drive_service():
    """Authenticates using the Service Account JSON stored in GitHub Secrets."""
    creds_json = os.environ.get("GCP_SERVICE_ACCOUNT_JSON")
    if not creds_json:
        raise ValueError("GCP_SERVICE_ACCOUNT_JSON environment variable is not set or empty.")
    
    try:
        creds_dict = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        return build('drive', 'v3', credentials=creds)
    except json.JSONDecodeError:
        raise ValueError("GCP_SERVICE_ACCOUNT_JSON is not a valid JSON string.")

def get_file_id(service):
    """Finds the ledger.json file specifically inside your shared folder."""
    folder_id = os.environ.get("GDRIVE_FOLDER_ID")
    if not folder_id:
         raise ValueError("GDRIVE_FOLDER_ID environment variable is not set or empty.")
         
    query = f"'{folder_id}' in parents and name='ledger.json' and trashed=false"
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
    folder_id = os.environ.get("GDRIVE_FOLDER_ID")
    
    # Convert the Python dictionary back to a JSON string and encode to bytes
    json_bytes = json.dumps(data, indent=2).encode('utf-8')
    media = MediaIoBaseUpload(
        io.BytesIO(json_bytes), 
        mimetype='application/json',
        resumable=True
    )
    
    if file_id:
        # Update the existing file
        service.files().update(fileId=file_id, media_body=media).execute()
        print("Successfully updated ledger.json in Google Drive.")
    else:
        # Fallback just in case it got deleted
        if not folder_id:
            raise ValueError("GDRIVE_FOLDER_ID missing; cannot create new ledger.json")
            
        file_metadata = {'name': 'ledger.json', 'parents': [folder_id]}
        service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        print("Created new ledger.json in Google Drive.")