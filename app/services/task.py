import math
import os.path
import re
from os import path

from loguru import logger

from app.config import config
from app.models import const
from app.models.schema import VideoConcatMode, VideoParams
from app.services import llm, material, subtitle, video, voice
from app.services import state as sm
from app.utils import utils


def generate_script(task_id, params):
    logger.info("\n\n## generating video script")
    video_script = params.video_script.strip()
    if not video_script:
        video_script = llm.generate_script(
            video_subject=params.video_subject,
            language=params.video_language,
            paragraph_number=params.paragraph_number,
            include_emojis=getattr(params, 'enable_emojis', False)
        )
    else:
        logger.debug(f"video script: \n{video_script}")

    if not video_script:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        logger.error("failed to generate video script.")
        return None

    return video_script


def generate_terms(task_id, params, video_script):
    logger.info("\n\n## generating video terms")
    video_terms = params.video_terms
    if not video_terms:
        video_terms = llm.generate_terms(
            video_subject=params.video_subject, video_script=video_script, amount=5
        )
    else:
        if isinstance(video_terms, str):
            video_terms = [term.strip() for term in re.split(r"[,，]", video_terms)]
        elif isinstance(video_terms, list):
            video_terms = [term.strip() for term in video_terms]
        else:
            raise ValueError("video_terms must be a string or a list of strings.")

        logger.debug(f"video terms: {utils.to_json(video_terms)}")

    if not video_terms:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        logger.error("failed to generate video terms.")
        return None

    return video_terms


def save_script_data(task_id, video_script, video_terms, params):
    script_file = path.join(utils.task_dir(task_id), "script.json")
    script_data = {
        "script": video_script,
        "search_terms": video_terms,
        "params": params,
    }

    with open(script_file, "w", encoding="utf-8") as f:
        f.write(utils.to_json(script_data))


def generate_audio(task_id, params, video_script):
    logger.info("\n\n## generating audio")
    audio_file = path.join(utils.task_dir(task_id), "audio.mp3")
    sub_maker = voice.tts(
        text=video_script,
        voice_name=voice.parse_voice_name(params.voice_name),
        voice_rate=params.voice_rate,
        voice_file=audio_file,
        fast_narration=params.fast_narration,
    )
    if sub_maker is None:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        logger.error(
            """failed to generate audio:
1. check if the language of the voice matches the language of the video script.
2. check if the network is available. If you are in China, it is recommended to use a VPN and enable the global traffic mode.
        """.strip()
        )
        return None, None, None

    # Get the actual audio file path (might be .wav if MP3 conversion failed)
    actual_audio_file = getattr(sub_maker, '_actual_audio_file', audio_file)
    if actual_audio_file != audio_file:
        logger.info(f"Audio file saved as: {actual_audio_file} (instead of {audio_file})")
        audio_file = actual_audio_file

    audio_duration = math.ceil(voice.get_audio_duration(sub_maker))
    return audio_file, audio_duration, sub_maker


def generate_subtitle(task_id, params, video_script, sub_maker, audio_file):
    if not params.subtitle_enabled:
        return ""

    subtitle_path = path.join(utils.task_dir(task_id), "subtitle.srt")
    subtitle_provider = config.app.get("subtitle_provider", "edge").strip().lower()
    logger.info(f"\n\n## generating subtitle, provider: {subtitle_provider}")

    # Check if Chatterbox TTS was used by examining the voice name
    is_chatterbox = voice.is_chatterbox_voice(params.voice_name)
    
    subtitle_fallback = False
    if subtitle_provider == "edge":
        if is_chatterbox and sub_maker and sub_maker.subs:
            # Use specialized Chatterbox subtitle function for word-level timestamps
            logger.info("Using Chatterbox-optimized subtitle generation")
            voice.create_chatterbox_subtitle(
                sub_maker=sub_maker, text=video_script, subtitle_file=subtitle_path
            )
        else:
            # Use standard subtitle function for Azure TTS
            voice.create_subtitle(
                text=video_script, sub_maker=sub_maker, subtitle_file=subtitle_path
            )
        
        if not os.path.exists(subtitle_path):
            subtitle_fallback = True
            logger.warning("subtitle file not found, fallback to whisper")

    if subtitle_provider == "whisper" or subtitle_fallback:
        subtitle.create(audio_file=audio_file, subtitle_file=subtitle_path)
        logger.info("\n\n## correcting subtitle")
        subtitle.correct(subtitle_file=subtitle_path, video_script=video_script)

    # Generate enhanced subtitles if word highlighting is enabled
    if getattr(params, 'enable_word_highlighting', False):
        logger.info("\n\n## generating enhanced subtitles for word highlighting")
        enhanced_subtitle_path = path.join(utils.task_dir(task_id), "subtitle_enhanced.json")
        enhanced_subtitles = subtitle.create_enhanced_subtitles(
            audio_file=audio_file, 
            subtitle_file=enhanced_subtitle_path,
            params=params
        )
        if enhanced_subtitles:
            # Store both paths for later use
            params._enhanced_subtitle_path = enhanced_subtitle_path
            logger.info(f"enhanced subtitles created: {enhanced_subtitle_path}")

    subtitle_lines = subtitle.file_to_subtitles(subtitle_path)
    if not subtitle_lines:
        logger.warning(f"subtitle file is invalid: {subtitle_path}")
        return ""

    return subtitle_path


