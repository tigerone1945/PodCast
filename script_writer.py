"""リサーチ結果からポッドキャスト台本を生成するモジュール"""

import json
import logging
import os
import time
from typing import Optional

from google import genai
from google.genai import types

from config import (
    MAX_RETRIES,
    OUTPUT_DIR,
    RESEARCH_MODEL,
    RESEARCH_MODEL_FALLBACK,
    RETRY_WAIT_SECONDS,
    SCRIPT_CHUNK_SIZE,
    SPEAKERS,
)

logger = logging.getLogger(__name__)

HOST_A = SPEAKERS[0]["name"]  # 田中（男性）
HOST_B = SPEAKERS[1]["name"]  # 鈴木（女性）


def _call_gemini_script(client: genai.Client, model: str, prompt: str) -> str:
    """Gemini で台本を生成する"""
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.7,
            response_mime_type="application/json",
        ),
    )
    return response.text


def generate_script(client: genai.Client, research_data: dict) -> dict:
    """リサーチデータからポッドキャスト台本を生成する（リトライ・フォールバック付き）"""
    version = research_data.get("version", "不明")
    key_changes = research_data.get("key_changes", "")
    bug_fixes = research_data.get("bug_fixes", "")
    x_reactions = research_data.get("x_reactions", "")
    community_reactions = research_data.get("community_reactions", "")
    practical_impact = research_data.get("practical_impact", "")

    prompt = f"""
あなたは日本語のテクノロジーポッドキャスト「Claude Code ウィークリー」の台本ライターです。
以下のリサーチ情報をもとに、2人のホストによる自然な会話形式の台本を書いてください。

## ホスト情報
- {HOST_A}（男性）: 落ち着いた技術解説担当。具体的な機能や実装面を詳しく説明する。
- {HOST_B}（女性）: 明るくユーザー視点担当。実際の使い勝手や影響を平易な言葉で伝える。

## リサーチ情報
- バージョン: {version}
- 主要な変更点: {key_changes}
- バグ修正: {bug_fixes if bug_fixes else "特になし"}
- X の反応: {x_reactions if x_reactions else "情報なし"}
- コミュニティの反応: {community_reactions if community_reactions else "情報なし"}
- 実用的な影響: {practical_impact}

## 台本の要件
- 自然な日本語会話（話し言葉、敬語は不要）
- 約5分程度（2000〜2500文字程度）
- 構成: イントロ → メインコンテンツ（変更点解説） → コミュニティ反応 → まとめ
- 各発言は「{HOST_A}: テキスト」または「{HOST_B}: テキスト」の形式
- 専門用語は適度に噛み砕いて説明
- 番組タイトルに触れる（「Claude Code ウィークリー」）

## 出力形式
以下の JSON 形式のみで出力してください（コードブロックなし）:
{{
  "version": "{version}",
  "title": "エピソードタイトル（例: Claude Code {version} の新機能を徹底解説）",
  "script": "完全な台本テキスト（改行は \\n で区切り、各発言は {HOST_A}: または {HOST_B}: で始まる）"
}}
"""

    last_error = None
    for model in [RESEARCH_MODEL, RESEARCH_MODEL_FALLBACK]:
        logger.info(f"台本生成モデル使用: {model}")
        for attempt in range(MAX_RETRIES + 1):
            try:
                raw = _call_gemini_script(client, model, prompt)
                raw_stripped = raw.strip()
                if raw_stripped.startswith("```"):
                    lines = raw_stripped.split("\n")
                    raw_stripped = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
                data = json.loads(raw_stripped)
                logger.info(f"台本生成完了: {data.get('title', version)}")
                return data
            except json.JSONDecodeError:
                logger.warning("台本 JSON パース失敗。テキストとして扱います")
                return {
                    "version": version,
                    "title": f"Claude Code {version}",
                    "script": raw,
                }
            except Exception as e:
                last_error = e
                err_str = str(e)
                is_retryable = any(
                    code in err_str for code in ["429", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE", "quota", "rate"]
                )
                if is_retryable and attempt < MAX_RETRIES:
                    logger.info(
                        f"APIエラー（{err_str[:80]}）、{RETRY_WAIT_SECONDS}秒後にリトライ"
                        f" ({attempt + 1}/{MAX_RETRIES}回目、モデル: {model})"
                    )
                    time.sleep(RETRY_WAIT_SECONDS)
                else:
                    logger.warning(f"モデル {model} の全リトライ失敗: {err_str[:80]}")
                    break

    raise RuntimeError(f"台本生成失敗（全モデル・全リトライ消費）: {last_error}")


def split_script_into_chunks(script: str, max_chars: int = SCRIPT_CHUNK_SIZE) -> list[str]:
    """
    台本を1800文字未満のチャンクに分割する。
    発言単位ではなく、複数発言をまとめたチャンク単位で処理する。
    """
    lines = [line.strip() for line in script.split("\n") if line.strip()]
    chunks = []
    current_chunk_lines = []
    current_length = 0

    for line in lines:
        line_len = len(line) + 1  # +1 for newline
        if current_length + line_len >= max_chars and current_chunk_lines:
            chunks.append("\n".join(current_chunk_lines))
            current_chunk_lines = [line]
            current_length = line_len
        else:
            current_chunk_lines.append(line)
            current_length += line_len

    if current_chunk_lines:
        chunks.append("\n".join(current_chunk_lines))

    logger.info(f"台本を {len(chunks)} チャンクに分割しました（最大{max_chars}文字/チャンク）")
    return chunks


def run_script_generation(client: genai.Client, research_data: dict) -> dict:
    """台本生成のメイン処理。script.json に保存して返す。"""
    script_data = generate_script(client, research_data)

    script_text = script_data.get("script", "")
    chunks = split_script_into_chunks(script_text)
    script_data["chunks"] = chunks
    script_data["chunk_count"] = len(chunks)

    script_path = os.path.join(OUTPUT_DIR, "script.json")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(script_path, "w", encoding="utf-8") as f:
        json.dump(script_data, f, ensure_ascii=False, indent=2)
    logger.info(f"台本を保存しました: {script_path}")

    return script_data
