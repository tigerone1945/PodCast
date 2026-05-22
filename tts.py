"""Gemini TTS で台本を音声に変換するモジュール（PCM → WAV → MP3）"""

import logging
import os
import time
import wave
from typing import Optional

from google import genai
from google.genai import types
from pydub import AudioSegment

from config import (
    AUDIO_CHANNELS,
    AUDIO_SAMPLE_RATE,
    AUDIO_SAMPLE_WIDTH,
    MAX_RETRIES,
    OUTPUT_DIR,
    RETRY_WAIT_SECONDS,
    SPEAKERS,
    TTS_MODEL,
    TTS_MODEL_FALLBACK,
)

logger = logging.getLogger(__name__)


def _build_speech_config() -> types.SpeechConfig:
    """MultiSpeakerVoiceConfig を構築する"""
    speaker_voice_configs = []
    for speaker in SPEAKERS:
        speaker_voice_configs.append(
            types.SpeakerVoiceConfig(
                speaker=speaker["name"],
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=speaker["voice"]
                    )
                ),
            )
        )
    return types.SpeechConfig(
        multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(
            speaker_voice_configs=speaker_voice_configs
        )
    )


def _call_tts(client: genai.Client, model: str, text: str) -> bytes:
    """Gemini TTS API を呼び出して PCM 音声バイトを返す"""
    response = client.models.generate_content(
        model=model,
        contents=text,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=_build_speech_config(),
        ),
    )
    part = response.candidates[0].content.parts[0]
    audio_data = part.inline_data.data

    # SDK バージョンによっては base64 エンコード済みの場合がある
    if isinstance(audio_data, str):
        import base64
        audio_data = base64.b64decode(audio_data)

    return audio_data


def _save_pcm_as_wav(pcm_data: bytes, output_path: str) -> None:
    """PCM バイト列を WAV ファイルとして保存する"""
    with wave.open(output_path, "wb") as wf:
        wf.setnchannels(AUDIO_CHANNELS)
        wf.setsampwidth(AUDIO_SAMPLE_WIDTH)
        wf.setframerate(AUDIO_SAMPLE_RATE)
        wf.writeframes(pcm_data)


def generate_chunk_audio(
    client: genai.Client, chunk_text: str, chunk_index: int
) -> Optional[str]:
    """
    1チャンクの台本を音声に変換して WAV として保存する。
    失敗時は None を返す。
    """
    wav_path = os.path.join(OUTPUT_DIR, f"chunk_{chunk_index:03d}.wav")
    last_error = None

    for model in [TTS_MODEL, TTS_MODEL_FALLBACK]:
        logger.info(f"TTSモデル使用: {model}（チャンク {chunk_index + 1}）")
        for attempt in range(MAX_RETRIES + 1):
            try:
                pcm_data = _call_tts(client, model, chunk_text)
                _save_pcm_as_wav(pcm_data, wav_path)
                logger.info(
                    f"チャンク {chunk_index + 1} の音声生成完了: {wav_path}"
                    f"（{len(pcm_data):,} bytes）"
                )
                return wav_path
            except Exception as e:
                last_error = e
                err_str = str(e)
                is_retryable = any(
                    code in err_str
                    for code in ["429", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE", "quota", "rate"]
                )
                if is_retryable and attempt < MAX_RETRIES:
                    logger.info(
                        f"TTS APIエラー（{err_str[:80]}）、{RETRY_WAIT_SECONDS}秒後にリトライ"
                        f" ({attempt + 1}/{MAX_RETRIES}回目、モデル: {model})"
                    )
                    time.sleep(RETRY_WAIT_SECONDS)
                else:
                    logger.warning(f"モデル {model} の全リトライ失敗: {err_str[:80]}")
                    break

    logger.error(f"チャンク {chunk_index + 1} の音声生成に失敗しました: {last_error}")
    return None


def combine_wav_to_mp3(wav_paths: list[str], output_mp3: str) -> bool:
    """
    複数の WAV ファイルを結合して MP3 に変換する。
    pydub（内部で FFmpeg を使用）を利用。
    """
    if not wav_paths:
        logger.error("結合する WAV ファイルがありません")
        return False

    logger.info(f"{len(wav_paths)} 個の WAV ファイルを結合中...")
    combined = AudioSegment.empty()
    for wav_path in sorted(wav_paths):
        seg = AudioSegment.from_wav(wav_path)
        combined += seg
        logger.info(f"  結合: {os.path.basename(wav_path)}（{len(seg) / 1000:.1f}秒）")

    total_seconds = len(combined) / 1000
    logger.info(f"合計時間: {total_seconds:.1f}秒（{total_seconds / 60:.1f}分）")

    combined.export(output_mp3, format="mp3", bitrate="128k")
    logger.info(f"MP3 エクスポート完了: {output_mp3}")
    return True


def run_tts(client: genai.Client, script_chunks: list[str]) -> Optional[str]:
    """
    全チャンクの TTS を実行してポッドキャスト MP3 を生成する。
    成功した場合は MP3 パスを返す。失敗チャンクがあっても継続する。
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    wav_paths = []
    failed_chunks = []

    for i, chunk in enumerate(script_chunks):
        logger.info(f"チャンク {i + 1}/{len(script_chunks)} を処理中（{len(chunk)}文字）")
        wav_path = generate_chunk_audio(client, chunk, i)
        if wav_path:
            wav_paths.append(wav_path)
        else:
            failed_chunks.append(i + 1)

    if failed_chunks:
        logger.warning(f"以下のチャンクが失敗しました: {failed_chunks}")

    if not wav_paths:
        logger.error("有効な音声チャンクが1件もありません。MP3 生成をスキップします")
        return None

    mp3_path = os.path.join(OUTPUT_DIR, "podcast.mp3")
    success = combine_wav_to_mp3(wav_paths, mp3_path)
    if success:
        return mp3_path
    return None
