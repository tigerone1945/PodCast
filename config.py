# 設定値（変更不可の固定値を集約）

# リサーチモデル
RESEARCH_MODEL = "gemini-2.5-flash-lite"
RESEARCH_MODEL_FALLBACK = "gemini-2.5-flash"

# TTSモデル
TTS_MODEL = "gemini-2.5-flash-preview-tts"
TTS_MODEL_FALLBACK = "gemini-3.1-flash-tts-preview"

# 話者設定（MultiSpeakerVoiceConfig）
SPEAKERS = [
    {"name": "田中", "gender": "male", "voice": "Charon"},
    {"name": "鈴木", "gender": "female", "voice": "Aoede"},
]

# Google Drive アップロード先フォルダ名
DRIVE_FOLDER_NAME = "Podcasts"

# Claude Code GitHub リポジトリ
CLAUDE_CODE_GITHUB_REPO = "anthropics/claude-code"

# 台本のチャンクサイズ上限（文字数）
SCRIPT_CHUNK_SIZE = 1800

# 音声設定（Gemini TTS 出力: Linear16 PCM）
AUDIO_SAMPLE_RATE = 24000
AUDIO_CHANNELS = 1
AUDIO_SAMPLE_WIDTH = 2  # 16-bit

# リトライ設定
RETRY_WAIT_SECONDS = 60
MAX_RETRIES = 3

# 出力ディレクトリ
OUTPUT_DIR = "output"