def get_video_materials(task_id, params, video_terms, audio_duration):
    if params.video_source == "local":
        logger.info("\n\n## preprocess local materials")
        materials = video.preprocess_video(
            materials=params.video_materials, clip_duration=params.video_clip_duration
        )
        if not materials:
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            logger.error(
                "no valid materials found, please check the materials and try again."
            )
            return None
        return [material_info.url for material_info in materials]
    else:
        logger.info(f"\n\n## downloading videos from {params.video_source}")
        downloaded_videos = material.download_videos(
            task_id=task_id,
            search_terms=video_terms,
            source=params.video_source,
            video_aspect=params.video_aspect,
            video_contact_mode=params.video_concat_mode,
            audio_duration=audio_duration * params.video_count,
            max_clip_duration=params.video_clip_duration,
        )
        
        # Download B-roll if enabled
        if getattr(params, 'enable_broll', False):
            logger.info("## downloading B-roll decorative clips")
            broll_videos = material.download_broll_materials(
                task_id=task_id,
                video_aspect=params.video_aspect,
                audio_duration=audio_duration
            )
            if broll_videos:
                params._broll_videos = broll_videos
                logger.info(f"Downloaded {len(broll_videos)} B-roll clips")

        if not downloaded_videos:
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            logger.error(
                "failed to download videos, maybe the network is not available. if you are in China, please use a VPN."
            )
            return None
        return downloaded_videos


