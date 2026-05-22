"""ポッドキャスト自動生成のメインオーケストレーター"""

import json
import logging
import os
import sys
from datetime import date

from google import genai

from config import OUTPUT_DIR
from drive import run_upload
from research import load_researched_versions, run_research, save_researched_versions
from script_writer import run_script_generation
from tts import run_tts

# ログ設定（日本語、タイムスタンプ付き）
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def main() -> None:
    logger.info("=" * 60)
    logger.info("ポッドキャスト自動生成を開始します")
    logger.info("=" * 60)

    # 実行日付（DATE_OVERRIDE 環境変数で上書き可能）
    date_override = os.environ.get("DATE_OVERRIDE", "").strip()
    run_date = date_override if date_override else date.today().isoformat()
    logger.info(f"実行日付: {run_date}")

    # Gemini API キーの確認
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.error("環境変数 GEMINI_API_KEY が設定されていません")
        sys.exit(1)

    client = genai.Client(api_key=api_key)
    logger.info("Gemini クライアントを初期化しました")

    # 出力ディレクトリの作成
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # フラグ管理（途中成果物コミット用）
    research_data = None
    script_data = None
    mp3_path = None
    drive_file_id = None
    success = True

    try:
        # ステップ1: リサーチ
        logger.info("--- ステップ1: リサーチ ---")
        research_data = run_research(client)

        if research_data is None:
            logger.info("新しい未調査バージョンが見つかりませんでした。処理を終了します。")
            return

        version = research_data.get("version", "unknown")
        logger.info(f"調査対象バージョン: {version}")

        # ステップ2: 台本生成
        logger.info("--- ステップ2: 台本生成 ---")
        script_data = run_script_generation(client, research_data)
        chunks = script_data.get("chunks", [])
        logger.info(f"台本チャンク数: {len(chunks)}")

        # ステップ3: 音声生成（TTS）
        logger.info("--- ステップ3: 音声生成（TTS） ---")
        mp3_path = run_tts(client, chunks)

        if mp3_path is None:
            logger.error("MP3 生成に失敗しました")
            success = False
        else:
            logger.info(f"MP3 生成完了: {mp3_path}")

            # ステップ4: Google Drive アップロード
            logger.info("--- ステップ4: Google Drive アップロード ---")
            drive_file_id = run_upload(mp3_path, version, run_date)
            logger.info(f"Google Drive アップロード完了（ファイル ID: {drive_file_id}）")

        # ステップ5: 調査済みバージョン履歴を更新
        logger.info("--- ステップ5: 履歴更新 ---")
        history = load_researched_versions()
        history.setdefault("researched_versions", []).append(
            {
                "version": version,
                "date": run_date,
                "drive_file_id": drive_file_id or "",
                "title": script_data.get("title", "") if script_data else "",
            }
        )
        save_researched_versions(history)

    except Exception as e:
        logger.error(f"予期しないエラーが発生しました: {e}", exc_info=True)
        success = False

        # 途中成果物をエラー情報として保存
        error_info = {
            "error": str(e),
            "run_date": run_date,
            "step_completed": {
                "research": research_data is not None,
                "script": script_data is not None,
                "audio": mp3_path is not None,
                "upload": drive_file_id is not None,
            },
        }
        error_path = os.path.join(OUTPUT_DIR, "error.json")
        with open(error_path, "w", encoding="utf-8") as f:
            json.dump(error_info, f, ensure_ascii=False, indent=2)
        logger.info(f"エラー情報を保存しました: {error_path}")

    finally:
        logger.info("=" * 60)
        if success:
            logger.info("ポッドキャスト自動生成が正常に完了しました")
        else:
            logger.error("ポッドキャスト自動生成が失敗しました（途中成果物はコミットされます）")
        logger.info("=" * 60)

        if not success:
            sys.exit(1)


if __name__ == "__main__":
    main()
