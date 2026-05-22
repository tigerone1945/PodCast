"""Google Drive への OAuth2.0 認証付きアップロードモジュール"""

import json
import logging
import os
from typing import Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from config import DRIVE_FOLDER_NAME, OUTPUT_DIR

logger = logging.getLogger(__name__)

DRIVE_CONFIG_PATH = os.path.join(OUTPUT_DIR, "drive_config.json")
TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def create_drive_service(client_id: str, client_secret: str, refresh_token: str):
    """OAuth2.0 認証情報から Drive サービスクライアントを生成する"""
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=TOKEN_URI,
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )
    service = build("drive", "v3", credentials=creds)
    logger.info("Google Drive サービスクライアントを作成しました")
    return service


def _load_drive_config() -> dict:
    """保存済みの Drive 設定（フォルダ ID など）を読み込む"""
    if os.path.exists(DRIVE_CONFIG_PATH):
        with open(DRIVE_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_drive_config(data: dict) -> None:
    """Drive 設定をファイルに保存する"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(DRIVE_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"Drive 設定を保存しました: {DRIVE_CONFIG_PATH}")


def find_or_create_folder(service, name: str, parent_id: Optional[str] = None) -> str:
    """
    指定名のフォルダを検索し、なければ作成してフォルダ ID を返す。
    drive.file スコープのため、このアプリが作成したフォルダのみ検索対象になる。
    """
    query_parts = [
        f"name='{name}'",
        "mimeType='application/vnd.google-apps.folder'",
        "trashed=false",
    ]
    if parent_id:
        query_parts.append(f"'{parent_id}' in parents")

    query = " and ".join(query_parts)
    results = service.files().list(
        q=query,
        spaces="drive",
        fields="files(id, name)",
    ).execute()

    files = results.get("files", [])
    if files:
        folder_id = files[0]["id"]
        logger.info(f"フォルダ '{name}' を発見しました (ID: {folder_id})")
        return folder_id

    # フォルダが存在しない場合は作成
    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        metadata["parents"] = [parent_id]

    folder = service.files().create(body=metadata, fields="id").execute()
    folder_id = folder.get("id")
    logger.info(f"フォルダ '{name}' を作成しました (ID: {folder_id})")
    return folder_id


def upload_mp3(service, mp3_path: str, subfolder_name: str) -> str:
    """
    MP3 を Podcasts/{subfolder_name}/ にアップロードしてファイル ID を返す。
    subfolder_name は "v1.2.3_2026-05-22" などのバージョン+日付形式。
    """
    drive_config = _load_drive_config()

    # 親フォルダ（Podcasts）を取得または作成
    podcasts_folder_id = drive_config.get("podcasts_folder_id")
    if podcasts_folder_id:
        logger.info(f"保存済み Podcasts フォルダ ID を使用: {podcasts_folder_id}")
    else:
        podcasts_folder_id = find_or_create_folder(service, DRIVE_FOLDER_NAME)
        drive_config["podcasts_folder_id"] = podcasts_folder_id
        _save_drive_config(drive_config)

    # サブフォルダ（バージョン+日付）を作成
    subfolder_id = find_or_create_folder(service, subfolder_name, parent_id=podcasts_folder_id)

    # MP3 をアップロード
    file_name = os.path.basename(mp3_path)
    metadata = {
        "name": file_name,
        "parents": [subfolder_id],
    }
    media = MediaFileUpload(mp3_path, mimetype="audio/mpeg", resumable=True)
    uploaded = service.files().create(
        body=metadata,
        media_body=media,
        fields="id, name, webViewLink",
    ).execute()

    file_id = uploaded.get("id")
    web_link = uploaded.get("webViewLink", "")
    logger.info(
        f"MP3 アップロード完了: {file_name}"
        f"\n  ファイル ID: {file_id}"
        f"\n  Google Drive リンク: {web_link}"
        f"\n  フォルダ: {DRIVE_FOLDER_NAME}/{subfolder_name}"
    )
    return file_id


def run_upload(mp3_path: str, version: str, run_date: str) -> Optional[str]:
    """Drive アップロードのメイン処理。ファイル ID または None を返す。"""
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    refresh_token = os.environ.get("GOOGLE_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        raise EnvironmentError(
            "Google OAuth 環境変数が不足しています: "
            "GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN"
        )

    service = create_drive_service(client_id, client_secret, refresh_token)

    # バージョン文字列を安全なフォルダ名に変換（例: "v1.2.3" → "v1.2.3"）
    safe_version = version.replace("/", "_").replace(" ", "_")
    subfolder_name = f"{safe_version}_{run_date}"

    file_id = upload_mp3(service, mp3_path, subfolder_name)
    return file_id
