# Claude Code Podcast 自動生成システム

Claude Code の最新バージョン変更点を自動調査し、日本語ポッドキャストを生成して Google Drive にアップロードするシステムです。

毎日 JST 6:00 に自動実行されます（GitHub Actions）。

---

## システム概要

```
GitHub Releases API（Claude Code 最新版取得）
    ↓
Gemini 2.5 Flash Lite + Google Search Grounding（変更点・X反応を調査）
    ↓
Gemini（台本生成）
    ↓
Gemini 2.5 Flash Preview TTS（音声生成・田中/鈴木 二人の会話）
    ↓
Google Drive（Podcasts/{バージョン}_{日付}/ にアップロード）
```

---

## セットアップ手順

### 1. Gemini API キーの取得

1. [Google AI Studio](https://aistudio.google.com/) にアクセス
2. 「Get API key」から API キーを作成
3. キーをコピーして後の手順で使用

### 2. Google Cloud OAuth クライアントの作成

1. [Google Cloud Console](https://console.cloud.google.com/) を開く
2. プロジェクトを作成または選択
3. 「APIとサービス」→「有効な API とサービス」→「API を有効にする」
4. **Google Drive API** を検索して有効化
5. 「認証情報」→「認証情報を作成」→「OAuth クライアント ID」を選択
6. アプリの種類: **ウェブアプリケーション**
7. 承認済みリダイレクト URI に以下を追加:
   ```
   https://developers.google.com/oauthplayground
   ```
8. 作成後、**クライアント ID** と **クライアント シークレット** をコピー
9. OAuth 同意画面を「本番環境」に設定（テスト環境のままだとリフレッシュトークンが7日で失効）

### 3. リフレッシュトークンの取得（OAuth2.0 Playground）

1. [OAuth2.0 Playground](https://developers.google.com/oauthplayground) を開く
2. 右上の歯車アイコン「OAuth 2.0 configuration」をクリック
3. 「Use your own OAuth credentials」にチェック
4. Client ID と Client Secret を入力して閉じる
5. 「Step 1」のスコープ入力欄に以下を入力して「Authorize APIs」:
   ```
   https://www.googleapis.com/auth/drive.file
   ```
6. Google アカウントでログインして許可
7. 「Step 2」で「Exchange authorization code for tokens」をクリック
8. 表示された **Refresh token** をコピー

### 4. GitHub リポジトリの作成

1. GitHub で新しいパブリックリポジトリを作成（Actions 無料枠が無制限になる）
2. このコードをプッシュ（git 操作は別途実施）

### 5. GitHub Secrets の設定

リポジトリの「Settings」→「Secrets and variables」→「Actions」で以下を追加:

| Secret 名 | 値 | 説明 |
|---|---|---|
| `GEMINI_API_KEY` | Gemini API キー | Google AI Studio で取得したキー |
| `GOOGLE_CLIENT_ID` | OAuth クライアント ID | Cloud Console で作成したクライアント ID |
| `GOOGLE_CLIENT_SECRET` | OAuth クライアントシークレット | Cloud Console で作成したシークレット |
| `GOOGLE_REFRESH_TOKEN` | リフレッシュトークン | OAuth2.0 Playground で取得したトークン |

**設定順序**: `GEMINI_API_KEY` → `GOOGLE_CLIENT_ID` → `GOOGLE_CLIENT_SECRET` → `GOOGLE_REFRESH_TOKEN`

---

## 実行方法

### 自動実行（毎日 JST 6:00）

設定完了後、毎日自動的に実行されます。GitHub Actions の「Actions」タブで実行履歴を確認できます。

### 手動実行

1. GitHub リポジトリの「Actions」タブを開く
2. 左側の「Daily Podcast Generation」を選択
3. 「Run workflow」ボタンをクリック
4. `date_override` は空のままで「Run workflow」を実行

特定の日付で生成したい場合は `date_override` に日付文字列（例: `2026-05-22`）を入力してください。

---

## ファイル構成

```
.
├── main.py                   # メインオーケストレーター
├── config.py                 # 設定値（話者・モデル名など）
├── research.py               # GitHub API + Gemini リサーチ
├── script_writer.py          # 台本生成
├── tts.py                    # テキスト→音声変換
├── drive.py                  # Google Drive アップロード
├── requirements.txt          # Python 依存パッケージ
├── .github/
│   └── workflows/
│       └── podcast.yml       # GitHub Actions ワークフロー
└── output/
    ├── research.json         # 調査結果（git 管理）
    ├── script.json           # 生成台本（git 管理）
    ├── researched_versions.json  # 調査済みバージョン履歴（git 管理）
    ├── drive_config.json     # Drive フォルダ ID キャッシュ（git 管理）
    ├── chunk_*.wav           # 音声チャンク（.gitignore 除外）
    └── podcast.mp3           # 最終 MP3（.gitignore 除外）
```

---

## 話者設定

| 名前 | 性別 | 声（Gemini TTS） | 役割 |
|---|---|---|---|
| 田中 | 男性 | Charon | 落ち着いた技術解説担当 |
| 鈴木 | 女性 | Aoede | 明るいユーザー視点担当 |

---

## 使用モデル

| 用途 | メインモデル | フォールバックモデル |
|---|---|---|
| リサーチ・台本生成 | `gemini-2.5-flash-lite` | `gemini-2.5-flash` |
| 音声生成（TTS） | `gemini-2.5-flash-preview-tts` | `gemini-3.1-flash-tts-preview` |

API 制限（429/503）発生時は 60 秒待機後にリトライ（最大3回）。全リトライ失敗時はフォールバックモデルに切り替えます。

---

## トラブルシューティング

- **リフレッシュトークンが失効する**: OAuth 同意画面が「テスト環境」のままになっています。「本番環境」に変更してトークンを再取得してください。
- **Google Drive にフォルダが見つからない**: `drive.file` スコープの仕様上、このアプリが作成したフォルダのみアクセス可能です。初回実行時に `Podcasts` フォルダが自動作成されます。
- **新しいバージョンが見つからない**: `output/researched_versions.json` に記録済みのバージョンはスキップされます。
