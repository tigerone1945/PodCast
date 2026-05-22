"""GitHub Releases API + Gemini Google Search Grounding でバージョン調査を行うモジュール"""

import json
import logging
import os
import time
from typing import Optional

import requests
from google import genai
from google.genai import types

from config import (
    CLAUDE_CODE_GITHUB_REPO,
    MAX_RETRIES,
    OUTPUT_DIR,
    RESEARCH_MODEL,
    RESEARCH_MODEL_FALLBACK,
    RETRY_WAIT_SECONDS,
)

logger = logging.getLogger(__name__)

RESEARCHED_VERSIONS_PATH = os.path.join(OUTPUT_DIR, "researched_versions.json")


def get_github_releases(repo: str) -> list[dict]:
    """GitHub Releases API からリリース一覧を取得する"""
    url = f"https://api.github.com/repos/{repo}/releases"
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    logger.info(f"GitHub Releases API を取得中: {url}")
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    releases = resp.json()
    logger.info(f"{len(releases)} 件のリリースを取得しました")
    return releases


def load_researched_versions() -> dict:
    """調査済みバージョン履歴を読み込む（ファイルがなければ空を返す）"""
    if not os.path.exists(RESEARCHED_VERSIONS_PATH):
        return {"researched_versions": []}
    with open(RESEARCHED_VERSIONS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_researched_versions(data: dict) -> None:
    """調査済みバージョン履歴を保存する"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(RESEARCHED_VERSIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"調査済みバージョン履歴を保存しました: {RESEARCHED_VERSIONS_PATH}")


def find_unresearched_version(releases: list[dict], history: dict) -> Optional[dict]:
    """最新の未調査バージョンを1件返す（最新順）"""
    researched = {v["version"] for v in history.get("researched_versions", [])}
    for release in sorted(releases, key=lambda r: r.get("published_at", ""), reverse=True):
        tag = release.get("tag_name", "")
        if tag and tag not in researched and not release.get("prerelease", False):
            logger.info(f"未調査バージョン発見: {tag}")
            return release
    logger.info("新しい未調査バージョンはありません")
    return None


def _call_gemini_research(client: genai.Client, model: str, prompt: str) -> str:
    """Gemini + Google Search Grounding でリサーチを実行する"""
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.3,
        ),
    )
    return response.text


def research_version(client: genai.Client, release: dict) -> dict:
    """指定バージョンの変更点・X の反応をリサーチする（リトライ・フォールバック付き）"""
    version = release.get("tag_name", "unknown")
    release_body = release.get("body", "")
    published_at = release.get("published_at", "")

    prompt = f"""
あなたはテクノロジーポッドキャストのリサーチャーです。
Claude Code（Anthropic が開発した AI コーディングアシスタント CLI）の {version} について詳しく調査してください。

## GitHub リリースノート
{release_body[:3000] if release_body else "（情報なし）"}

## 調査してください

1. **主要な変更点・新機能**: このバージョンで何が変わったか、具体的に説明してください。
2. **バグ修正**: 重要なバグ修正があれば記載してください。
3. **X（旧Twitter）の公開投稿**: Google Search で「Claude Code {version} site:x.com OR site:twitter.com」などを検索し、開発者やユーザーの反応・評価をまとめてください。
4. **技術コミュニティの反応**: Reddit、Hacker News、GitHub Issues などでの議論や評価。
5. **実用的な影響**: ユーザーにとって最も重要な変化は何か。

## 出力形式
以下の JSON 形式で回答してください（コードブロックなし、JSONのみ）:
{{
  "version": "{version}",
  "published_at": "{published_at}",
  "key_changes": "主要な変更点の詳細説明（500文字程度）",
  "bug_fixes": "バグ修正の説明（200文字程度、なければ空文字）",
  "x_reactions": "X のユーザー反応まとめ（300文字程度）",
  "community_reactions": "コミュニティ全体の反応（300文字程度）",
  "practical_impact": "実用的な影響・重要な変化（200文字程度）"
}}
"""

    last_error = None
    for model in [RESEARCH_MODEL, RESEARCH_MODEL_FALLBACK]:
        logger.info(f"リサーチモデル使用: {model}")
        for attempt in range(MAX_RETRIES + 1):
            try:
                raw = _call_gemini_research(client, model, prompt)
                # JSON 部分を抽出してパース
                raw_stripped = raw.strip()
                if raw_stripped.startswith("```"):
                    lines = raw_stripped.split("\n")
                    raw_stripped = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
                data = json.loads(raw_stripped)
                data["release_notes_raw"] = release_body[:5000]
                logger.info(f"リサーチ完了: {version}")
                return data
            except json.JSONDecodeError:
                # JSON パース失敗時はテキストそのまま格納
                logger.warning("JSON パース失敗。テキストとして保存します")
                return {
                    "version": version,
                    "published_at": published_at,
                    "key_changes": raw,
                    "bug_fixes": "",
                    "x_reactions": "",
                    "community_reactions": "",
                    "practical_impact": "",
                    "release_notes_raw": release_body[:5000],
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

    raise RuntimeError(f"リサーチ失敗（全モデル・全リトライ消費）: {last_error}")


def run_research(client: genai.Client) -> Optional[dict]:
    """
    メインのリサーチ処理。
    未調査の最新 Claude Code バージョンを1件調査して返す。
    新バージョンがなければ None を返す。
    """
    releases = get_github_releases(CLAUDE_CODE_GITHUB_REPO)
    history = load_researched_versions()
    release = find_unresearched_version(releases, history)

    if release is None:
        return None

    research_data = research_version(client, release)

    # 結果を保存
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    research_path = os.path.join(OUTPUT_DIR, "research.json")
    with open(research_path, "w", encoding="utf-8") as f:
        json.dump(research_data, f, ensure_ascii=False, indent=2)
    logger.info(f"リサーチ結果を保存しました: {research_path}")

    return research_data