def generate_final_videos(
    task_id, params, downloaded_videos, audio_file, subtitle_path, video_script="", audio_duration=0
):
    final_video_paths = []
    combined_video_paths = []
    
    # Chunking logic for long videos (> 5 mins) to save memory on Colab T4
    CHUNK_THRESHOLD = 300 # 5 minutes
    is_long_video = audio_duration > CHUNK_THRESHOLD
    
    video_concat_mode = params.video_concat_mode
    if params.video_count > 1 and video_concat_mode.value == "semantic":
        logger.info(f"🔄 Multiple videos requested ({params.video_count}), forcing random concatenation mode for variety")
        video_concat_mode = VideoConcatMode.random
    
    video_transition_mode = params.video_transition_mode

    _progress = 50
    for i in range(params.video_count):
        index = i + 1
        final_video_path = path.join(utils.task_dir(task_id), f"final-{index}.mp4")
        
        if is_long_video:
            logger.info(f"📦 LONG VIDEO DETECTED ({audio_duration}s). Using Smart Chunking Rendering...")
            chunk_duration = 300 # 5 minute chunks
            total_chunks = math.ceil(audio_duration / chunk_duration)
            chunk_files = []
            
            for c_idx in range(total_chunks):
                t_start = c_idx * chunk_duration
                t_end = min((c_idx + 1) * chunk_duration, audio_duration)
                chunk_logger_info = f"Chapter {c_idx+1}/{total_chunks} ({t_start}s -> {t_end}s)"
                logger.info(f"🎬 Processing {chunk_logger_info}")
                
                # Temp paths for chunk
                c_audio = path.join(utils.task_dir(task_id), f"audio_c{c_idx}.mp3")
                c_sub = path.join(utils.task_dir(task_id), f"sub_c{c_idx}.srt")
                c_combined = path.join(utils.task_dir(task_id), f"combined_c{c_idx}.mp4")
                c_final = path.join(utils.task_dir(task_id), f"final_c{c_idx}.mp4")
                
                # Extract Audio & Subtitle segments
                try:
                    from moviepy import AudioFileClip
                    AudioFileClip(audio_file).subclipped(t_start, t_end).write_audiofile(c_audio, logger=None)
                    subtitle.slice_subtitle(subtitle_path, t_start, t_end, c_sub)
                    
                    # Process chunk video
                    video.combine_videos(
                        combined_video_path=c_combined,
                        video_paths=downloaded_videos,
                        audio_file=c_audio,
                        video_aspect=params.video_aspect,
                        video_concat_mode=video_concat_mode,
                        video_transition_mode=video_transition_mode,
                        max_clip_duration=params.video_clip_duration,
                        threads=params.n_threads,
                        script=video_script,
                        params=params,
                    )
                    
                    video.generate_video(
                        video_path=c_combined,
                        audio_path=c_audio,
                        subtitle_path=c_sub,
                        output_file=c_final,
                        params=params,
                        skip_bgm=True # Important for seamless audio
                    )
                    chunk_files.append(c_final)
                except Exception as e:
                    logger.error(f"Failed to process chunk {c_idx}: {e}")
                
            # Merge all chunks with FFmpeg (Copy mode - extremely memory efficient)
            if chunk_files:
                logger.info("🧵 Merging all chapters into final video...")
                temp_merged = final_video_path.replace(".mp4", "_merged_no_bgm.mp4")
                video.concat_videos_ffmpeg(chunk_files, temp_merged)
                
                # Apply BGM to final merged file if needed
                from app.services.video import get_bgm_file, add_bgm_to_video
                bgm_file = get_bgm_file(bgm_type=params.bgm_type, bgm_file=params.bgm_file)
                if bgm_file:
                    logger.info("🎵 Adding Background Music to final long video...")
                    add_bgm_to_video(temp_merged, bgm_file, params.bgm_volume, final_video_path)
                    if os.path.exists(temp_merged): os.remove(temp_merged)
                else:
                    os.rename(temp_merged, final_video_path)
                    
                final_video_paths.append(final_video_path)
            
        else:
            # Original Single Render Logic
            combined_video_path = path.join(
                utils.task_dir(task_id), f"combined-{index}.mp4"
            )
            logger.info(f"\n\n## combining video: {index} => {combined_video_path}")
            video.combine_videos(
                combined_video_path=combined_video_path,
                video_paths=downloaded_videos,
                audio_file=audio_file,
                video_aspect=params.video_aspect,
                video_concat_mode=video_concat_mode,
                video_transition_mode=video_transition_mode,
                max_clip_duration=params.video_clip_duration,
                threads=params.n_threads,
                script=video_script,
                params=params,
            )

            _progress += 50 / params.video_count / 2
            sm.state.update_task(task_id, progress=_progress)

            logger.info(f"\n\n## generating video: {index} => {final_video_path}")
            video.generate_video(
                video_path=combined_video_path,
                audio_path=audio_file,
                subtitle_path=subtitle_path,
                output_file=final_video_path,
                params=params,
            )

            _progress += 50 / params.video_count / 2
            sm.state.update_task(task_id, progress=_progress)

            final_video_paths.append(final_video_path)
            combined_video_paths.append(combined_video_path)

    return final_video_paths, combined_video_paths


def start(task_id, params: VideoParams, stop_at: str = "video"):
    logger.info(f"start task: {task_id}, stop_at: {stop_at}")
    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=5)

    if type(params.video_concat_mode) is str:
        params.video_concat_mode = VideoConcatMode(params.video_concat_mode)

    # 1. Generate script
    video_script = generate_script(task_id, params)
    if not video_script or "Error: " in video_script:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=10)

    if stop_at == "script":
        sm.state.update_task(
            task_id, state=const.TASK_STATE_COMPLETE, progress=100, script=video_script
        )
        return {"script": video_script}

    # 2. Generate terms
    video_terms = ""
    if params.video_source != "local":
        video_terms = generate_terms(task_id, params, video_script)
        if not video_terms:
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            return

    save_script_data(task_id, video_script, video_terms, params)

    if stop_at == "terms":
        sm.state.update_task(
            task_id, state=const.TASK_STATE_COMPLETE, progress=100, terms=video_terms
        )
        return {"script": video_script, "terms": video_terms}

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=20)

    # 3 & 5. Generate audio and get materials in parallel
    from concurrent.futures import ThreadPoolExecutor
    
    logger.info("Starting parallel audio generation and material fetching...")
    
    with ThreadPoolExecutor(max_workers=2) as executor:
        # Submit audio generation task
        audio_future = executor.submit(generate_audio, task_id, params, video_script)
        
        # Submit materials fetching task
        # Note: get_video_materials needs audio_duration, which we don't have yet.
        # However, we can fetch materials using a placeholder duration or wait for audio to finish.
        # Actually, let's wait for audio_duration first to be safe with lengths, OR
        # just fetch enough materials based on an estimate. 
        # Most scripts are ~150 words per minute.
        
        # To make it truly parallel without duration bottleneck:
        # We can run them in parallel but materials might need to 'over-download' slightly.
        # Or better: Audio is usually fast. We can run terms generation and audio in parallel if terms weren't stop_at.
        
        # Re-evaluating: Let's run audio and materials in parallel. 
        # We'll use a safe estimate for duration if audio is not yet done.
        est_duration = len(video_script.split()) * 0.5 + 30 # Rough estimate
        
        materials_future = executor.submit(get_video_materials, task_id, params, video_terms, est_duration)
        
        # Wait for results
        audio_file, audio_duration, sub_maker = audio_future.result()
        downloaded_videos = materials_future.result()

    if not audio_file:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=35)

    if stop_at == "audio":
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            audio_file=audio_file,
        )
        return {"audio_file": audio_file, "audio_duration": audio_duration}

    # 4. Generate subtitle
    subtitle_path = generate_subtitle(
        task_id, params, video_script, sub_maker, audio_file
    )

    if stop_at == "subtitle":
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            subtitle_path=subtitle_path,
        )
        return {"subtitle_path": subtitle_path}

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=45)

    if not downloaded_videos:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return

    if stop_at == "materials":
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            materials=downloaded_videos,
        )
        return {"materials": downloaded_videos}

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=50)

    # 6. Generate final videos
    final_video_paths, combined_video_paths = generate_final_videos(
        task_id, params, downloaded_videos, audio_file, subtitle_path, video_script, audio_duration
    )

    if not final_video_paths:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return

    logger.success(
        f"task {task_id} finished, generated {len(final_video_paths)} videos."
    )

    kwargs = {
        "videos": final_video_paths,
        "combined_videos": combined_video_paths,
        "script": video_script,
        "terms": video_terms,
        "audio_file": audio_file,
        "audio_duration": audio_duration,
        "subtitle_path": subtitle_path,
        "materials": downloaded_videos,
    }
    sm.state.update_task(
        task_id, state=const.TASK_STATE_COMPLETE, progress=100, **kwargs
    )
    
    # Colab Compatibility: Auto-sync to Google Drive if available
    try:
        drive_path = "/content/drive/MyDrive/MoneyPrinterTurbo"
        if os.path.exists("/content/drive"):
            if not os.path.exists(drive_path):
                os.makedirs(drive_path)
            
            import shutil
            for v_path in final_video_paths:
                dest = os.path.join(drive_path, os.path.basename(v_path))
                # Add task_id to prevent overwrites
                dest = dest.replace(".mp4", f"_{task_id}.mp4")
                shutil.copy2(v_path, dest)
                logger.info(f"💾 Persistent backup saved to Google Drive: {dest}")
    except Exception as e:
        logger.warning(f"Google Drive sync failed: {e}")

    return kwargs


if __name__ == "__main__":
    task_id = "task_id"
    params = VideoParams(
        video_subject="金钱的作用",
        voice_name="zh-CN-XiaoyiNeural-Female",
        voice_rate=1.0,
    )
    start(task_id, params, stop_at="video")
